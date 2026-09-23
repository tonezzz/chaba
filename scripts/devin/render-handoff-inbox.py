#!/usr/bin/env python3
"""Render ada-ha-bank-devin-handoff bank docs into docs/ssot/focus-inbox/
entries so repo-based triage (Devin sessions, overnight focus sweep) sees
the pending Ada-written implementation specs.

- One file per live bank doc: handoff-<key>.yml (draft status).
- Repo targeting comes from meta repo/applies_to (whitelist-restricted,
  defaults to chaba).
- Docs whose status is retracted/superseded lose their inbox file; GC
  only touches files carrying our renderer marker.
- Idempotent: unchanged renders are skipped.

Runs from devin-dispatch-watch.timer (best-effort tail of the watch
script) and manually. Bank docs are written by Ada via ada_remember —
keep them short and self-contained; the rendered text goes to an agent.

Usage: render-handoff-inbox.py [--dry-run] [--inbox DIR]
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location(
    "ada_sync",
    Path(__file__).resolve().parents[1] / "ada" / "sync-ada-memory-to-mddb.py",
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

COLLECTION = "ada-ha-bank-devin-handoff"
REPOS = {"chaba", "ada-pi", "sunsynk-card"}
DEAD_STATES = {"retracted", "superseded", "archived"}
MAX_TEXT = 3000
MARKER = "render-handoff-inbox"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INBOX = REPO_ROOT / "docs/ssot/focus-inbox"


def _first(meta: dict, name: str) -> str | None:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v) if isinstance(v, str) else None


def _all(meta: dict, name: str) -> list[str]:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return [str(x) for x in v]
    return [v] if isinstance(v, str) else []


def _slug(key: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    return (s or "doc")[:80]


def _title(key: str, meta: dict, body: str) -> str:
    subj = _first(meta, "subject")
    if subj:
        return subj[:120]
    m = re.search(r"^#\s+(.+)$", body, re.M)
    return (m.group(1).strip() if m else key)[:120]


def _repo(meta: dict) -> str:
    for cand in _all(meta, "repo") + _all(meta, "applies_to"):
        if cand in REPOS:
            return cand
    return "chaba"


def render_entry(key: str, doc: dict) -> dict:
    meta = doc.get("meta") or {}
    body = doc.get("contentMd") or ""
    repo = _repo(meta)
    text = body.strip()
    if len(text) > MAX_TEXT:
        text = f"{text[:MAX_TEXT].rstrip()}\n\n[truncated — full spec in bank doc {key}]"
    return {
        "title": _title(key, meta, body),
        "subtitle": f"Devin handoff spec: {key}",
        "icon": "robot",
        "focus": {
            "label": _title(key, meta, body),
            "text": text,
            "branch": repo,
            "priority": _first(meta, "priority") or "medium",
            "status": "draft",
            "tags": sorted({"devin", "handoff", *_all(meta, "tags")}),
            "safe_to_parallel": {
                "value": True,
                "reason": "Spec document; execution goes through devin_dispatch which creates an isolated worktree.",
            },
            "subtasks": [
                {
                    "label": f"Dispatch via devin_dispatch (repo {repo}, prompt references bank doc {key})",
                    "status": "not_started",
                }
            ],
        },
        "ownership": {"owner": "tony", "session": "", "locked": False, "lock_reason": ""},
        "source": {
            "bank_key": key,
            "renderer": MARKER,
            "date": date.today().isoformat(),
        },
    }


def _dump(entry: dict) -> str:
    return yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=100)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mddb = ada_sync.Mddb(args.mddb, timeout=30)
    docs = mddb.list_docs(COLLECTION)

    live: dict[str, dict] = {}
    for doc in docs:
        key = doc.get("key") or ""
        status = (_first(doc.get("meta"), "status") or "active").lower()
        if key and status not in DEAD_STATES:
            live[key] = doc

    args.inbox.mkdir(parents=True, exist_ok=True)
    written = skipped = removed = 0
    live_files = set()
    for key, doc in sorted(live.items()):
        path = args.inbox / f"handoff-{_slug(key)}.yml"
        live_files.add(path.name)
        out = _dump(render_entry(key, doc))
        if path.exists() and path.read_text() == out:
            skipped += 1
            continue
        if args.dry_run:
            print(f"would write {path.name}")
        else:
            path.write_text(out)
        written += 1

    # GC: remove generated files whose bank doc is gone or dead.
    for path in args.inbox.glob("handoff-*.yml"):
        if path.name in live_files:
            continue
        try:
            if MARKER not in path.read_text():
                continue  # not ours
        except OSError:
            continue
        if args.dry_run:
            print(f"would remove {path.name}")
        else:
            path.unlink()
        removed += 1

    print(f"handoff inbox: {written} written, {skipped} unchanged, "
          f"{removed} removed, {len(live)} live bank docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
