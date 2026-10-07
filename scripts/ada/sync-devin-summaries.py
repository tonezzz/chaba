#!/usr/bin/env python3
"""Sync Devin session summaries into the ada-ha-bank-devin-tony MDDB
bank so Ada can recall "what did we work on" via ada_memory_search /
ada_session_recall(bank="devin").

Sources:
- ~/.local/share/devin/cli/summaries/history_*.md — CLI thread dumps,
  keyed devin/<hex-thread-id>.
- ~/.local/share/devin/summaries/*.md — devin-desktop per-session
  summaries, keyed devin-session/<friendly-name>. These carry the
  desktop session identity the hex keys lack.

- Skips empty files (continuation stubs).
- Idempotent: compares remote contentMd; unchanged files are skipped.
- Meta: kind=note, source=import, written_by=devin-cli/devin-desktop,
  session_id/session_name from the filename, date from file mtime — the
  standard provenance fields let the vault sync leave these docs alone
  (remote-only, kept).

Usage:
  sync-devin-summaries.py            # sync all summaries
  sync-devin-summaries.py --dry-run
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import time
import sys
from datetime import datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

CLI_SUMMARIES = Path.home() / ".local/share/devin/cli/summaries"
NAMED_SUMMARIES = Path.home() / ".local/share/devin/summaries"
COLLECTION = "ada-ha-bank-devin-tony"
# MDDB drops the connection on very large docs. Oversized files keep the
# distilled head (structured summary) plus the tail, where the outcome of
# the session usually lands.
MAX_CHARS = 50_000
HEAD_FRACTION = 0.6

# history_*.md dumps open with "=== MESSAGE 0 - System ===" holding the
# session preamble (<available_skills> or <system_info>) — near-identical
# boilerplate in every thread. Embedded whole it skews the doc vector so
# memory queries hit these dumps ahead of real content (the 2026-10-07
# 'Liam dub' audit: every ada_memory_search returned devin/* preamble
# fragments). Strip just that leading block; later System messages carry
# resume summaries and task context worth keeping.
_LEADING_PREAMBLE_RE = re.compile(
    r"\A=== MESSAGE 0 - System ===\n.*?(?==== MESSAGE |\Z)", re.S)


def _strip_preamble(text: str) -> str:
    return _LEADING_PREAMBLE_RE.sub("", text, count=1).lstrip()


def clip(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    head = int(MAX_CHARS * HEAD_FRACTION)
    tail = MAX_CHARS - head - 128  # room for the truncation marker
    omitted = len(text) - head - tail
    marker = f"\n\n[... {omitted} chars truncated ...]\n\n"
    return text[:head] + marker + text[-tail:]


def iter_docs(src_dir: Path):
    """Yield (file, key, meta_overrides) for every source doc."""
    for f in sorted(src_dir.glob("history_*.md")):
        sid = f.stem.removeprefix("history_")
        yield f, f"devin/{sid}", {"session_id": [sid], "attribute": [sid],
                                  "subject": ["devin-session"],
                                  "written_by": ["devin-cli"]}
    for f in sorted(NAMED_SUMMARIES.glob("*.md")):
        name = f.stem
        yield f, f"devin-session/{name}", {"session_name": [name],
                                           "attribute": [name],
                                           "subject": ["devin-session-summary"],
                                           "written_by": ["devin-desktop"]}


# A continuation summary embeds its parent: "Full conversation history
# saved at .../summaries/history_<hex>.md". Chains of resumed threads all
# sync as separate active docs, so recall returns overlapping ancestors —
# the chain tip's summary already covers them.
_PARENT_RE = re.compile(r"cli/summaries/history_([0-9a-f]+)\.md")


def _parent_sid(path: Path) -> str | None:
    head = path.read_text(errors="replace")[:4000]
    m = _PARENT_RE.search(head)
    return m.group(1) if m else None


def _chain_supersedes(src_dir: Path) -> dict[str, str]:
    """Map ancestor session_id -> tip session_id across resume chains."""
    children: dict[str, str] = {}  # parent sid -> newest child sid seen
    sids = set()
    for f in src_dir.glob("history_*.md"):
        sid = f.stem.removeprefix("history_")
        sids.add(sid)
        parent = _parent_sid(f)
        if parent and parent != sid:
            # newest child wins if a thread branched (mtime decides)
            prev = children.get(parent)
            if prev is None or f.stat().st_mtime > (
                    src_dir.joinpath(f"history_{prev}.md")
                    .stat().st_mtime if
                    src_dir.joinpath(f"history_{prev}.md").exists() else 0):
                children[parent] = sid

    def tip(sid: str) -> str:
        seen = set()
        while sid in children and sid not in seen:
            seen.add(sid)
            sid = children[sid]
        return sid

    return {p: tip(p) for p in children if p in sids}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=CLI_SUMMARIES)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dedupe-only", action="store_true",
                    help="run only the resume-chain supersede pass — "
                         "no new file writes (avoids the embed storm "
                         "when a large backlog is pending)")
    ap.add_argument("--max-writes", type=int, default=0,
                    help="cap new/changed doc writes this run — drain a "
                         "large backlog in chunks instead of one embed "
                         "storm (every add costs an embed call)")
    ap.add_argument("--write-delay", type=float, default=0.0,
                    help="seconds to sleep between doc writes")
    args = ap.parse_args()

    mddb = ada_sync.Mddb(args.mddb, timeout=120)  # large histories embed slowly
    remote = {d.get("key"): d for d in mddb.list_docs(COLLECTION)}
    chains = _chain_supersedes(args.dir)

    added = skipped = empty = unchanged = total = 0
    for f, key, extra_meta in iter_docs(args.dir):
        if args.dedupe_only:
            break
        total += 1
        text = f.read_text(errors="replace").strip()
        if not text:
            empty += 1
            continue
        body = clip(_strip_preamble(text))
        mtime = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
        old = remote.get(key)
        if old and (old.get("contentMd") or "") == body:
            unchanged += 1
            continue
        meta = {
            "kind": ["note"],
            "status": ["active"],
            "scope": ["tony"],
            "bank": ["devin"],
            "source": ["import"],
            "date": [mtime],
            **extra_meta,
        }
        # Resume-chain ancestors never enter as active — the chain tip's
        # summary already covers them, so they land pre-superseded.
        sid = extra_meta.get("session_id", [None])[0]
        if sid and sid in chains:
            meta["status"] = ["superseded"]
            meta["superseded_by"] = [f"devin/{chains[sid]}"]
        print(f"  {'(dry) ' if args.dry_run else ''}{'~' if old else '+'} {key} "
              f"({len(body)} chars, {mtime})")
        if not args.dry_run:
            if args.max_writes and added >= args.max_writes:
                print(f"  … write cap {args.max_writes} reached — "
                      "rerun to continue the backlog")
                break
            try:
                mddb.add(COLLECTION, key, body, meta)
            except Exception as exc:
                print(f"  ! {key} failed ({exc}) — continuing")
                skipped += 1
                continue
            if args.write_delay:
                time.sleep(args.write_delay)
        added += 1

    # Dedupe pass: ancestors of resume chains become superseded — their
    # content is subsumed by the chain tip's summary. Active search then
    # returns only tips instead of every continuation. (New ancestors are
    # already written superseded above; this pass repairs pre-existing
    # active ancestors.)
    sup = 0
    for parent_sid, tip_sid in chains.items():
        pkey = f"devin/{parent_sid}"
        old = remote.get(pkey)
        if not old:
            continue
        meta = dict(old.get("meta") or {})
        if meta.get("status") == ["superseded"]:
            continue
        meta["status"] = ["superseded"]
        meta["superseded_by"] = [f"devin/{tip_sid}"]
        print(f"  {'(dry) ' if args.dry_run else ''}supersede {pkey} "
              f"-> devin/{tip_sid}")
        if not args.dry_run:
            try:
                mddb.add(COLLECTION, pkey, old.get("contentMd") or "", meta)
            except Exception as exc:
                print(f"  ! {pkey} supersede failed ({exc}) — continuing")
                continue
        sup += 1

    print(f"\n{added} synced, {unchanged} unchanged, {empty} empty skipped, "
          f"{skipped} failed, {sup} superseded (of {total} files)")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
