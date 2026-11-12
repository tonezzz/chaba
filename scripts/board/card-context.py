#!/usr/bin/env python3
"""card-context — build a just-enough context pack for one kanban card.

Emits a single markdown brief an agent (opencode session, Devin dispatch,
Ada) can start from without seeing the whole board:

  card fields (verbatim spec/brief) + open requests + recent comms
  + repo files referenced in the card text (existence-checked, head
  excerpts) + the conventions/gates block + a synthesized done-condition.

Usage:
  card-context.py CARD_ID [--ssh idc03] [--repo ROOT] [--max-files N]
                  [--head LINES] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from importlib import import_module  # noqa: E402

_board_cli = import_module("board-cli")

REPO = Path(os.environ.get(
    "CHABA_REPO",
    __file__.rsplit("/scripts/", 1)[0] if "/scripts/" in __file__ else "."))

PATH_RE = re.compile(
    r"(?:^|[\s'\"(])((?:docs|scripts|integrations|stacks|apps|tests|"
    r"opencode|\.github|reports)/[\w./~:@+-]+)")
FILE_TOKEN_RE = re.compile(
    r"(?:^|[\s'\"(])([\w.+-]+\.(?:py|mjs|js|ts|sh|yml|yaml|md|json|php))")
DONE_HINTS = re.compile(
    r"(verif|done|deploy|expect|must|should|gate|check|test|confirm)",
    re.IGNORECASE)
MAX_COMMS = 5


def fetch_card(cid: str, ssh: str | None, api: str | None) -> dict:
    if api:
        _board_cli.API = api
    out = _board_cli.call("GET", f"/cards?id={cid}&limit=1", None, ssh)
    cards = out.get("cards") or []
    if not cards:
        raise SystemExit(f"card {cid!r} not found")
    return cards[0]


def card_text(card: dict) -> str:
    parts = [card.get("brief") or "", card.get("spec") or ""]
    for c in (card.get("comms") or [])[-MAX_COMMS:]:
        parts.append(str(c.get("text") or ""))
    for r in (card.get("requests") or []):
        parts.append(str(r.get("ask") or ""))
        parts.append(str(r.get("answer") or ""))
    return "\n".join(parts)


def referenced_files(text: str, repo: Path) -> list[Path]:
    """Path-shaped tokens that exist under the repo, deduped, in order."""
    seen, found = set(), []
    for m in PATH_RE.finditer(text):
        p = m.group(1).rstrip(".,;:)]")
        f = repo / p
        if f.is_file() and p not in seen:
            seen.add(p)
            found.append(f)
    # bare filenames like board-api.py — resolve under common dirs
    for m in FILE_TOKEN_RE.finditer(text):
        name = m.group(1)
        if "/" in name:
            continue
        hits = list(repo.glob(f"**/{name}"))[:1]
        for f in hits:
            rel = str(f.relative_to(repo))
            if rel not in seen:
                seen.add(rel)
                found.append(f)
    return found


def done_condition(card: dict) -> str:
    """Best-effort done-condition: last DONE_HINTS sentence in spec,
    else the brief's tail."""
    spec = (card.get("spec") or "").replace("\n", " ")
    sentences = re.split(r"(?<=[.;:])\s+", spec)
    hinted = [s.strip() for s in sentences if DONE_HINTS.search(s)]
    if hinted:
        return hinted[-1]
    brief = (card.get("brief") or "").strip()
    return (brief[:200] if brief
            else "(no explicit done-condition — derive one from spec "
                 "before starting)")


def excerpt(path: Path, head: int) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()[:head]
    except OSError:
        return "(unreadable)"
    return "\n".join(lines)


def build(card: dict, repo: Path, max_files: int, head: int) -> str:
    text = card_text(card)
    files = referenced_files(text, repo)[:max_files]
    md = []
    md.append(f"# Card {card.get('ref') or card.get('id')}: "
              f"{card.get('title')}")
    md.append("")
    md.append(f"- id: `{card.get('id')}`  ref: `{card.get('ref')}`")
    md.append(f"- column: `{card.get('column')}`  "
              f"priority: `{card.get('priority')}`  "
              f"program: `{card.get('program') or '-'}`")
    if card.get("tags"):
        md.append(f"- tags: {', '.join(card['tags'])}")
    md.append("")
    if card.get("brief"):
        md += ["## Brief", "", card["brief"], ""]
    if card.get("spec"):
        md += ["## Spec (verbatim)", "", card["spec"], ""]
    open_reqs = [r for r in (card.get("requests") or [])
                 if r.get("status") not in ("answered", "closed")]
    if open_reqs:
        md += ["## Open requests (needs human input first)", ""]
        for r in open_reqs:
            md.append(f"- {r.get('ask')} "
                      f"(options: {', '.join(r.get('options') or [])})")
        md.append("")
    comms = (card.get("comms") or [])[-MAX_COMMS:]
    if comms:
        md += ["## Recent comms", ""]
        for c in comms:
            body = str(c.get("text") or "")
            md.append(f"- `{c.get('at')}` {c.get('from')}: "
                      f"{body[:300]}{'…' if len(body) > 300 else ''}")
        md.append("")
    if files:
        md += ["## Referenced files (exist in repo)", ""]
        for f in files:
            rel = f.relative_to(repo)
            md += [f"### {rel}", "", "```",
                   excerpt(f, head), "```", ""]
    md += ["## Gates & conventions", "",
           "- Work in a dispatch worktree; never edit the live checkout.",
           "- Card mutations go through board-api (see "
           "scripts/board/board-cli.py), never card-YAML edits.",
           "- Push via scripts/git-safe-push.sh; open a PR, let CI gate.",
           "- Verify real state before asserting done "
           "(unit status, curl codes, file contents — not memory).",
           "- No secrets in chat/commits; never print token/password "
           "values.", ""]
    md += ["## Done-condition (synthesized — check before finishing)", "",
           done_condition(card), ""]
    return "\n".join(md)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--ssh", default="idc03")
    ap.add_argument("--api", default=None)
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--max-files", type=int, default=8)
    ap.add_argument("--head", type=int, default=40)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    card = fetch_card(args.id, args.ssh or None, args.api)
    md = build(card, Path(args.repo).resolve(),
               args.max_files, args.head)
    if args.out:
        Path(args.out).write_text(md)
        print(f"wrote {args.out} ({len(md)} bytes)")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
