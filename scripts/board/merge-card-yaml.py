#!/usr/bin/env python3
"""merge-card-yaml — git merge driver for kanban card YAML.

Registered as merge driver ``card-union`` for
``docs/ssot/kanban/cards/*.yml`` via .gitattributes, with
``merge.card-union.driver`` armed per checkout (git-safe-pull.sh and
install-hooks.sh self-arm it; info/attributes covers mid-rebase trees
whose checked-out .gitattributes predates the binding). git calls:

    merge-card-yaml.py %O %A %B

%O = merge-base version, %A = ours (result is written back here),
%B = theirs. Exit 0 = clean merge. Exit non-zero = git leaves the path
conflicted, and safe-pull's generated-path resolver then preserves the
local side as .local-conflict-* and resolves upstream-wins — the same
contract as before this driver existed (card
kanban-commit-reconcile-rebase-deadlocks-4d95a9).

Why: a card that diverged semantically on both sides used to stop the
kanban-commit rebase at every replayed step (2026-10-23 incident —
275 commits stuck ~6h, board truth unpushed). Cards are append-mostly
YAML and union-comms resolution is mechanical, so the driver merges
inline via reconcile-local-conflicts.merge_cards: comms unioned and
deduped on (at|ts, from, text), requests merged by id (more-resolved
side wins), action/ask per-key union, board scalars won by the newer
``updated``, generic keys won by %A/ours (upstream during a rebase —
matching the old upstream-wins convention — the default branch during
dispatch merges). Deletions of entries do not propagate; cards are
append-mostly and dropping a raced write is the worse failure.

CLI: merge-card-yaml.py %O %A %B   (invoked by git, not by hand)
     merge-card-yaml.py --selftest
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent


def _load_merge_cards():
    spec = importlib.util.spec_from_file_location(
        "reconcile_local_conflicts",
        _HERE / "reconcile-local-conflicts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.merge_cards


merge_cards = _load_merge_cards()


def _load_yaml(p: Path):
    return yaml.safe_load(p.read_text())


def merge_files(ours_p: Path, theirs_p: Path) -> int:
    """Union-merge theirs into ours (written back). 0 on success."""
    try:
        ours = _load_yaml(ours_p)
        theirs = _load_yaml(theirs_p)
        if not isinstance(ours, dict) or not isinstance(theirs, dict):
            raise ValueError("card YAML is not a mapping")
    except Exception as e:
        print(f"merge-card-yaml: cannot merge ({e}) — leaving conflict",
              file=sys.stderr)
        return 1
    try:
        merged, notes = merge_cards(ours, theirs)
        ours_p.write_text(yaml.safe_dump(
            merged, allow_unicode=True, sort_keys=False, width=110))
    except Exception as e:
        print(f"merge-card-yaml: merge failed ({e}) — leaving conflict",
              file=sys.stderr)
        return 1
    if notes:
        print("merge-card-yaml: " + "; ".join(notes[:6]), file=sys.stderr)
    return 0


def _selftest() -> None:
    import tempfile

    def card(**kw):
        c = {"id": "t", "title": "t", "column": "backlog",
             "updated": "2026-10-23 08:00", "comms": []}
        c.update(kw)
        return c

    with tempfile.TemporaryDirectory() as td:
        ours_p = Path(td) / "ours.yml"
        theirs_p = Path(td) / "theirs.yml"
        base_p = Path(td) / "base.yml"

        # semantic divergence: ours moved column+comms, theirs added comms
        base_p.write_text(yaml.safe_dump(card()))
        ours_p.write_text(yaml.safe_dump(card(
            column="done", updated="2026-10-23 14:00",
            comms=[{"at": "2026-10-23 14:00", "from": "devin",
                    "text": "local done"}])))
        theirs_p.write_text(yaml.safe_dump(card(
            updated="2026-10-23 09:00",
            comms=[{"at": "2026-10-23 09:00", "from": "ada",
                    "text": "origin note"}])))
        assert merge_files(ours_p, theirs_p) == 0
        out = yaml.safe_load(ours_p.read_text())
        assert out["column"] == "done"            # newer updated wins
        assert out["updated"] == "2026-10-23 14:00"
        assert {c["text"] for c in out["comms"]} == \
            {"local done", "origin note"}          # comms unioned

        # unparseable side -> non-zero, ours untouched
        ours_p.write_text("a: [unclosed\n")
        assert merge_files(ours_p, theirs_p) == 1
        assert ours_p.read_text() == "a: [unclosed\n"

        # non-mapping -> non-zero
        ours_p.write_text("- a\n- b\n")
        assert merge_files(ours_p, theirs_p) == 1

    print("merge-card-yaml: selftest OK")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
        return 0
    if len(sys.argv) < 4:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: merge-card-yaml.py %O %A %B", file=sys.stderr)
        return 2
    # argv[1]=%O (ancestor — union policy does not need it), argv[2]=%A
    # ours (written back), argv[3]=%B theirs.
    return merge_files(Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    sys.exit(main())
