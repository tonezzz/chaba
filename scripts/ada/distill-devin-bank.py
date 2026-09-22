#!/usr/bin/env python3
"""Distill raw Devin session transcripts in the devin memory bank into
weekly digest docs, then supersede the sources.

Substrate: sync-devin-summaries.py imports ~/.local/share/devin/cli/
summaries/history_*.md as subject=devin-session docs in
ada-ha-bank-devin-tony (~930 docs, mostly raw transcripts). They dominate
recall with noise. This job aggregates them into:

  devin/weekly-<YYYY>W<ww>   subject=devin-weekly-rollup   per ISO week

Each digest records source_keys in meta; a week is regenerated only when
its source set changed. Processed sources get status=superseded +
superseded_by=<rollup key> so recall (active-only) stops seeing raw
transcripts while the audit trail stays in MDDB revisions.

The current ISO week is never distilled — sessions may still be landing.

Usage:
  distill-devin-bank.py                    # all completed weeks
  distill-devin-bank.py --dry-run
  distill-devin-bank.py --week 2026W38     # one week only
  distill-devin-bank.py --max-weeks 4      # backlog in batches
  distill-devin-bank.py --keep-sources     # write rollups, don't supersede
Env: GEMINI_API_KEY (required), ADA_MEMORY_MDDB_URL, ADA_SUMMARY_MODEL
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

COLLECTION = "ada-ha-bank-devin-tony"
MODEL = os.environ.get("ADA_SUMMARY_MODEL", "gemini-3.5-flash-lite")
# Per-session prompt cap: the structured summary sits at the top of the
# imported transcript; the tail is mostly tool noise.
PER_DOC_CHARS = 3000
MAX_PROMPT_CHARS = 160_000
MAX_DOCS_PER_CHUNK = 40

PROMPT = """These are Devin CLI session transcripts/summaries from ISO week {week}.
Produce a compact markdown digest with exactly these sections:

## Highlights
Two to four sentences on what was worked on.

## Durable facts & decisions
Bullets: configuration changes, decisions, machine/host facts, credentials
locations (paths only — never values), things that remain true.

## Procedures & how-tos
Bullets: reusable runbooks or commands discovered — keep the exact commands.

## Open items
Bullets: unfinished work, unresolved problems, follow-ups mentioned.

Rules: drop small talk, tool-call noise, and system prompts. Paths,
service names, hostnames, and port numbers are the valuable parts —
preserve them verbatim. If a session is a continuation of another, treat
them as one piece of work."""

MERGE_PROMPT = """These are partial digests of Devin CLI sessions from ISO week
{week} (the week was split because there were too many sessions for one
pass). Merge them into one weekly digest with the same four sections:

## Highlights
## Durable facts & decisions
## Procedures & how-tos
## Open items

Deduplicate aggressively — continued work should appear once. Keep the
verbatim paths, commands, service names, and hostnames."""


def mval(doc: dict, field: str) -> str:
    v = (doc.get("meta") or {}).get(field) or [""]
    return str(v[0] if isinstance(v, list) else v)


def doc_date(doc: dict) -> date | None:
    raw = mval(doc, "date")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        ts = doc.get("addedAt") or doc.get("updatedAt")
        return datetime.fromtimestamp(ts, timezone.utc).date() if ts else None


def iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}W{iso[1]:02d}"


def update_meta(mddb: "ada_sync.Mddb", collection: str, key: str,
                meta: dict, content: str) -> None:
    """Meta-only update via PATCH /v1/update (content untouched, so no
    re-embed). Falls back to a full re-add if the endpoint rejects it."""
    r = mddb.s.patch(f"{mddb.base}/update",
                     json={"collection": collection, "key": key,
                           "lang": "en", "meta": meta},
                     timeout=mddb.timeout)
    if r.status_code != 200:
        mddb.add(collection, key, content, meta)


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


def chunk_sessions(sdocs: list[dict]) -> list[list[dict]]:
    """Split a week's sessions into chunks that fit the prompt budget."""
    chunks, cur, budget = [], [], MAX_PROMPT_CHARS
    for d in sdocs:
        size = min(len(d.get("contentMd") or ""), PER_DOC_CHARS) + 120
        if cur and (len(cur) >= MAX_DOCS_PER_CHUNK or budget - size < 0):
            chunks.append(cur)
            cur, budget = [], MAX_PROMPT_CHARS
        cur.append(d)
        budget -= size
    if cur:
        chunks.append(cur)
    return chunks


