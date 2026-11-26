#!/usr/bin/env python3
"""Checkout-role helper — single-writer detection for producers.

Every long-lived chaba checkout carries ``<gitdir>/chaba-role``
(``served|exec|readonly|job|branch|experiment`` — stamped by
``scripts/install-hooks.sh --role``; NOT git config, which is shared
across linked worktrees). Producers that write generated files into the
repo must check this before touching tracked paths: only the ``served``
checkout on idc03 can commit, so writes anywhere else die in a dirty
working tree (card exec-checkout-generated-writes-focus-inb-da698a).

Role semantics (AGENTS.md checkout-roles rule, 2026-10-22):
  - ``served``  — the writer; generated writes + commits are legal.
  - ``exec``/``readonly``/``job``/``branch``/``experiment`` — non-writer;
    route generated output through board-api or a local-only dir.
  - ``""`` (unset) — legacy/unstamped checkout: treated as non-writer by
    ``is_served_checkout`` callers that pass ``strict=True``; default
    ``checkout_role`` returns "" and callers decide.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def checkout_role(repo) -> str:
    """Return the stamped chaba-role for ``repo`` ('' when unset/unknown)."""
    repo = Path(repo)
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if r.returncode != 0 or not r.stdout.strip():
        return ""
    try:
        return (Path(r.stdout.strip()) / "chaba-role").read_text().strip()
    except OSError:
        return ""


def is_served_checkout(repo, strict: bool = False) -> bool:
    """True when ``repo`` is the single-writer (served) checkout.

    With ``strict=True`` an unstamped checkout counts as non-writer —
    use for producers where a dead write is worse than no write.
    """
    role = checkout_role(repo)
    if role:
        return role == "served"
    return not strict
