#!/usr/bin/env python3
"""Ada recall-miss -> knowledge-gap drafts (knowledge-circle step 3).

Parses ada-ha service journals for bank-recall miss lines, clusters them
by normalized question, and writes a status=draft gap note into the
missed bank's MDDB collection. Drafts export to docs/ada-memory/inbox/
on the next sync-ada-memory-to-mddb.py --export-inbox run for human
review — closing the loop from "questions Ada couldn't answer" back into
capture. See docs/ada-memory/tony-projects/knowledge-circle.md.

ada-pi logs (conversation_memory.py):
  bank recall '<bank>': miss q="<json-escaped question>" (top scores=[...])
  (older builds logged no q= field — counted but not clustered)

Usage:
  memory-gap-report.py                        # analyze + write gap drafts
  memory-gap-report.py --dry-run              # report only, no writes
  memory-gap-report.py --emit                 # also chaba-event on new gaps
  memory-gap-report.py --since '7 days ago' --min-misses 2
  memory-gap-report.py --ssh tony-dell --units ada-pi-pwa.service
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"
MDDB_BASE_URL = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
STATE = Path.home() / ".cache/ada-memory-gaps.json"

DEFAULT_UNITS = ["ada-ha-tony.service", "ada-ha-michael.service"]
MIN_MISSES = 2  # a question missed this often in the window is a real gap

# bank recall 'general': miss q="what is ..." (top scores=[...])
# The q= field is JSON-quoted; pre-2026-09-21 builds log no q at all.
MISS_RE = re.compile(
    r"bank recall '([^']+)': miss(?:\s+q=(\"(?:[^\"\\]|\\.)*\"))?"
)

EVENT_CMD = [
    "ssh", "tony-dell",
    "python3", "/home/tony/.config/home-assistant/scripts/chaba-event-log.py",
    "add", "-",
]

UNIT_INSTANCE_RE = re.compile(r"ada-ha-([a-z0-9_-]+)\.service")


def unit_instance(unit: str) -> str:
    """ada-ha-michael.service -> michael; anything else (ada-pi-pwa) -> tony."""
    m = UNIT_INSTANCE_RE.search(unit)
    return m.group(1) if m else "tony"


def journal_lines(unit: str, since: str, ssh_host: str | None) -> str:
    cmd = ["journalctl", "--user", "--since", since, "-o", "short-iso", "-u", unit]
    if ssh_host:
        cmd = ["ssh", ssh_host] + cmd
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def parse_misses(text: str) -> list[tuple[str, str | None]]:
    out = []
    for line in text.splitlines():
        m = MISS_RE.search(line)
        if not m:
            continue
        q = None
        if m.group(2):
            try:
                q = json.loads(m.group(2))
            except ValueError:
                q = None
        out.append((m.group(1), q))
    return out


def norm_q(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", q.lower())).strip()


def slug(text: str, max_words: int = 6) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:max_words]) or "gap"


def load_banks() -> dict[str, dict]:
    data = yaml.safe_load(SSOT.read_text())
    return data.get("banks") or {}


def collection_for(spec: dict, instance: str) -> str:
    return str(spec.get("mddb_collection") or "").replace("{instance}", instance)


def _post(path: str, payload: dict, timeout: int = 20):
    req = urllib.request.Request(
        f"{MDDB_BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST" if path != "/update" else "PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        if exc.code == 400 and "not found" in body.lower():
            return "missing"
        print(f"  {path} failed: HTTP {exc.code} {body}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  {path} failed: {exc}", file=sys.stderr)
        return None


def gap_exists(collection: str, subject: str) -> bool:
    """A gap draft/doc with this subject already exists (any status)."""
    docs = _post("/search", {
        "collection": collection,
        "filterMeta": {"subject": [subject]},
        "limit": 5,
    })
    return bool(docs)


def write_gap(collection: str, bank: str, scope: str, queries: list[str],
              since: str) -> bool:
    today = date.today().isoformat()
    subject = f"gap-{slug(queries[0])}"
    key = f"gap/{today}-{subject[4:]}"
    sample = "\n".join(f'- "{q}"' for q in sorted(set(queries))[:8])
    body = (
        f"# Knowledge gap in the {bank} bank\n\n"
        f"Ada could not answer these questions ({len(queries)} miss(es) "
        f"in the last {since}):\n\n{sample}\n\n"
        "Fill in the answer below, then promote to the bank with "
        "consolidate-memory.py — or delete this note if out of scope.\n"
    )
    meta = {
        "bank": [bank],
        "kind": ["note"],
        "scope": [scope],
        "status": ["draft"],
        "source": ["extract"],
        "written_by": ["memory-gap-report"],
        "subject": [subject],
        "valid_from": [today],
        "last_verified": [today],
    }
    result = _post("/add", {
        "collection": collection, "key": key, "lang": "en",
        "contentMd": body, "meta": meta,
    }, timeout=120)  # /add embeds inline — slow embedding providers need it
    return result is not None


def emit_event(title: str, body: str) -> None:
    payload = json.dumps({
        "title": title,
        "category": "ada-memory",
        "source": "memory-gap-report",
        "severity": "warn",
        "body": body,
        "requires_response": True,
        "confidence": 0.8,
    })
    try:
        r = subprocess.run(EVENT_CMD, input=payload, capture_output=True,
                           text=True, timeout=30)
        print(f"event: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    except Exception as exc:
        print(f"event emit failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="7 days ago")
    ap.add_argument("--units", nargs="+", default=DEFAULT_UNITS)
    ap.add_argument("--min-misses", type=int, default=MIN_MISSES)
    ap.add_argument("--ssh", default=None,
                    help="read journals from this host instead of locally")
    ap.add_argument("--emit", action="store_true",
                    help="post a chaba-event when new gap drafts are written")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    banks = load_banks()
    misses: list[tuple[str, str | None, str]] = []  # (bank, query, instance)
    for unit in args.units:
        text = journal_lines(unit, args.since, args.ssh)
        for bank, q in parse_misses(text):
            misses.append((bank, q, unit_instance(unit)))

    no_query = sum(1 for _, q, _ in misses if q is None)
    print(f"{len(misses)} bank-recall miss(es) in last {args.since} "
          f"({no_query} without logged query — pre-2026-09-21 builds)")

    clusters: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for bank, q, instance in misses:
        if q:
            clusters[(bank, instance, norm_q(q))].append(q)

    created = skipped = failed = 0
    for (bank, instance, _nq), queries in sorted(
        clusters.items(), key=lambda kv: -len(kv[1])
    ):
        if len(queries) < args.min_misses:
            continue
        spec = banks.get(bank)
        if not spec or not spec.get("writable"):
            print(f"  - {bank} x{len(queries)} (read-only/unknown bank — "
                  f"report only): {queries[0][:60]!r}")
            continue
        collection = collection_for(spec, instance)
        scope = "shared" if spec.get("scope") == "shared" else instance
        subject = f"gap-{slug(queries[0])}"
        if gap_exists(collection, subject):
            skipped += 1
            print(f"  = {bank}/{instance} gap {subject!r} already recorded")
            continue
        print(f"  + {bank}/{instance} gap {subject!r} ({len(queries)} misses)")
        if not args.dry_run:
            if write_gap(collection, bank, scope, queries, args.since):
                created += 1
            else:
                failed += 1

    print(f"done: {created} gap draft(s), {skipped} existing, {failed} failed")
    if args.emit and created:
        emit_event(
            f"Ada knowledge gaps: {created} new draft(s)",
            f"Recurring unanswered questions were drafted into memory banks "
            f"in the last {args.since}. Review docs/ada-memory/inbox/ after "
            f"the next --export-inbox run.",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