def distill_chunk(sdocs: list[dict], label: str) -> str | None:
    parts = []
    for d in sdocs:
        head = (d.get("contentMd") or "")[:PER_DOC_CHARS]
        parts.append(
            f"### session {mval(d, 'session_id') or d.get('key')} "
            f"({mval(d, 'date')})\n{head}"
        )
    return _gen(PROMPT.format(week=label) + "\n\n" + "\n\n".join(parts))


def distill_week(sdocs: list[dict], week: str) -> str | None:
    chunks = chunk_sessions(sdocs)
    if len(chunks) == 1:
        return distill_chunk(chunks[0], week)
    partials = []
    for i, chunk in enumerate(chunks, 1):
        text = distill_chunk(chunk, f"{week} (part {i}/{len(chunks)})")
        if not text:
            print(f"  chunk {i}/{len(chunks)} of {week} failed")
            return None
        partials.append(text)
        print(f"    chunk {i}/{len(chunks)} done ({len(text)} chars)")
    return _gen(
        MERGE_PROMPT.format(week=week)
        + "\n\n"
        + "\n\n".join(f"--- part {i} ---\n{t}" for i, t in enumerate(partials, 1))
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--week", help="only this ISO week (YYYYWww)")
    ap.add_argument("--max-weeks", type=int, default=0,
                    help="process at most N weeks, oldest first (0 = all)")
    ap.add_argument("--keep-sources", action="store_true",
                    help="write rollups but leave source docs active")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mddb = ada_sync.Mddb(args.mddb, timeout=120)
    # list_docs caps at 1000 — the bank is larger; fetch with a big limit.
    docs = mddb._post("/search", {"collection": args.collection, "limit": 10000})

    raw, rollups = [], {}
    for d in docs:
        subj, status = mval(d, "subject"), mval(d, "status")
        if subj == "devin-weekly-rollup":
            rollups[d.get("key")] = d
        elif subj == "devin-session" and status == "active":
            raw.append(d)

    current_week = iso_week(date.today())
    by_week: dict[str, list[dict]] = {}
    for d in raw:
        dd = doc_date(d)
        if not dd:
            continue
        w = iso_week(dd)
        if w == current_week:
            continue
        by_week.setdefault(w, []).append(d)

    weeks = sorted(by_week)
    if args.week:
        weeks = [w for w in weeks if w == args.week]
    if args.max_weeks:
        weeks = weeks[: args.max_weeks]

    print(f"{args.collection}: {len(raw)} active session docs, "
          f"{len(by_week)} completed weeks, processing {len(weeks)}")

    done = skipped = failed = 0
    for week in weeks:
        sdocs = sorted(by_week[week], key=lambda d: doc_date(d) or date.min)
        skeys = sorted(d.get("key") or "" for d in sdocs)
        key = f"devin/weekly-{week}"
        existing = rollups.get(key)
        if existing and (existing.get("meta") or {}).get("source_keys") == skeys:
            print(f"  = {key} (unchanged, {len(skeys)} sources)")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  (dry) w {key} ({len(sdocs)} sources)")
            done += 1
            continue

        text = distill_week(sdocs, week)
        if not text:
            failed += 1
            continue

        today = date.today().isoformat()
        meta = {
            "kind": ["note"],
            "status": ["active"],
            "scope": ["tony"],
            "bank": ["devin"],
            "source": ["extract"],
            "written_by": ["distill-devin-bank"],
            "subject": ["devin-weekly-rollup"],
            "period": [week],
            "valid_from": [doc_date(sdocs[0]).isoformat()],
            "last_verified": [today],
            "source_keys": skeys,
            "generated_at": [datetime.now(timezone.utc).isoformat()],
        }
        print(f"  w {key} ({len(sdocs)} sources, {len(text)} chars)")
        mddb.add(args.collection, key, text, meta)

        if not args.keep_sources:
            for d in sdocs:
                new_meta = dict(d.get("meta") or {})
                new_meta["status"] = ["superseded"]
                new_meta["superseded_by"] = [key]
                try:
                    update_meta(mddb, args.collection, d["key"], new_meta,
                                d.get("contentMd") or "")
                except Exception as exc:
                    print(f"    ! supersede {d.get('key')} failed: {exc}")
                    continue
                print(f"    ~ {d.get('key')} superseded")
        done += 1

    print(f"\n{done} weeks distilled, {skipped} unchanged, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
