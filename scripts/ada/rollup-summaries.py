#!/usr/bin/env python3
"""Roll per-session summaries up into daily/weekly/monthly docs.

Substrate: ada-pi writes kind=session-summary docs
(session-<date>-<sid>) into ada-ha-recall-summary-<instance> at session
close. This job aggregates them into:

  daily-<YYYY-MM-DD>     kind=daily-summary    from that day's sessions
  weekly-<YYYY>W<ww>     kind=weekly-summary   from that ISO week's dailies
  monthly-<YYYY-MM>      kind=monthly-summary  from that month's dailies

Each rollup doc records source_keys in meta; a period is only regenerated
when its source set changed (new session/day landed). Runs nightly before
the backup timer so rollups are captured in backups/ada-memory/.

Usage:
  rollup-summaries.py              # roll up all instances
  rollup-summaries.py --instance tony --dry-run
Env: GEMINI_API_KEY (summarizer), ADA_MEMORY_MDDB_URL, ADA_SUMMARY_MODEL
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

MODEL = os.environ.get("ADA_SUMMARY_MODEL", "gemini-3.5-flash-lite")


def summarize(texts: list[str], label: str) -> str | None:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set — cannot summarize")
        return None
    import asyncio
    try:
        from google import genai
        joined = "\n\n".join(f"- {t}" for t in texts)
        prompt = (
            f"Session summaries for {label}:\n{joined}\n\n"
            "Summarize what happened across these sessions in two to four "
            "sentences. Keep concrete facts, decisions, and requests; drop "
            "small talk."
        )

        async def _gen() -> str | None:
            resp = await genai.Client(
                api_key=os.environ["GEMINI_API_KEY"]
            ).aio.models.generate_content(model=MODEL, contents=prompt)
            return (resp.text or "").strip() or None

        return asyncio.run(_gen())
    except Exception as exc:
        print(f"summarize({label}) failed: {exc}")
        return None


def docs_by_kind(docs: list[dict], kind: str) -> list[dict]:
    return [d for d in docs
            if (d.get("meta") or {}).get("kind", [""])[0] == kind]


def doc_keys(docs: list[dict]) -> list[str]:
    return sorted(d.get("key") or "" for d in docs)


def rollup_needed(existing: dict | None, source_keys: list[str]) -> bool:
    if existing is None:
        return True
    return (existing.get("meta") or {}).get("source_keys") != source_keys


def write_rollup(mddb: "ada_sync.Mddb", collection: str, key: str, kind: str,
                 period: str, source_keys: list[str], text: str,
                 dry: bool) -> None:
    meta = {
        "kind": [kind],
        "period": [period],
        "source": ["rollup-summaries"],
        "source_keys": source_keys,
        "generated_at": [datetime.now(timezone.utc).isoformat()],
    }
    print(f"  {'(dry) ' if dry else ''}w {key} ({len(source_keys)} sources)")
    if not dry:
        mddb.add(collection, key, text, meta)


def rollup_instance(mddb: "ada_sync.Mddb", instance: str, dry: bool) -> None:
    coll = f"ada-ha-recall-summary-{instance}"
    docs = mddb.list_docs(coll)
    sessions = docs_by_kind(docs, "session-summary")
    dailies = {d.get("key"): d for d in docs_by_kind(docs, "daily-summary")}

    # --- daily: group sessions by meta.date ---
    by_day: dict[str, list[dict]] = {}
    for d in sessions:
        day = str((d.get("meta") or {}).get("date", [""])[0] or "")
        if day:
            by_day.setdefault(day, []).append(d)
    for day, sdocs in sorted(by_day.items()):
        key = f"daily-{day}"
        skeys = doc_keys(sdocs)
        if not rollup_needed(dailies.get(key), skeys):
            print(f"  = {key} (unchanged)")
            continue
        text = summarize([d.get("contentMd") or "" for d in sdocs], day)
        if text:
            write_rollup(mddb, coll, key, "daily-summary", day, skeys, text, dry)

    # Re-read so today's new dailies are visible to weekly/monthly.
    if not dry:
        docs = mddb.list_docs(coll)
    dailies = {d.get("key"): d for d in docs_by_kind(docs, "daily-summary")}
    rollups = {d.get("key"): d for d in docs
               if str((d.get("meta") or {}).get("kind", [""])[0]).endswith("-summary")
               and str((d.get("meta") or {}).get("kind", [""])[0])
               not in ("session-summary", "daily-summary")}

    # --- weekly + monthly: group dailies by ISO week / month ---
    by_week: dict[str, list[dict]] = {}
    by_month: dict[str, list[dict]] = {}
    for key, d in dailies.items():
        day = key.removeprefix("daily-")
        try:
            dt = date.fromisoformat(day)
        except ValueError:
            continue
        iso = dt.isocalendar()
        by_week.setdefault(f"{iso[0]}W{iso[1]:02d}", []).append(d)
        by_month.setdefault(day[:7], []).append(d)
    for week, ddocs in sorted(by_week.items()):
        key = f"weekly-{week}"
        skeys = doc_keys(ddocs)
        if not rollup_needed(rollups.get(key), skeys):
            continue
        text = summarize([d.get("contentMd") or "" for d in ddocs],
                         f"ISO week {week}")
        if text:
            write_rollup(mddb, coll, key, "weekly-summary", week, skeys, text, dry)
    for month, ddocs in sorted(by_month.items()):
        key = f"monthly-{month}"
        skeys = doc_keys(ddocs)
        if not rollup_needed(rollups.get(key), skeys):
            continue
        text = summarize([d.get("contentMd") or "" for d in ddocs],
                         f"month {month}")
        if text:
            write_rollup(mddb, coll, key, "monthly-summary", month, skeys, text, dry)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--instance", action="append",
                    help="limit to instance(s); default = all from bank registry")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import yaml
    banks = yaml.safe_load(ada_sync.SSOT.read_text()).get("banks") or {}
    all_instances = sorted({i for spec in banks.values()
                            for i in (spec.get("instances") or [])})
    instances = args.instance or all_instances or ["tony", "michael"]

    mddb = ada_sync.Mddb(args.mddb)
    for inst in instances:
        print(f"ada-ha-recall-summary-{inst}:")
        rollup_instance(mddb, inst, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
