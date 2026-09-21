#!/usr/bin/env python3
"""Back up Ada memory-bank MDDB collections to JSON files.

Banks are the only memory state with no copy outside MDDB — voice-written
docs exist nowhere else until exported to the vault inbox. This dumps every
bank collection (plus the rolling recall summaries) so a lost/corrupted
MDDB can be rebuilt.

Privacy: personal banks and any bank whose dir is in PRIVATE_DIRS are
written to a local-only dir (default ~/.local/share/ada-backups/), never
into the repo. Repo-bound dumps are also scanned for credential-shaped
content and quarantined to the private dir on a hit — the devin bank and
recall summaries carry raw transcripts that have already leaked real
secrets once (GEMINI_API_KEY / HOME_ASSISTANT_TOKEN, blocked by GitHub
push protection 2026-09-21).

Usage:
  backup-mddb-banks.py                # dump all banks (shared→repo, private→local)
  backup-mddb-banks.py --dry-run      # report what would be written
  backup-mddb-banks.py --git          # write + git add/commit+push the repo dump
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "ada_sync", Path(__file__).with_name("sync-ada-memory-to-mddb.py")
)
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

DEFAULT_OUT = REPO / "backups/ada-memory"
DEFAULT_PRIVATE_OUT = Path.home() / ".local/share/ada-backups/ada-memory"

# Vault-dir prefixes whose contents are uncontrolled (raw transcripts,
# session summaries) — always private, regardless of curation status.
PRIVATE_DIRS = ("personal", "devin")

# Credential-shaped content that must never reach the public repo. A hit
# on a repo-bound dump quarantines the whole file to the private dir.
SECRET_PATTERNS = re.compile(
    r"AIza[0-9A-Za-z_\-]{20,}|"            # Google/GCP API keys
    r"ya29\.[0-9A-Za-z_\-]{20,}|"          # Google OAuth access tokens
    r"ghp_[0-9A-Za-z]{20,}|"               # GitHub PATs
    r"xox[baprs]-[0-9A-Za-z-]{10,}|"       # Slack tokens
    r"sk-[0-9A-Za-z]{20,}|"                # OpenAI-style keys
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:(api[_-]?key|token|secret))\s*[=:]\s*[\"']?[A-Za-z0-9_\-\.]{24,}"
)


_ENV_REF = re.compile(
    r"^(process\.env|os\.environ|os\.getenv|\$\{|ENV\[|<[A-Z_]+>$)")


def scan_for_secrets(text: str) -> list[str]:
    hits = []
    for m in SECRET_PATTERNS.finditer(text):
        hit = m.group(0)
        # "KEY = process.env.X" / "TOKEN=${X}" are references, not values.
        value = re.split(r"\s*[=:]\s*[\"']?", hit, maxsplit=1)[-1]
        if len(m.groups()) > 0 and m.group(1) and _ENV_REF.match(value):
            continue
        hits.append(hit[:40])
    return sorted(set(hits))


def dump_collection(mddb: "ada_sync.Mddb", collection: str) -> dict:
    docs = mddb.list_docs(collection)
    return {
        "collection": collection,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "doc_count": len(docs),
        "docs": docs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mddb", default=ada_sync.MDDB)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT,
                    help="repo-side dump dir (git-backable)")
    ap.add_argument("--private-output", type=Path, default=DEFAULT_PRIVATE_OUT,
                    help="local-only dir for personal banks")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--git", action="store_true",
                    help="git add+commit+push the repo dump dir afterwards")
    args = ap.parse_args()

    mapping = ada_sync.load_bank_map()
    mddb = ada_sync.Mddb(args.mddb)

    # Bank collections + the rolling recall summaries (the other recallable
    # state that exists only in MDDB).
    import yaml
    banks = yaml.safe_load(ada_sync.SSOT.read_text()).get("banks") or {}
    instances = {i for spec in banks.values() for i in (spec.get("instances") or [])}

    collections: list[tuple[str, str]] = []  # (collection, privacy)
    for m in mapping:
        privacy = ("private" if m["dir"].startswith(PRIVATE_DIRS) else "repo")
        collections.append((m["collection"], privacy))
    for inst in sorted(instances):
        # Recall summaries are session-derived transcript content — the
        # same leak surface as raw transcripts; keep them private.
        collections.append((f"ada-ha-recall-summary-{inst}", "private"))

    written = 0
    for collection, privacy in dict.fromkeys(collections):
        try:
            data = dump_collection(mddb, collection)
        except Exception as exc:
            print(f"  ! {collection}: {exc}")
            continue
        if data["doc_count"] == 0:
            print(f"  = {collection} (empty, skipped)")
            continue
        payload = json.dumps(data, indent=1, ensure_ascii=False)
        if privacy == "repo":
            hits = scan_for_secrets(payload)
            if hits:
                privacy = "private"
                print(f"  ! {collection}: credential-shaped content "
                      f"({len(hits)} hit(s), e.g. {hits[0][:18]}...) — "
                      "quarantined to private dir")
        outdir = args.private_output if privacy == "private" else args.output
        path = outdir / f"{collection}.json"
        print(f"  {'(dry) ' if args.dry_run else ''}w {collection} -> {path} "
              f"({data['doc_count']} docs{' [local-only]' if privacy == 'private' else ''})")
        if not args.dry_run:
            outdir.mkdir(parents=True, exist_ok=True)
            path.write_text(payload + "\n")
        written += 1

    print(f"\n{written} collection(s) dumped")

    if args.git and not args.dry_run and args.output.exists():
        subprocess.run(["git", "-C", str(REPO), "add", str(args.output)], check=True)
        msg = f"backup(ada-memory): MDDB bank dump {datetime.now(timezone.utc):%Y-%m-%d}"
        subprocess.run(["git", "-C", str(REPO), "commit", "-qm", msg])
        subprocess.run(["git", "-C", str(REPO), "push", "origin", "HEAD"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
