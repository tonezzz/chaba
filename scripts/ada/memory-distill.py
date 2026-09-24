#!/usr/bin/env python3
"""Distill ada voice session summaries into candidate memory drafts.

Substrate: ada-pi writes kind=session-summary docs into
ada-ha-recall-summary-<instance> at session close. Most sessions contain
nothing worth keeping, but some carry durable decisions, facts, and
preferences nobody said "remember" about. This job asks Gemini to extract
those candidates and writes them as status=draft docs into the target
bank's collection — they never surface in recall until promoted. Drafts
export to docs/ada-memory/inbox/ on the next
sync-ada-memory-to-mddb.py --export-inbox run for human review, same as
memory-gap-report.py drafts.

Processed session keys are tracked in ~/.cache/ada-memory-distill.json so
re-runs are incremental.

Usage:
  memory-distill.py                     # new sessions, all instances
  memory-distill.py --dry-run           # print candidates, no writes
  memory-distill.py --instance tony --since-days 14
  memory-distill.py --emit              # chaba-event when drafts land
Env: GEMINI_API_KEY (required), ADA_MEMORY_MDDB_URL, ADA_SUMMARY_MODEL
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

STATE = Path.home() / ".cache/ada-memory-distill.json"
MODEL = os.environ.get("ADA_SUMMARY_MODEL", "gemini-3.5-flash-lite")
PER_DOC_CHARS = 3000
MAX_PROMPT_CHARS = 120_000
MAX_DOCS_PER_CHUNK = 30
DEDUP_SCORE = 0.82  # top vector hit above this = already known, skip

EVENT_CMD = [
    "ssh", "tony-dell",
    "python3", "/home/tony/.config/home-assistant/scripts/chaba-event-log.py",
    "add", "-",
]


def load_writable_banks() -> dict[str, dict]:
    data = yaml.safe_load(ada_sync.SSOT.read_text())
    return {n: b for n, b in (data.get("banks") or {}).items()
            if b.get("writable")}


def bank_table(banks: dict[str, dict]) -> str:
    lines = []
    for name, b in banks.items():
        coll = str(b.get("mddb_collection") or "")
        insts = ", ".join(b.get("instances") or [])
        lines.append(
            f'- "{name}" — kinds: {"|".join(b.get("kinds") or ["note"])}; '
            f'collection: {coll}; instances: {insts}')
    return "\n".join(lines)


PROMPT_HEAD = """You are distilling Ada voice-assistant session summaries into durable
memories. Return a JSON array (possibly empty) of candidate memory writes.

Each item: {{"bank","subject","attribute","kind","text","reason"}}
- bank: one of the writable banks below
- subject: short slug-ish topic (e.g. "google-tasks", "mn01-deploy")
- attribute: optional sub-topic; "" if none
- kind: one of the bank's allowed kinds — prefer "fact" for durable facts,
  "preference" for stated preferences, "procedure" for reusable how-tos,
  "note" otherwise
- text: 1-2 self-contained sentences. Name the person ("tony decided X"),
  not "the user". Include verbatim paths/hostnames/dates that matter.
- reason: one short phrase, why this is durable

Writable banks:
{banks}

Instance for this batch: {instance} — for per-instance collections
(personal, note) pick the bank only if it applies to this instance.

