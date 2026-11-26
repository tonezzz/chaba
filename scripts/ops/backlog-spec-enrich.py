#!/usr/bin/env python3
"""backlog-spec-enrich — draft specs for thin backlog cards via LiteLLM.

The board's throughput is spec-bound, not runner-bound: most backlog
cards are title-only captures that a dispatch can't turn into a
verifiable done-condition. This job takes the thinnest N per run, asks
the model for either a draft spec or a clarifying ask, and writes the
result back into the card on the served checkout (this runs on the
live-writer host — idc03 — so YAML writes go straight to the tree and
kanban-commit persists them; do NOT run it from a satellite checkout).

Outcomes per card:
  spec  -> spec: field filled + comms 'spec drafted — review before
           queueing' (a human queues when the draft reads right)
  ask   -> a requests: entry with options for Tony's one-word call
  skip  -> comms note (looks obsolete/duplicate/already-done)

Env:
  CARD_DIR            card dir (default live served checkout on idc03)
  ENRICH_LIMIT        cards per run (default 4)
  ENRICH_MIN_SPEC     spec chars below which a card is 'thin' (default 80)
  ENRICH_PROVIDER     litellm (default) | gemini. litellm rides the
                      OpenAI-compatible gateway (scripts/ada/
                      litellm_chat.py -> idc03:4000/v1/chat/completions)
                      so calls get x-litellm attribution, per-key
                      budgets, and the registered model fallback
                      chains; gemini keeps the legacy direct
                      gemini_rest path. A failed/empty litellm reply
                      falls back to gemini_rest when ENRICH_MODEL names
                      a gemini-* route and a direct key resolves.
  ENRICH_MODEL        gateway model_name or Gemini model
                      (default gemini-3.5-flash-lite; e.g.
                      ollama-qwen38b-kkmac for free local kk-mac drafts)
  LITELLM_URL/LITELLM_KEY  gateway creds — the job's env_file
                      litellm-chaba.env supplies the chaba virtual key
  GEMINI_API_KEY      else ~/.config/secrets/mddb-gemini.env /
                    gemini-keys.env (FREE first) — gemini provider +
                    litellm fallback only
Usage:
  backlog-spec-enrich.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ada"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
import yaml  # noqa: E402
import gemini_rest  # noqa: E402
import litellm_chat  # noqa: E402
import card_io  # noqa: E402

CARD_DIR = Path(os.environ.get(
    "CARD_DIR",
    os.path.expanduser("~/CascadeProjects/chaba-tony-dell/"
                       "docs/ssot/kanban/cards")))
MIN_SPEC = int(os.environ.get("ENRICH_MIN_SPEC", "80"))
MODEL = os.environ.get("ENRICH_MODEL", "gemini-3.5-flash-lite")
PROVIDER = os.environ.get("ENRICH_PROVIDER", "litellm").strip().lower()
if PROVIDER not in ("litellm", "gemini"):
    print(f"ENRICH_PROVIDER {PROVIDER!r} unknown — using litellm")
    PROVIDER = "litellm"
MARKER = "backlog-spec-enrich"
SECRET_FILES = [os.path.expanduser("~/.config/secrets/mddb-gemini.env"),
                os.path.expanduser("~/.config/secrets/gemini-keys.env")]
PRIOR = {"high": 0, "medium": 1, "low": 2}

PROMPT = """You are writing a dispatch spec for a kanban card in a personal
infra system (Chaba board). Cards dispatch to agents; a good spec lets a
runner produce a verifiable done-condition without conversation context.

Card:
  id: {cid}
  title: {title}
  note: {note}
  tags: {tags}
  recent comms:
{comms}

Decide ONE:
- "spec"  — you can draft a concrete spec now. Write: goal, host/repo
  (hosts: tony-dell, idc02, idc03, tony-omen, tony-macbook, mn01, con01;
  repos: chaba, ada-voice, sunsynk-card, mddb-fork, gods-eye-view),
  constraints, and a testable done-condition. 3-6 sentences of plain
  text. Only assert facts present in the card/context — never invent
  hostnames, paths, or decisions.
