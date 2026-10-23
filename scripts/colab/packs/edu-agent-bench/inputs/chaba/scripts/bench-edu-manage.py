#!/usr/bin/env python3
"""bench-edu-manage.py — card edu-agent-benchmark.

A/B three education-managing lanes on ONE fixed fixture corpus
(scripts/bench-edu-corpus.json) against a LOCAL mock WP-lesson store —
never prod WP:

  current  today's pipeline, run faithfully: mechanical question filter
           -> gemini-3.5-flash-lite classify (real CLASSIFY_PROMPT) ->
           per-topic draft (real DRAFT_PROMPT) -> lesson-add upsert
           semantics (slug = md5(topic), meta overwrite, +7d default).
           Ops/recall tasks use the deterministic scripted-equivalent
           (the documented manual step a correct operator would run).
  clawbot  OpenClaw-shaped agent surface — tool-calling loop with the
           mock store CRUD — on its default provider. The real gateway
           (tony-omen 127.0.0.1:18789) is loopback-only, so this lane
           runs the same loop in-process on openrouter/free (its stated
           primary). Interpretation documented in the report.
  hermes   the identical agent surface pointed at omen ollama /v1
           hermes3:8b (T1 tool-call slot, card try-hermes).

Task suite (golden labels in the corpus):
  transcript  capture-judgment (file/skip -> P/R/F1), dedupe/upsert
              discipline (create vs update vs hub-create), draft HTML
  ops         next_review scheduling + status-transition correctness
  recall      recall pointer accuracy
Cross-lane: tool-loop completion, p50 latency, tokens/task (all lanes
are $0 free-tier — cost reported as tokens). One fixed LLM judge
(gemini-3.5-flash-lite) grades every draft on a 5-axis rubric.

Usage:
  python3 scripts/bench-edu-manage.py                 # all lanes, full suite
  python3 scripts/bench-edu-manage.py --lanes hermes --tasks t1-create-bbr-cubic
  python3 scripts/bench-edu-manage.py --no-judge --out /tmp/bench
Env: OLLAMA_URL (default http://100.75.102.88:11434), OPENROUTER_API_KEY
or ~/.config/secrets/openrouter.env, GEMINI_API_KEY or the usual secrets
files. Keys are loaded at runtime and never printed.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
import re
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ada"))
import gemini_rest  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "lesson_miner", REPO / "scripts" / "ada" / "lesson-miner.py")
lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lm)

CORPUS = REPO / "scripts" / "bench-edu-corpus.json"
CURRENT_MODEL = "gemini-3.5-flash-lite"
JUDGE_MODEL = "gemini-3.5-flash-lite"
OR_BASE = "https://openrouter.ai/api/v1"
OR_MODEL = "openrouter/free"  # OpenClaw's stated primary
HERMES_MODEL = "hermes3:8b"
MAX_ROUNDS = 10

SECRET_FILES = ("~/.config/secrets/mddb-gemini.env",
                "~/.config/secrets/gemini-keys.env",
                "~/.config/secrets/gemini-api-key.env",
                "~/.config/secrets/ada-pi-pwa.env")


def load_secret(var_names: tuple[str, ...], extra_files: tuple[str, ...] = (),
                env_files: tuple[str, ...] = SECRET_FILES) -> str | None:
    for v in var_names:
        if os.environ.get(v):
            return os.environ[v]
    for f in list(env_files) + list(extra_files):
        try:
            for ln in open(os.path.expanduser(f)):
                m = re.match(r"^([A-Z_]+)=(.*)$", ln.strip())
                if m and m.group(1) in var_names:
                    return m.group(2).strip().strip('"').strip("'")
        except OSError:
            pass
    return None


def resolve_day(v: str) -> str:
    """'today+N' / 'today-N' / '-Nd' offsets -> ISO date; else literal."""
    m = re.match(r"^today([+-]\d+)$", str(v))
    if m:
        return (date.today() + timedelta(days=int(m.group(1)))).isoformat()
    m = re.match(r"^([+-]\d+)d$", str(v))
    if m:
        return (date.today() + timedelta(days=int(m.group(1)))).isoformat()
    return str(v)


def slug_of(topic: str) -> str:
    return "lesson-" + hashlib.md5(
        topic.strip().lower().encode()).hexdigest()[:12]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def topic_matches(pred_topic: str, match_list: list[str]) -> bool:
    p = norm(pred_topic)
    return any(norm(m) in p or p in norm(m) for m in match_list)


# ---------------------------------------------------------------- mock store

class MockStore:
    """Local stand-in for the WP lesson CPT. Slug = md5(topic) exactly
    like lesson-add.py; create refuses a taken slug so agents must use
    update — that IS the dedupe discipline being measured."""

    def __init__(self, seed: list[dict]):
        self.recs: dict[str, dict] = {}
        self.next_id = 100
        for s in seed:
            r = {
                "slug": slug_of(s["topic"]),
                "title": f"Education — {s['topic']}",
                "topic": s["topic"],
                "level": s.get("level", "intro"),
                "source": s.get("source", "chat"),
                "learned_at": resolve_day(s.get("learned_at", "today+0")),
                "next_review": resolve_day(s.get("next_review", "today+7")),
                "status": s.get("status", "open"),
                "content": s.get("content", ""),
            }
            self.recs[r["slug"]] = r
        self.seed_slugs = set(self.recs)

    def _compact(self, r: dict) -> dict:
        return {k: r[k] for k in
                ("slug", "title", "topic", "level", "status",
                 "learned_at", "next_review")}

    def search(self, query: str) -> list[dict]:
        q = norm(query)
        out = [self._compact(r) for r in self.recs.values()
               if q in norm(r["topic"] + " " + r["title"] + " " + r["content"])]
        return out or []

    def list_all(self) -> list[dict]:
        return [self._compact(r) for r in self.recs.values()]

    def get(self, slug: str) -> dict:
        r = self.recs.get(slug)
        return dict(r) if r else {"error": f"no lesson {slug}"}

    def create(self, topic, level="intro", source="voice", content_html="",
               next_review=None, status="open"):
        slug = slug_of(topic)
        if slug in self.recs:
            return {"error": f"lesson {slug} already exists — use lesson_update"}
        r = {"slug": slug, "title": f"Education — {topic}", "topic": topic,
             "level": level, "source": source,
             "learned_at": date.today().isoformat(),
             "next_review": resolve_day(next_review) if next_review
             else (date.today() + timedelta(days=7)).isoformat(),
             "status": status, "content": content_html}
        r["id"] = self.next_id
        self.next_id += 1
        self.recs[slug] = r
        return {"created": self._compact(r)}

    def update(self, slug, content_html=None, next_review=None, status=None,
               level=None, topic=None):
        r = self.recs.get(slug)
        if not r:
            return {"error": f"no lesson {slug}"}
        if content_html is not None:
            r["content"] = content_html
        if next_review is not None:
            r["next_review"] = resolve_day(next_review)
        if status is not None:
            r["status"] = status
        if level is not None:
            r["level"] = level
        if topic is not None:
            r["topic"] = topic
            r["title"] = f"Education — {topic}"
        return {"updated": self._compact(r)}

    def upsert_add(self, topic, level, source, content_html,
                   next_review=None, status="open"):
        """lesson-add.py semantics verbatim: EVERY filing overwrites the
        whole meta block — a re-filed lesson resets status to --status
        (default open) and next_review to +7d. This is the real
        pipeline's behavior, quirks included."""
        slug = slug_of(topic)
        existed = slug in self.recs
        r = {"slug": slug, "title": f"Education — {topic}", "topic": topic,
             "level": level, "source": source,
             "learned_at": date.today().isoformat(),
             "next_review": resolve_day(next_review) if next_review
             else (date.today() + timedelta(days=7)).isoformat(),
             "status": status, "content": content_html,
             "id": self.recs.get(slug, {}).get("id", self.next_id)}
        if not existed:
            self.next_id += 1
        self.recs[slug] = r
        return ("updated" if existed else "created"), r

    def due(self) -> list[dict]:
        today = date.today().isoformat()
        return [self._compact(r) for r in self.recs.values()
                if r["status"] != "learned" and r["next_review"] <= today]