Extract ONLY: explicit decisions, corrections, durable facts
(paths/hosts/config/account facts), stated preferences, reusable
procedures, resolved questions with lasting answers, and the concluded
outcome of investigations or incidents (e.g. "the empty list was
expected — tony deliberately cleared it").

Do NOT extract: small talk, weather/time lookups, one-off searches with
no outcome, shopping queries without a purchase decision, anything
transient, anything the user asked not to save. When in doubt, leave it
out — drafts go to a human review queue and noise costs review time.

Return ONLY the JSON array, no markdown fences.
"""


def _gen(prompt: str) -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not set — cannot distill")
        return None
    import time
    import requests
    for attempt in range(4):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{MODEL}:generateContent",
                headers={"x-goog-api-key": key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=120,
            )
            if r.status_code == 429 or r.status_code >= 500:
                wait = 20 * (attempt + 1)
                print(f"  gemini {r.status_code} — retrying in {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            parts = (r.json().get("candidates") or [{}])[0].get(
                "content", {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            return text or None
        except requests.RequestException as exc:
            wait = 20 * (attempt + 1)
            print(f"  gemini call failed ({exc}) — retrying in {wait}s")
            time.sleep(wait)
    return None


def parse_candidates(raw: str) -> list[dict]:
    """Tolerant JSON-array parse: strip fences, find the array."""
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except ValueError:
        return []
    return [i for i in items if isinstance(i, dict) and i.get("text")]


def extract_candidates(sessions: list[dict], banks: dict[str, dict],
                       instance: str) -> list[dict]:
    """sessions = [{key, date, text}] — one Gemini pass per chunk."""
    parts = []
    for s in sessions:
        parts.append(f"### session {s['key']} ({s['date']})\n"
                     f"{s['text'][:PER_DOC_CHARS]}")
    prompt = (PROMPT_HEAD.format(banks=bank_table(banks), instance=instance)
              + "\n\n" + "\n\n".join(parts))
    raw = _gen(prompt)
    return parse_candidates(raw) if raw else []


def chunk_sessions(sessions: list[dict]) -> list[list[dict]]:
    chunks, cur, budget = [], [], MAX_PROMPT_CHARS
    for s in sessions:
        size = min(len(s["text"]), PER_DOC_CHARS) + 120
        if cur and (len(cur) >= MAX_DOCS_PER_CHUNK or budget - size < 0):
            chunks.append(cur)
            cur, budget = [], MAX_PROMPT_CHARS
        cur.append(s)
        budget -= size
    if cur:
        chunks.append(cur)
    return chunks


def valid_candidate(c: dict, banks: dict[str, dict],
                    instance: str) -> tuple[dict, str] | None:
    """Apply bank policy. Returns (normalized candidate, collection) or None."""
    bank = str(c.get("bank") or "")
    spec = banks.get(bank)
    if not spec:
        return None
    if instance not in (spec.get("instances") or [instance]):
        return None
    kinds = spec.get("kinds") or ["note"]
    kind = str(c.get("kind") or "note")
    if kind not in kinds:
        kind = "note" if "note" in kinds else kinds[0]
    coll = str(spec.get("mddb_collection") or "").replace(
        "{instance}", instance)
    if not coll:
        return None
    c = dict(c)
    c["bank"], c["kind"] = bank, kind
    c["subject"] = re.sub(r"[^a-z0-9-]+", "-",
                          str(c.get("subject") or "misc").lower()).strip("-") \
        or "misc"
    c["attribute"] = str(c.get("attribute") or "").strip()
    c["text"] = str(c["text"]).strip()
    return c, coll


def slug(text: str, max_words: int = 6) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:max_words]) or "item"


def subject_exists(mddb: "ada_sync.Mddb", coll: str, subject: str,
                   attribute: str) -> bool:
    filt = {"subject": [subject]}
    if attribute:
        filt["attribute"] = [attribute]
    docs = mddb._post("/search", {"collection": coll, "filterMeta": filt,
                                  "limit": 5})
    return bool(docs)


def semantically_known(mddb: "ada_sync.Mddb", coll: str, text: str) -> float:
    """Top vector score for this text in the collection; 0 on failure."""
    r = mddb._post("/vector-search", {
        "collection": coll, "query": text, "topK": 1,
        "threshold": 0.0, "includeContent": False})
    try:
        return float((r.get("results") or [{}])[0].get("score") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def write_draft(mddb: "ada_sync.Mddb", coll: str, c: dict,
                session_keys: list[str]) -> str:
    today = date.today().isoformat()
    key = f"distill/{today}-{slug(c['text'])}"
    body = (f"{c['text']}\n\n---\n_distilled from {len(session_keys)} "
            f"session(s); reason: {c.get('reason') or '—'}_\n")
    meta = {
        "bank": [c["bank"]],
        "kind": [c["kind"]],
        "status": ["draft"],
        "source": ["extract"],
        "written_by": ["memory-distill"],
        "subject": [c["subject"]],
        "attribute": [c["attribute"]] if c["attribute"] else [],
        "session_keys": session_keys,
        "valid_from": [today],
        "last_verified": [today],
    }
    mddb.add(coll, key, body, meta)
    return key


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1) + "\n")


def emit_event(title: str, body: str) -> None:
    payload = json.dumps({
        "title": title, "category": "ada-memory",
        "source": "memory-distill", "severity": "info",
        "body": body, "requires_response": True, "confidence": 0.8,
    })
    try:
        r = subprocess_run(EVENT_CMD, payload)
        print(f"event: {'ok' if r == 0 else 'failed'}")
    except Exception as exc:
        print(f"event emit failed: {exc}")


def subprocess_run(cmd: list[str], payload: str) -> int:
    import subprocess
    r = subprocess.run(cmd, input=payload, capture_output=True,
                       text=True, timeout=30)
    if r.returncode != 0:
        print(f"  {r.stderr.strip()[:200]}")
    return r.returncode


def mval(doc: dict, field: str) -> str:
    v = (doc.get("meta") or {}).get(field) or [""]
    return str(v[0] if isinstance(v, list) else v)


def distill_instance(mddb: "ada_sync.Mddb", instance: str,
                     banks: dict[str, dict], args, state: dict) -> int:
    coll = f"ada-ha-recall-summary-{instance}"
    docs = mddb.list_docs(coll)
    seen = set(state.get(instance, []))
    sessions = []
    for d in docs:
        if mval(d, "kind") != "session-summary":
            continue
        if d.get("key") in seen:
            continue
        if args.since_days is not None:
            try:
                age = (date.today()
                       - date.fromisoformat(mval(d, "date"))).days
            except ValueError:
                age = 999
            if age > args.since_days:
                continue
        sessions.append({"key": d.get("key") or "",
                         "date": mval(d, "date"),
                         "text": d.get("contentMd") or ""})
    sessions = sessions[-args.max_sessions:] if args.max_sessions else sessions
    print(f"{coll}: {len(sessions)} new session summary doc(s)")
    if not sessions:
        return 0

    created = dup = invalid = failed = 0
    for chunk in chunk_sessions(sessions):
        cands = extract_candidates(chunk, banks, instance)
        if not cands:
            print(f"  chunk of {len(chunk)}: no candidates")
            continue
        skeys = sorted(s["key"] for s in chunk)
        for c in cands:
            ok = valid_candidate(c, banks, instance)
            if not ok:
                invalid += 1
                print(f"  - rejected (bad bank/instance): "
                      f"{c.get('bank')}/{c.get('subject')} "
                      f"{str(c.get('text'))[:60]!r}")
                continue
            c, target = ok
            if subject_exists(mddb, target, c["subject"], c["attribute"]):
                dup += 1
                print(f"  = dup subject {c['bank']}/{c['subject']}")
                continue
            score = semantically_known(mddb, target, c["text"])
            if score > DEDUP_SCORE:
                dup += 1
                print(f"  = dup semantic {c['bank']}/{c['subject']} "
                      f"(score {score:.2f})")
                continue
            tag = "(dry) " if args.dry_run else ""
            print(f"  + {tag}{c['bank']}/{c['subject']}"
                  f"{'/' + c['attribute'] if c['attribute'] else ''} "
                  f"[{c['kind']}] {c['text'][:80]!r}")
            if not args.dry_run:
                try:
                    write_draft(mddb, target, c, skeys)
                    created += 1
                except Exception as exc:
                    failed += 1
                    print(f"    ! write failed: {exc}")
    if not args.dry_run:
        state.setdefault(instance, []).extend(s["key"] for s in sessions)
    print(f"  {created} draft(s), {dup} dup, {invalid} rejected, "
          f"{failed} failed")
    return created


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--instance", action="append",
                    help="limit to instance(s); default = all writable-bank "
                         "instances")
    ap.add_argument("--since-days", type=int, default=None,
                    help="only sessions newer than N days")
    ap.add_argument("--max-sessions", type=int, default=0)
    ap.add_argument("--emit", action="store_true",
                    help="post a chaba-event when drafts are written")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    banks = load_writable_banks()
    all_instances = sorted({i for b in banks.values()
                            for i in (b.get("instances") or [])})
    instances = args.instance or all_instances or ["tony"]

    state = load_state()
    mddb = ada_sync.Mddb(args.mddb, timeout=120)
    total = 0
    for inst in instances:
        total += distill_instance(mddb, inst, banks, args, state)
    if not args.dry_run:
        save_state(state)
    if args.emit and total:
        emit_event(
            f"Ada memory: {total} distilled draft(s) for review",
            "Session-summary distillation found candidate memories. "
            "Review docs/ada-memory/inbox/ after the next --export-inbox run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