- "ask"   — a materially different direction needs the owner. Write a
  short ask (one paragraph, current-state context) plus 2-4 options with
  a ★ on the recommended one. Options must be ACTIONABLE OUTCOMES the
  owner picks between ("use repo X on host Y", "postpone", "split per
  member") — never meta-requests like "clarify the repo" or "specify
  the host": an option that just re-asks the question is a failed ask
  (observed 2026-10-23: 4 cards got circular answers this way).
- "skip"  — the card looks obsolete, already-done, or a duplicate.
  Give one sentence why.

Reply JSON only: {{"decision":"spec|ask|skip","spec":"...",
"ask":"...","options":["..."],"why":"..."}}"""


def _load_env(path: str) -> dict:
    env = {}
    try:
        for line in open(path):
            m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)", line)
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _gemini_key() -> str | None:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    for f in SECRET_FILES:
        env = _load_env(f)
        for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_FREE", "GOOGLE_API_KEY"):
            if env.get(k):
                return env[k]
    return None


def _load_cards() -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(open(p))
        except Exception:
            continue
        if isinstance(c, dict):
            out.append((p, c))
    return out


def _thin(p: Path, c: dict) -> bool:
    if c.get("column") != "backlog":
        return False
    a = c.get("action") or {}
    if a.get("status") in ("queued", "running"):
        return False
    if len((c.get("spec") or "").strip()) >= MIN_SPEC:
        return False
    for r in c.get("requests") or []:
        if isinstance(r, dict) and r.get("status") == "open":
            return False
    for m in c.get("comms") or []:
        if isinstance(m, dict) and MARKER in (m.get("text") or ""):
            return False  # already processed by this job
    return True


def _rank(item: tuple[Path, dict]) -> tuple:
    p, c = item
    return (PRIOR.get(str(c.get("priority") or "medium"), 1),
            str(c.get("updated") or ""))


def _req_id(ask: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", ask.lower())[:30].strip("-")
    return f"{slug}-{hashlib.md5(ask.encode()).hexdigest()[:6]}"


def _write(p: Path, c: dict) -> None:
    card_io.atomic_write_text(p, yaml.dump(c, allow_unicode=True,
                                           sort_keys=False, width=100))


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _enrich_json(prompt: str, cid: str, key: str | None):
    """One spec-draft call -> dict | None (None = no usable reply).

    litellm provider: OpenAI-compatible /chat/completions on the
    gateway — x-litellm-tags/metadata stamp SpendLogs rows with
    service/job/route/card attribution, per-key budgets apply, and
    the model's registered fallback chain handles upstream failures.
    ENRICH_MODEL is any gateway model_name (gemini-3.5-flash-lite,
    ollama-qwen38b-kkmac, chat-local, ...). A failed/empty litellm
    reply falls back to gemini_rest only when the model names a
    gemini-* route — a local/OR alias has no direct-Google meaning."""
    tags = "service=backlog-spec-enrich,job=backlog-spec-enrich"
    meta = {"route": "spec_draft", "card": cid}
    if PROVIDER == "litellm":
        res = litellm_chat.chat_json(
            prompt, model=MODEL, temperature=0.2, max_tokens=2048,
            timeout=180, label="enrich", tags=tags,
            litellm_metadata=meta)
        if isinstance(res, dict):
            return res
        print(f"  {cid}: litellm {MODEL} -> no usable reply")
        if not MODEL.startswith("gemini"):
            return None
        print(f"  {cid}: falling back to gemini_rest")
    if not key:
        print(f"  {cid}: no GEMINI key — cannot call gemini_rest")
        return None
    return gemini_rest.generate_json(
        prompt, MODEL, key=key, timeout=180, tags=tags,
        litellm_metadata=meta)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int,
                    default=int(os.environ.get("ENRICH_LIMIT", "4")))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = _gemini_key()
    if PROVIDER == "gemini" and not key:
        print("no GEMINI key in env or secrets files"); return 1
    if PROVIDER == "litellm":
        url, lkey = litellm_chat.gateway()
        if not (url and lkey):
            print("warn: LITELLM_URL/LITELLM_KEY unresolved — litellm "
                  "path will no-op; gemini fallback needs a GEMINI key")

    candidates = [x for x in _load_cards() if _thin(*x)]
    candidates.sort(key=_rank)
    batch = candidates[: args.limit]
    print(f"{len(candidates)} thin backlog cards; enriching {len(batch)}")

    done = 0
    for p, c in batch:
        cid = c.get("id") or p.stem
        comms = "\n".join(
            f"  [{m.get('at')}] {m.get('from')}: {m.get('text')}"
            for m in (c.get("comms") or [])[-4:] if isinstance(m, dict))
        prompt = PROMPT.format(
            cid=cid, title=c.get("title") or "", note=c.get("note") or "",
            tags=", ".join(str(t) for t in (c.get("tags") or [])),
            comms=comms or "  (none)")
        try:
            res = _enrich_json(prompt, cid, key)
        except Exception as e:
            print(f"  {cid}: model error {e}"); continue
        if not isinstance(res, dict):
            print(f"  {cid}: no reply"); continue
        dec = str(res.get("decision") or "").lower()
        ts = _now()
        c.setdefault("comms", [])
        if dec == "spec" and (res.get("spec") or "").strip():
            c["spec"] = res["spec"].strip()
            c["comms"].append({
                "at": ts, "from": MARKER,
                "text": f"spec drafted by {MARKER} ({PROVIDER}:{MODEL})"
                        " — review before queueing"})
        elif dec == "ask" and (res.get("ask") or "").strip():
            c.setdefault("requests", []).append({
                "id": _req_id(res["ask"]),
                "ask": res["ask"].strip(),
                "options": res.get("options") or ["proceed", "hold"],
                "status": "open",
                "at": ts, "from": MARKER})
            c["comms"].append({
                "at": ts, "from": MARKER,
                "text": "raised a decision request — spec needs owner "
                        "input"})
        elif dec == "skip":
            c["comms"].append({
                "at": ts, "from": MARKER,
                "text": "skipped — " + (res.get("why")
                                        or "looks obsolete/dup")})
        else:
            print(f"  {cid}: unusable reply {str(res)[:120]}"); continue
        if args.dry_run:
            print(f"  {cid}: {dec} (dry-run)")
            continue
        _write(p, c)
        print(f"  {cid}: {dec} written")
        done += 1
    print(f"done: {done} written, {len(batch) - done} skipped/failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