TOOLS = [
    {"type": "function", "function": {
        "name": "lesson_search",
        "description": "Search lessons by substring over topic, title and content.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "lesson_list",
        "description": "List all lessons (compact records).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "lesson_get",
        "description": "Fetch one full lesson by slug.",
        "parameters": {"type": "object", "properties": {
            "slug": {"type": "string"}}, "required": ["slug"]}}},
    {"type": "function", "function": {
        "name": "lesson_create",
        "description": "File a NEW lesson. Fails if a lesson with the same "
                       "topic already exists — then use lesson_update. Slug "
                       "is derived from the topic automatically.",
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "3-8 word English topic"},
            "level": {"type": "string", "enum": ["intro", "working", "deep"]},
            "content_html": {"type": "string", "description":
                             "Standalone fragment: h3/h4/p/ul/ol/li/code/pre/"
                             "strong/em/a only, no h1/h2/html/head/body"},
            "next_review": {"type": "string",
                            "description": "ISO date or 'today+N'; default +7d"},
            "status": {"type": "string", "enum": ["open", "learned"]},
            "source": {"type": "string"}},
            "required": ["topic", "content_html"]}}},
    {"type": "function", "function": {
        "name": "lesson_update",
        "description": "Update an existing lesson's content and/or meta by slug.",
        "parameters": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "content_html": {"type": "string"},
            "next_review": {"type": "string",
                            "description": "ISO date or 'today+N'"},
            "status": {"type": "string", "enum": ["open", "learned"]},
            "level": {"type": "string", "enum": ["intro", "working", "deep"]},
            "topic": {"type": "string"}},
            "required": ["slug"]}}},
    {"type": "function", "function": {
        "name": "lessons_due",
        "description": "List lessons due for review (next_review <= today, "
                       "status != learned).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "skip",
        "description": "Declare that nothing in the input is lesson-worthy.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}}, "required": ["reason"]}}},
]


def exec_tool(store: MockStore, name: str, args: dict) -> dict:
    try:
        if name == "lesson_search":
            return {"results": store.search(str(args.get("query", "")))}
        if name == "lesson_list":
            return {"results": store.list_all()}
        if name == "lesson_get":
            return store.get(str(args.get("slug", "")))
        if name == "lesson_create":
            return store.create(str(args.get("topic", "")),
                                level=str(args.get("level", "intro")),
                                source=str(args.get("source", "voice")),
                                content_html=str(args.get("content_html", "")),
                                next_review=args.get("next_review"),
                                status=str(args.get("status", "open")))
        if name == "lesson_update":
            return store.update(str(args.get("slug", "")),
                                content_html=args.get("content_html"),
                                next_review=args.get("next_review"),
                                status=args.get("status"),
                                level=args.get("level"),
                                topic=args.get("topic"))
        if name == "lessons_due":
            return {"due": store.due()}
        if name == "skip":
            return {"skipped": str(args.get("reason", ""))}
        return {"error": f"unknown tool {name}"}
    except Exception as e:  # never let a bad call kill the loop
        return {"error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------- agent surface

AGENT_SYS = """You are the manager of Tony's education ledger — a personal
lesson store (one lesson per topic). Today's date is {today}.

Rules:
- Capture durable knowledge only: definitions, comparisons,
  how-things-work, concepts, troubleshooting knowledge. Never file
  commands, reminders, scheduling, chit-chat, private/personal matters,
  or answers valid only for one moment in time.
- Topics are short English titles (3-8 words). The lesson slug derives
  from the topic — a re-asked topic maps to the SAME slug, so re-asks
  UPDATE the existing lesson instead of forking. Always lesson_search
  first.
- Multi-part education lives as a topic family: "ada-nest-map" is the
  hub lesson; each part gets its own "ada-nest-<topic>" lesson. Never
  overwrite a hub with a sub-topic.
- Lesson content is a standalone HTML fragment using only h3, h4, p, ul,
  ol, li, code, pre, strong, em, a (NO h1/h2/html/head/body). Start with
  a direct answer in 1-2 sentences, ~150-400 words, strip personal
  specifics (names, addresses, schedules, devices).
- New lessons get status=open and next_review=today+7 unless told
  otherwise.
- Use the tools. When finished, reply with ONE line summarising every
  action you took (slug + what changed) — or for recall questions, the
  slug of the lesson that answers it, or "none".{existing}"""

EXISTING_TOPICS_BLOCK = """

The ledger already has lessons on these topics — reuse an EXISTING
topic name whenever the question covers it (a re-asked topic updates
its lesson, never creates a second one); invent a new topic only for
genuinely new knowledge:
{topics}"""


REQUIRED_ARGS = {t["function"]["name"]:
                 set(t["function"]["parameters"].get("required", []))
                 for t in TOOLS}

JSON_RETRY_INSTR = (
    "That reply was not a valid tool call. Emit exactly ONE JSON object "
    "{\"name\": \"<tool>\", \"arguments\": {...}} — or, if you are "
    "finished, the one-line summary.")


class AgentLane:
    """OpenClaw-shaped tool-calling loop over an OpenAI-compat endpoint.

    Turn-2 structured-output hardening (card edu-agent-lane-lift-turn2):
    - parallel_tool_calls disabled — serial calls parse cleaner on small
      models;
    - malformed `arguments` JSON is repaired (balanced-brace extract,
      trailing-comma strip, literal_eval) — counted as arg_repairs;
    - calls still unparseable or missing schema-required params are NOT
      executed — an error is fed back as the tool result so the model
      re-emits (stricter schema retry) — counted as arg_errors;
    - a reply that looks like a text-blob call but fails fallback parsing
      escalates once to response_format=json_object where the backend
      supports it (auto-disabled lane-wide on a 4xx complaint) —
      counted as json_retries.
    """

    def __init__(self, name, base, key, model, timeout, retries=2,
                 json_mode=True):
        self.name, self.base, self.key = name, base.rstrip("/"), key
        self.model, self.timeout, self.retries = model, timeout, retries
        self.json_mode_ok = json_mode

    def _chat(self, messages, tools, response_format=None):
        body = {"model": self.model, "messages": messages,
                "tools": tools, "temperature": 0.2,
                "parallel_tool_calls": False}
        if response_format:
            body["response_format"] = response_format
        err = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(
                    self.base + "/chat/completions",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization":
                             f"Bearer {self.key or 'none'}"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    d = json.loads(r.read())
                ch = (d.get("choices") or [{}])[0]
                return (ch.get("message") or {}, d.get("usage") or {},
                        d.get("model"), None)
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read()[:400].decode("utf-8", "replace")
                except Exception:
                    pass
                err = f"HTTP {e.code}"
                if (response_format and e.code in (400, 404, 422)
                        and re.search(r"response_format|json_object|"
                                      r"format", detail, re.I)):
                    # backend rejects forced JSON — drop it lane-wide
                    self.json_mode_ok = False
                    body.pop("response_format", None)
                    response_format = None
                    continue
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            time.sleep(5 * (attempt + 1))
        return {}, {}, None, err

    @staticmethod
    def _outer_braces(s):
        """First balanced {...} substring (quote/escape-aware) or None."""
        start = s.find("{")
        if start < 0:
            return None
        depth, quote, esc = 0, None, False
        for i in range(start, len(s)):
            c = s[i]
            if esc:
                esc = False
            elif c == "\\" and quote:
                esc = True
            elif quote:
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
        return None

    def _parse_args(self, raw):
        """-> (args_dict, 'ok'|'repaired'|'bad')"""
        if isinstance(raw, dict):
            return raw, "ok"
        if raw is None or raw == "":
            return {}, "ok"
        s = str(raw)
        try:
            v = json.loads(s)
            return (v if isinstance(v, dict) else {}), "ok"
        except json.JSONDecodeError:
            pass
        frag = self._outer_braces(s)
        if frag:
            for cand in (frag, re.sub(r",\s*([}\]])", r"\1", frag)):
                try:
                    v = json.loads(cand)
                    if isinstance(v, dict):
                        return v, "repaired"
                except json.JSONDecodeError:
                    pass
            try:
                v = ast.literal_eval(frag)
                if isinstance(v, dict):
                    return v, "repaired"
            except (ValueError, SyntaxError):
                pass
        return {}, "bad"

    @staticmethod
    def _looks_like_call(content):
        """Reply text that tried to be a tool call (brace blob naming a
        tool or the name/arguments keys) but failed fallback parsing."""
        if not content or "{" not in content:
            return False
        return bool(re.search(
            r'"(name|arguments|parameters|tool)"|'
            + "|".join(REQUIRED_ARGS), content))

    def _fallback_call(self, content: str):
        """Prompted-JSON rescue: a tool call emitted as plain text
        {"name": ..., "arguments"|"parameters": {...}} — mirrors the
        resilience an OpenClaw surface gets from hermes-style models."""
        m = re.search(r"\{.*\}", content or "", flags=re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict) or "name" not in obj:
            return None
        args = obj.get("arguments") or obj.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {"name": obj["name"], "arguments": args}

    def run_task(self, task_user_msg, store, store_aware=False):
        existing = ""
        if store_aware:
            topics = ", ".join(sorted(
                r["topic"] for r in store.list_all()))
            existing = EXISTING_TOPICS_BLOCK.format(
                topics=topics or "(none)")
        messages = [{"role": "system",
                     "content": AGENT_SYS.format(
                         today=date.today(), existing=existing)},
                    {"role": "user", "content": task_user_msg}]
        calls, tok_in, tok_out, llm_calls = [], 0, 0, 0
        models_seen, final_text, err = set(), "", None
        arg_repairs = arg_errors = json_retries = 0
        json_retried = False
        t0 = time.time()
        for _ in range(MAX_ROUNDS):
            msg, usage, model_seen, err = self._chat(messages, TOOLS)
            if err:
                break
            llm_calls += 1
            if model_seen:
                models_seen.add(model_seen)
            tok_in += int(usage.get("prompt_tokens") or 0)
            tok_out += int(usage.get("completion_tokens") or 0)
            tcalls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            if not tcalls:
                fb = self._fallback_call(content)
                if fb:
                    tcalls = [{"id": "fb", "type": "function",
                               "function": fb}]
            if (not tcalls and not json_retried and self.json_mode_ok
                    and self._looks_like_call(content)):
                # malformed text-blob call -> one forced-JSON retry
                json_retried = True
                json_retries += 1
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user",
                                 "content": JSON_RETRY_INSTR})
                msg2, u2, ms2, err2 = self._chat(
                    messages, TOOLS,
                    response_format={"type": "json_object"})
                tok_in += int(u2.get("prompt_tokens") or 0)
                tok_out += int(u2.get("completion_tokens") or 0)
                if not err2:
                    llm_calls += 1
                    if ms2:
                        models_seen.add(ms2)
                    content = msg2.get("content") or ""
                    tcalls = msg2.get("tool_calls") or []
                    if not tcalls:
                        fb = self._fallback_call(content)
                        if fb:
                            tcalls = [{"id": "fb2", "type": "function",
                                       "function": fb}]
            if not tcalls:
                final_text = content
                break
            messages.append({"role": "assistant", "content": content or None,
                             "tool_calls": tcalls})
            for tc in tcalls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args, arg_status = self._parse_args(fn.get("arguments"))
                missing = REQUIRED_ARGS.get(name, set()) - set(args)
                if arg_status == "bad" or (name in REQUIRED_ARGS
                                           and missing):
                    why = ("invalid JSON arguments" if arg_status == "bad"
                           else f"missing required: {sorted(missing)}")
                    arg_errors += 1
                    result = {"error": (
                        f"tool call rejected — {why}; re-emit {name} "
                        "with a single valid JSON object matching the "
                        "tool schema")}
                    calls.append({"tool": name, "args": args,
                                  "result": result, "arg_error": why})
                else:
                    if arg_status == "repaired":
                        arg_repairs += 1
                    result = exec_tool(store, name, args)
                    calls.append({"tool": name, "args": args,
                                  "result": result})
                messages.append({"role": "tool",
                                 "tool_call_id": tc.get("id", "x"),
                                 "name": name, "content": json.dumps(result)})
        else:
            err = f"exceeded {MAX_ROUNDS} tool rounds"
        lat = time.time() - t0
        return {"final_text": final_text, "calls": calls,
                "llm_calls": llm_calls, "tokens_in": tok_in,
                "tokens_out": tok_out, "models": sorted(models_seen),
                "latency": lat, "err": err,
                "arg_repairs": arg_repairs, "arg_errors": arg_errors,
                "json_retries": json_retries,
                "json_mode": self.json_mode_ok,
                "completed": err is None and bool(final_text)}


# -------------------------------------------------------------- current lane

TRANSCRIPT_INSTR = """Process this Ada voice transcript for the education
ledger. For each user question worth a durable lesson: search first, then
draft the fragment and lesson_update the existing slug if the topic is
already covered, else lesson_create. Call skip if nothing qualifies.

TRANSCRIPT:
%s"""


def run_current(task, store, key, stats, topics=None):
    """The scripted pipeline (transcript) or its documented
    scripted-equivalent (ops/recall). Returns task record. `topics`
    injects the store's existing topic list into classify — the same
    store-awareness the production miner gets from the /lesson topics
    door (turn-3 A/B)."""
    t0 = time.time()
    rec = {"calls": [], "llm_calls": 0, "tokens_in": 0, "tokens_out": 0,
           "models": [CURRENT_MODEL], "err": None, "final_text": "",
           "completed": True}
    if task["type"] == "transcript":
        with tempfile.NamedTemporaryFile(
                "w", suffix=".md", prefix="2026-10-22-bench",
                delete=False, encoding="utf-8") as f:
            f.write(task["transcript"])
            tmp = Path(f.name)
        try:
            _sid, _d, turns = lm.parse_transcript(tmp)
            cands = lm.find_candidates(turns)
            rec["candidates"] = len(cands)
            kept = (lm.classify(cands, CURRENT_MODEL, key, topics=topics)
                    if cands else [])
            rec["llm_calls"] += 1 if cands else 0
            for c in kept:
                html = lm.draft_lesson(task["transcript"], c,
                                       CURRENT_MODEL, key)
                rec["llm_calls"] += 1
                if not html:
                    continue
                action, r = store.upsert_add(c["topic"], c["level"],
                                             "voice", html)
                rec["calls"].append(
                    {"tool": f"upsert_{action}", "args": {"topic": c["topic"]},
                     "result": {"slug": r["slug"]}})
        finally:
            tmp.unlink(missing_ok=True)
    elif task["type"] == "ops":
        g = task["ops_golden"]
        if g["kind"] == "set_field":
            slug = slug_of(g["topic"])
            val = resolve_day(g["value"]) if g["field"] == "next_review" \
                else g["value"]
            res = store.update(slug, **{g["field"]: val})
            rec["calls"].append({"tool": "ops_equivalent",
                                 "args": g, "result": res})
        elif g["kind"] == "due_list":
            due = store.due()
            rec["calls"].append({"tool": "due_list", "args": {},
                                 "result": {"due": due}})
            rec["final_text"] = "Due: " + ", ".join(
                f"{r['topic']} ({r['slug']}, due {r['next_review']})"
                for r in due)
    elif task["type"] == "recall":
        stop = {"what", "whats", "where", "when", "which", "that", "this",
                "have", "does", "about", "lesson", "post", "tony", "asks",
                "with", "cover", "covers", "there", "their", "them",
                "again", "explainer", "thing"}
        words = [w for w in re.findall(r"[a-z]{4,}", norm(task["query"]))
                 if w not in stop]
        best, best_hits = None, 0
        for slug, r in store.recs.items():
            hay = norm(r["topic"] + " " + r["title"] + " " + r["content"])
            hits = sum(1 for w in words if w in hay)
            if hits > best_hits:
                best, best_hits = slug, hits
        if best and best_hits >= 2:
            rec["final_text"] = f"{best} — {store.recs[best]['title']}"
            rec["calls"].append({"tool": "search", "args": {"q": words},
                                 "result": {"slug": best}})
        else:
            rec["final_text"] = "none"
    rec["latency"] = time.time() - t0
    # estimate tokens (gemini_rest doesn't surface usage)
    rec["tokens_in"] = sum(len(str(c.get("args", ""))) // 4
                           for c in rec["calls"]) + len(
                               task.get("transcript", "")) // 4
    rec["tokens_out"] = sum(len(json.dumps(c.get("result", ""))) // 4
                            for c in rec["calls"])
    stats_drafts(rec, task, store)
    return rec


def stats_drafts(rec, task, store):
    """Annotate rec with filings — one entry per distinct slug touched
    (create+update on the same slug counts once; `created` = the slug
    was not in the seed set)."""
    seen, filings = set(), []
    for c in rec["calls"]:
        if c["tool"].startswith("upsert_") or c["tool"] in (
                "lesson_create", "lesson_update"):
            slug = (c["result"].get("created") or c["result"].get("updated")
                    or c["result"]).get("slug")
            if not slug or slug in seen or slug not in store.recs:
                continue
            seen.add(slug)
            r = store.recs[slug]
            filings.append({"slug": slug, "topic": r["topic"],
                            "created": slug not in store.seed_slugs,
                            "content": r["content"],
                            "next_review": r["next_review"],
                            "status": r["status"]})
    rec["filings"] = filings


def run_agent_task(lane, task, store, store_aware=False):
    if task["type"] == "transcript":
        msg = TRANSCRIPT_INSTR % task["transcript"]
    elif task["type"] == "ops":
        msg = ("Education-ledger operation. Do exactly what is asked, "
               "using the tools, then reply with one summary line.\n\n"
               + task["instruction"])
    else:  # recall
        msg = ("Tony asks: %s\n\nPoint to the lesson that answers this — "
               "use the tools to find it and reply with its slug, or "
               "reply \"none\" if no lesson covers it." % task["query"])
    rec = lane.run_task(msg, store, store_aware=store_aware)
    stats_drafts(rec, task, store)
    return rec


# ------------------------------------------------------------------ scoring

def score_task(task, store, rec):
    """-> dict of per-task scores + notes."""
    s = {"id": task["id"], "type": task["type"],
         "completed": bool(rec.get("completed")), "err": rec.get("err")}
    filings = rec.get("filings", [])
    if task["type"] == "transcript":
        golden = task["keep"]
        neutral = {slug_of(t) for t in task.get("neutral_seed_topics", [])}
        matched, fp = [], []
        for g in golden:
            hit = next((f for f in filings
                        if topic_matches(f["topic"], g["match"])), None)
            if hit:
                a_ok = action_ok(g, hit, store)
                matched.append({"golden": g, "filing": hit, "action_ok": a_ok})
        for f in filings:
            if f["slug"] in neutral:
                continue  # convention-correct touches (e.g. hub refresh)
            if not any(topic_matches(f["topic"], g["match"]) for g in golden):
                fp.append(f)
        s["tp"], s["fp"], s["fn"] = len(matched), len(fp), len(golden) - len(matched)
        s["dedupe_correct"] = sum(1 for m in matched if m["action_ok"])
        s["dedupe_total"] = len(golden)
        s["notes"] = [f"filed {f['topic']!r} "
                      f"({'new' if f['created'] else 'upd'})" for f in filings]
        if rec.get("candidates") is not None:
            s["notes"].append(f"filter={rec['candidates']}cand")
    elif task["type"] == "ops":
        passed = []
        for chk in task.get("checks", []):
            slug = slug_of(chk["topic"])
            r = store.recs.get(slug)
            got = r.get(chk["field"]) if r else None
            want = resolve_day(chk["expect"])
            passed.append(got == want)
        txt = (rec.get("final_text") or "").lower()
        for t in task.get("expect_topics_in_answer", []):
            passed.append(norm(t) in txt or slug_of(t) in txt)
        for t in task.get("forbid_topics_in_answer", []):
            passed.append(norm(t) not in txt and slug_of(t) not in txt)
        s["ops_pass"] = sum(passed)
        s["ops_total"] = len(passed)
        s["notes"] = [f"checks {s['ops_pass']}/{s['ops_total']}"]
    else:  # recall
        exp = task["expect_topic"]
        txt = rec.get("final_text") or ""
        get_slugs = {c["args"].get("slug") for c in rec.get("calls", [])
                     if c["tool"] == "lesson_get"}
        any_slug = {c["result"].get("slug") for c in rec.get("calls", [])
                    if c["tool"] == "search"} | get_slugs
        slug_refs = set(re.findall(r"lesson-[0-9a-f]{12}", txt)) | any_slug
        if exp is None:
            s["recall_ok"] = not slug_refs or slug_refs == {None}
        else:
            s["recall_ok"] = (slug_of(exp) in slug_refs
                              or slug_of(exp) in get_slugs)
        s["notes"] = [f"answer={txt[:80]!r}"]
    return s


def action_ok(g, filing, store):
    a = g["action"]
    if a == "create":
        return filing["created"]
    if a == "update":
        return (not filing["created"]
                and filing["slug"] == slug_of(g["seed_topic"]))
    if a == "hub_create":
        return (filing["created"]
                and norm(g["family"]) in norm(filing["topic"]))
    return False


JUDGE_PROMPT = """Grade this lesson draft filed into a personal education
ledger. Source question the user asked: "%s"

Score each axis 0-5:
- direct_answer: opens with a direct answer in 1-2 sentences
- accuracy: faithful to the source exchange, no invented facts
- structure: valid fragment (h3/h4/p/ul/ol/li/code/pre/strong/em/a only,
  no h1/h2/html/head/body, no markdown fences)
- hygiene: no personal specifics (names, addresses, schedules, devices)
- length: ~150-400 words, appropriately concise

DRAFT:
%s

Reply with ONE JSON object only:
{"direct_answer":N,"accuracy":N,"structure":N,"hygiene":N,"length":N}
"""


def judge_drafts(drafts, key):
    """drafts: [{lane, task, slug, topic, html, q}] -> per-draft scores."""
    for d in drafts:
        if not d["html"] or len(d["html"]) < 30:
            d["judge"] = None
            continue
        try:
            r = gemini_rest.generate_json(
                JUDGE_PROMPT % (d["q"][:300], d["html"][:6000]),
                JUDGE_MODEL, key=key, timeout=120)
        except (ValueError, json.JSONDecodeError):
            r = None
        d["judge"] = r
        time.sleep(0.3)


def rescore(path, corpus):
    """Recompute transcript capture/dedupe metrics in a finished result
    JSON after a corpus or scorer change (e.g. neutral_seed_topics).
    Ops/recall/loop numbers replay unchanged — they come from recorded
    store mutations that aren't re-derivable from the file."""
    result = json.loads(Path(path).read_text())
    by_id = {t["id"]: t for t in corpus["tasks"]}
    for lane, recs in result["tasks"].items():
        tp = fp = fn = dc = dt = 0
        for r in recs:
            task = by_id[r["task"]]
            if task["type"] != "transcript":
                continue
            sc = score_task(task, None,
                            {"filings": r.get("filings", []),
                             "completed": r.get("completed")})
            tp += sc["tp"]; fp += sc["fp"]; fn += sc["fn"]
            dc += sc["dedupe_correct"]; dt += sc["dedupe_total"]
        prec = tp / max(tp + fp, 1)
        recl = tp / max(tp + fn, 1)
        f1 = 2 * prec * recl / max(prec + recl, 1e-9)
        agg = result["scores"][lane][-1]
        agg["capture"] = {"tp": tp, "fp": fp, "fn": fn,
                          "precision": round(prec, 3),
                          "recall": round(recl, 3), "f1": round(f1, 3)}
        agg["dedupe"] = {"correct": dc, "total": dt,
                         "score": round(dc / max(dt, 1), 3)}
    Path(path).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    write_md(str(path)[:-5] + ".md", result)
    print(f"rescored {path}")


def aggregate(lane_name, task_scores, task_recs):
    lat = [r["latency"] for r in task_recs if r.get("latency")]
    tok_in = sum(r.get("tokens_in", 0) for r in task_recs)
    tok_out = sum(r.get("tokens_out", 0) for r in task_recs)
    tp = sum(s.get("tp", 0) for s in task_scores)
    fp = sum(s.get("fp", 0) for s in task_scores)
    fn = sum(s.get("fn", 0) for s in task_scores)
    prec = tp / max(tp + fp, 1)
    recl = tp / max(tp + fn, 1)
    f1 = 2 * prec * recl / max(prec + recl, 1e-9)
    dc = sum(s.get("dedupe_correct", 0) for s in task_scores)
    dt = sum(s.get("dedupe_total", 0) for s in task_scores)
    op = sum(s.get("ops_pass", 0) for s in task_scores)
    ot = sum(s.get("ops_total", 0) for s in task_scores)
    recc = [s for s in task_scores if s["type"] == "recall"]
    creates = [f for r in task_recs for f in r.get("filings", [])
               if f["created"]]
    nr_ok = sum(1 for f in creates
                if f["next_review"] ==
                (date.today() + timedelta(days=7)).isoformat())
    return {
        "lane": lane_name,
        "capture": {"tp": tp, "fp": fp, "fn": fn,
                    "precision": round(prec, 3), "recall": round(recl, 3),
                    "f1": round(f1, 3)},
        "dedupe": {"correct": dc, "total": dt,
                   "score": round(dc / max(dt, 1), 3)},
        "sched_ops": {"pass": op, "total": ot,
                      "score": round(op / max(ot, 1), 3),
                      "next_review_default_ok": nr_ok,
                      "creates": len(creates)},
        "recall": {"correct": sum(1 for s in recc if s.get("recall_ok")),
                   "total": len(recc)},
        "loop": {"completed": sum(1 for s in task_scores if s["completed"]),
                 "total": len(task_scores),
                 "lat_mean": round(statistics.mean(lat), 1) if lat else None,
                 "lat_p50": round(statistics.median(lat), 1) if lat else None,
                 "tokens_in": tok_in, "tokens_out": tok_out,
                 "arg_repairs": sum(r.get("arg_repairs", 0)
                                    for r in task_recs),
                 "arg_errors": sum(r.get("arg_errors", 0)
                                   for r in task_recs),
                 "json_retries": sum(r.get("json_retries", 0)
                                     for r in task_recs),
                 "json_mode": (task_recs[-1].get("json_mode")
                               if task_recs else None),
                 "cost_usd": 0.0},
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lanes", nargs="+",
                    default=["current", "clawbot", "hermes"],
                    choices=["current", "clawbot", "hermes"])
    ap.add_argument("--ollama-model", default=HERMES_MODEL,
                    help="model for the local-ollama agent lane "
                         "(default hermes3:8b; lane is renamed "
                         "local-<model> when a different model is given)")
    ap.add_argument("--ollama-timeout", type=int, default=300,
                    help="per-call timeout (s) for the local-ollama lane "
                         "(default 300 — reasoning models on a shared "
                         "RAM-offloaded GPU need more than the old 150)")
    ap.add_argument("--tasks", nargs="+", default=None,
                    help="task ids to run (default: all)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--agent-topics", action="store_true",
                    help="inject the store's existing topic list into "
                         "the agent system prompt (turn-3 store-"
                         "awareness A/B — off = baseline prompt)")
    ap.add_argument("--rescore", default=None, metavar="RESULT.json",
                    help="recompute transcript metrics in a finished "
                         "result file and rewrite it + the .md")
    ap.add_argument("--out", default=None,
                    help="output prefix (default reports/bench-edu-manage-<date>)")
    args = ap.parse_args()

    corpus = json.loads(CORPUS.read_text())
    if args.rescore:
        rescore(args.rescore, corpus)
        return
    tasks = corpus["tasks"]
    if args.tasks:
        tasks = [t for t in tasks if t["id"] in args.tasks]
    if args.limit:
        tasks = tasks[: args.limit]

    gkey = load_secret(("GEMINI_API_KEY_FREE", "GEMINI_API_KEY",
                        "GOOGLE_API_KEY"))
    orkey = load_secret(("OPENROUTER_API_KEY",),
                        env_files=("~/.config/secrets/openrouter.env",))
    ollama = os.environ.get("OLLAMA_URL",
                            "http://100.75.102.88:11434").rstrip("/")

    lanes = {}
    if "current" in args.lanes:
        lanes["current"] = {"kind": "scripted", "model": CURRENT_MODEL}
    if "clawbot" in args.lanes:
        lanes["clawbot"] = AgentLane("clawbot", OR_BASE, orkey, OR_MODEL, 90)
    if "hermes" in args.lanes:
        lname = ("hermes" if args.ollama_model == HERMES_MODEL
                 else "local-" + re.sub(r"[^a-z0-9]+", "-",
                                        args.ollama_model.lower()))
        lanes[lname] = AgentLane(lname, ollama + "/v1", "ollama",
                                 args.ollama_model, args.ollama_timeout)

    out_prefix = args.out or str(
        REPO / "reports" / f"bench-edu-manage-{date.today().isoformat()}")
    all_scores, all_recs, drafts = {}, {}, []
    for rep in range(args.reps):
        for name, lane in lanes.items():
            print(f"[{name}] rep {rep + 1}")
            t_scores, t_recs = [], []
            for task in tasks:
                store = MockStore(corpus["seeds"][task["seed"]])
                if name == "current":
                    topics = ([r["topic"] for r in store.list_all()]
                              if args.agent_topics else None)
                    rec = run_current(task, store, gkey, None,
                                      topics=topics)
                else:
                    rec = run_agent_task(lane, task, store,
                                         store_aware=args.agent_topics)
                stats_drafts(rec, task, store)
                sc = score_task(task, store, rec)
                t_scores.append(sc)
                t_recs.append(rec)
                for f in rec.get("filings", []):
                    drafts.append({"lane": name, "task": task["id"],
                                   "slug": f["slug"], "topic": f["topic"],
                                   "html": f["content"],
                                   "q": next(
                                       (k["match"][0] for k in task.get("keep", [])
                                        if topic_matches(f["topic"], k["match"])),
                                       f["topic"])})
                print(f"  {task['id']:28s} ok={sc['completed']} "
                      f"{sc.get('notes', [])} lat={rec['latency']:.0f}s"
                      + (f" err={rec['err']}" if rec.get("err") else ""))
            agg = aggregate(name, t_scores, t_recs)
            all_scores.setdefault(name, []).append(agg)
            all_recs.setdefault(name, []).extend(
                {"task": s["id"], **{k: v for k, v in r.items()
                                     if k != "calls"},
                 "tool_calls": len(r["calls"])}
                for s, r in zip(t_scores, t_recs))
            print(f"  -> F1={agg['capture']['f1']} dedupe={agg['dedupe']['score']} "
                  f"ops={agg['sched_ops']['score']} "
                  f"recall={agg['recall']['correct']}/{agg['recall']['total']} "
                  f"p50={agg['loop']['lat_p50']}s")

    judged = {}
    if not args.no_judge and gkey:
        print(f"[judge] {JUDGE_MODEL} grading {len(drafts)} drafts")
        judge_drafts(drafts, key=gkey)
        for lane in all_scores:
            ds = [d["judge"] for d in drafts
                  if d["lane"] == lane and d["judge"]]
            if ds:
                axes = ["direct_answer", "accuracy", "structure",
                        "hygiene", "length"]
                judged[lane] = {
                    "n": len(ds),
                    "mean": round(statistics.mean(
                        sum(float(x.get(a, 0)) for a in axes) / 5
                        for x in ds), 2),
                    **{a: round(statistics.mean(
                        float(x.get(a, 0)) for x in ds), 2) for a in axes}}
    for lane, aggs in all_scores.items():
        all_scores[lane][-1]["draft_quality"] = judged.get(lane)

    result = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "date": date.today().isoformat(),
              "config": {"lanes": {k: (v if isinstance(v, dict) else
                                     {"base": v.base, "model": v.model,
                                      "json_mode": v.json_mode_ok})
                                   for k, v in lanes.items()},
                         "judge": None if args.no_judge else JUDGE_MODEL,
                         "agent_topics": bool(args.agent_topics),
                         "corpus": str(CORPUS)},
              "scores": all_scores, "tasks": all_recs,
              "drafts": [{k: v for k, v in d.items() if k != "html"}
                         | {"html_len": len(d["html"])} for d in drafts]}
    jp = out_prefix + ".json"
    Path(jp).parent.mkdir(parents=True, exist_ok=True)
    Path(jp).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(f"wrote {jp}")
    write_md(out_prefix + ".md", result)


