#!/usr/bin/env python3
"""Runner-tooling pin gate for husky pre-commit / pre-merge-commit.

A pinned tool source may only change in the same commit that bumps its
sha256 in scripts/devin/runner-tooling.manifest.json. sync-runner-tools.sh
refuses unpinned sources, so a missed bump leaves the whole fleet on the
old build while the contract test only fires in CI.

Compares index blobs (``git show :path``) against HEAD (``git show
HEAD:path``): at pre-commit time that is the staged commit; at
pre-merge-commit time it is the merged tree vs the first parent — exactly
the "source from one parent, pins from the other" conflict shape from
ops-1036 (commit da9798df42c).

Only pairs the commit actually touches are checked, so pre-existing
breakage on master cannot block unrelated commits. Opt out with
CHABA_PRECOMMIT_PINS=0 (or ``git commit/merge --no-verify``).

parse_pins / relevant_paths / find_mismatches are pure — tests/board/
test_runner_tooling_contract.py exercises them without git or network.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

MANIFEST = "scripts/devin/runner-tooling.manifest.json"


def parse_pins(blob):
    """key -> (source, sha256) from a manifest blob (bytes | str | None)."""
    if not blob:
        return {}
    try:
        doc = json.loads(blob)
    except (ValueError, TypeError):
        return {}
    tools = doc.get("tools") if isinstance(doc, dict) else None
    if not isinstance(tools, dict):
        return {}
    return {
        str(key): ((val.get("source") or ""), (val.get("sha256") or ""))
        for key, val in tools.items() if isinstance(val, dict)
    }


def relevant_paths(pins):
    """Manifest plus every source it pins — the paths this gate cares about."""
    return {MANIFEST} | {src for src, _ in pins.values() if src}


def find_mismatches(staged_pins, head_pins, source_sha, touched):
    """Touched pin pairs whose committed source no longer matches its pin.

    staged_pins / head_pins: key -> (source, sha256) maps from parse_pins().
    source_sha(src): callable -> sha256 hex of the committed source blob,
        or None when the source is absent.
    touched: set of paths the commit or merge changed (index vs HEAD).

    Returns [(key, source, got_sha256, want_pin), ...].
    """
    bad = []
    for key, (src, want) in staged_pins.items():
        if not src or not want:
            continue
        pin_changed = head_pins.get(key) != (src, want)
        if src not in touched and not pin_changed:
            continue  # this pin pair is untouched by the commit
        got = source_sha(src)
        if got is None or got == want:
            continue
        bad.append((key, src, got, want))
    return bad


def check(repo=None):
    """Gate the current index against HEAD. Returns bad tuples ([] = pass)."""
    def show(spec):
        proc = subprocess.run(["git", "show", spec], capture_output=True,
                              cwd=repo)
        return proc.stdout if proc.returncode == 0 else None

    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo)
    touched = set((proc.stdout or "").split())

    mblob = show(":" + MANIFEST) or show("HEAD:" + MANIFEST)
    staged_pins = parse_pins(mblob)
    if not (touched & relevant_paths(staged_pins)):
        return []

    head_pins = parse_pins(show("HEAD:" + MANIFEST))

    def source_sha(src):
        blob = show(":" + src)
        if blob is None:
            blob = show("HEAD:" + src)
        if blob is None:
            return None
        return hashlib.sha256(blob).hexdigest()

    return find_mismatches(staged_pins, head_pins, source_sha, touched)


def main():
    if os.environ.get("CHABA_PRECOMMIT_PINS", "1") == "0":
        return 0
    bad = check()
    if not bad:
        return 0
    print("❌ BLOCKED: runner-tooling pin mismatch —", file=sys.stderr)
    for key, src, got, want in bad:
        print(f"   {key}: {src}\n"
              f"      committed sha256 {got}\n"
              f"      manifest pin     {want}", file=sys.stderr)
    print("   Bump the sha256 in " + MANIFEST + " in the SAME commit",
          file=sys.stderr)
    print("   (sync-runner-tools.sh refuses unpinned sources; the fleet"
          " stays on the old build).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