def write_md(path, result):
    L = []
    L.append(f"# bench-edu-manage — {result['date']}")
    L.append("")
    L.append("Card: edu-agent-benchmark. Three education-managing lanes on "
             "one fixed corpus (`scripts/bench-edu-corpus.json`) against a "
             "LOCAL mock WP-lesson store — never prod WP.")
    L.append("")
    L.append("| lane | capture F1 | P / R | dedupe | sched/ops | recall | "
             "draft-Q (judge) | completed | p50 lat | tokens in/out |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for lane, aggs in result["scores"].items():
        a = aggs[-1]
        dq = a.get("draft_quality") or {}
        L.append(
            f"| {lane} | {a['capture']['f1']} | "
            f"{a['capture']['precision']} / {a['capture']['recall']} | "
            f"{a['dedupe']['correct']}/{a['dedupe']['total']} | "
            f"{a['sched_ops']['pass']}/{a['sched_ops']['total']} | "
            f"{a['recall']['correct']}/{a['recall']['total']} | "
            f"{dq.get('mean', 'n/a')} (n={dq.get('n', 0)}) | "
            f"{a['loop']['completed']}/{a['loop']['total']} | "
            f"{a['loop']['lat_p50']}s | "
            f"{a['loop']['tokens_in']}/{a['loop']['tokens_out']} |")
    L.append("")
    L.append("## Per-task")
    for lane, recs in result["tasks"].items():
        L.append(f"\n### {lane}")
        for r in recs:
            fl = ", ".join(
                f"{f['topic']}({'new' if f['created'] else 'upd'})"
                for f in r.get("filings", []))
            L.append(
                f"- `{r['task']}` completed={r['completed']} "
                f"calls={r.get('tool_calls', 0)} llm={r.get('llm_calls', 0)} "
                f"lat={r.get('latency', 0):.0f}s"
                + (f" filed: {fl}" if fl else "")
                + (f" ERR={r['err']}" if r.get("err") else ""))
    L.append("")
    L.append("## Method notes")
    L.append("- `current` = real pipeline path (mechanical filter -> "
             "flash-lite classify with the production CLASSIFY_PROMPT -> "
             "draft with DRAFT_PROMPT -> lesson-add upsert semantics "
             "incl. its meta-overwrite quirk). Ops/recall run the "
             "documented scripted-equivalent (deterministic).")
    L.append("- `clawbot` = OpenClaw-shaped tool loop (same system-prompt "
             "duties + store CRUD tools) on `openrouter/free`. The real "
             "gateway on tony-omen is loopback:18789 — unreachable over "
             "tailnet — so the surface is emulated in-process on its "
             "declared provider.")
    for lk, lc in result["config"]["lanes"].items():
        if lk.startswith("local-") or lk == "hermes":
            L.append(f"- `{lk}` = identical loop on omen ollama /v1 "
                     f"{lc.get('model')}.")
    fid = "; ".join(
        f"{lane}: arg_repairs={a['loop'].get('arg_repairs', 0)} "
        f"arg_errors={a['loop'].get('arg_errors', 0)} "
        f"json_retries={a['loop'].get('json_retries', 0)} "
        f"json_mode={'on' if a['loop'].get('json_mode') else 'off'}"
        for lane, a in ((l, aggs[-1]) for l, aggs
                        in result["scores"].items())
        if "arg_repairs" in a["loop"])
    if fid:
        L.append("- Structured-output counters (turn-2 loop change — args "
                 "repair, schema-retry, forced-JSON escalation): " + fid)
    L.append("- Judge = one fixed model (gemini-3.5-flash-lite) for all "
             "lanes; it is also the `current` lane's model — symmetry "
             "caveat applies to draft-quality only.")
    Path(path).write_text("\n".join(L) + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
