#!/usr/bin/env python3
"""Append a miss record to the canonical repeat-ask register.

A miss is a retainable answer/lesson that lived only in a chat reply and was
never filed to a canonical sink (lesson / KB / SSOT / card). The register is
the single counter for both re-asks (`topics:`) and misses (`misses:`).

Posture: writes ONLY the `misses:` block of docs/ssot/ssot.repeat-asks.yml.
The insertion is textual and comment-preserving; every other byte of the file
is left untouched. Dedupe key: (topic, at, location, should_have_been).
Commit through the normal governed SSOT path (worktree, not the live checkout).

Usage:
  python3 scripts/chaba/miss-add.py --topic <slug> --location chat \
      --should-have-been "lesson:<slug>" --evidence "<message pointer>" \
      [--at YYYY-MM-DD] [--repo /path/to/chaba]
  python3 scripts/chaba/miss-add.py --self-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTER = Path("docs/ssot/ssot.repeat-asks.yml")
MISS_LINE = re.compile(r"^(misses:[ \t]*)(.*)$", re.MULTILINE)


def _quote(value: Any) -> str:
    # JSON string literals are valid YAML double-quoted scalars.
    return json.dumps(str(value if value is not None else ""), ensure_ascii=False)


def _records(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in (data.get("misses") or []) if isinstance(r, dict)]


def _key(rec: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(rec.get(k) or "") for k in ("topic", "at", "location", "should_have_been"))


def _render(rec: dict[str, Any], nl: str) -> str:
    lines = ["  - topic: " + _quote(rec.get("topic", ""))]
    lines += ["    " + f + ": " + _quote(rec.get(f, ""))
              for f in ("at", "location", "should_have_been", "evidence")]
    return nl.join(lines)


def add_miss(register: Path, rec: dict[str, Any]) -> str:
    """Append one deduped miss record. Returns a short status string."""
    raw = register.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    data = yaml.safe_load(raw) or {}
    key = _key(rec)
    if any(_key(e) == key for e in _records(data)):
        return "already recorded (dedupe hit)"

    m = MISS_LINE.search(raw)
    if not m:
        raise ValueError(f"no misses: block in {register} - add the schema first")

    block = _render(rec, nl)
    if m.group(2).strip() in ("", "[]", "null", "~"):
        new_raw = raw[:m.start()] + "misses:" + nl + block + raw[m.end():]
    else:
        # Insert before the first existing list item, not directly under the
        # `misses:` line -- otherwise a second append splits the first record
        # away from its continuation fields.
        item = re.compile(r"^  - ", re.MULTILINE).search(raw, m.end())
        if not item:
            raise ValueError(f"malformed misses: block in {register}")
        new_raw = raw[:item.start()] + block + nl + raw[item.start():]

    fd, tmp = tempfile.mkstemp(dir=register.parent, prefix=".miss-add-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_raw)
        os.replace(tmp, register)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "miss recorded"


def self_test() -> int:
    fixture = (
        "# register header - must survive the write verbatim\n"
        "version: 1\n"
        "topics: []\n"
        "misses: []\n"
    )
    with tempfile.TemporaryDirectory() as d:
        reg = Path(d) / REGISTER
        reg.parent.mkdir(parents=True)
        reg.write_text(fixture, encoding="utf-8")

        rec = {"topic": "some-topic", "at": "2026-11-23", "location": "chat",
               "should_have_been": "lesson:some-slug", "evidence": "msg-ref-1"}
        assert add_miss(reg, rec) == "miss recorded"
        assert add_miss(reg, rec) == "already recorded (dedupe hit)"
        rec2 = dict(rec, topic="other-topic")
        assert add_miss(reg, rec2) == "miss recorded"

        raw = reg.read_text(encoding="utf-8")
        assert raw.startswith("# register header - must survive the write verbatim\n")
        data = yaml.safe_load(raw)
        assert len(data["misses"]) == 2, data
        assert {r["topic"] for r in data["misses"]} == {"some-topic", "other-topic"}
        first = next(r for r in data["misses"] if r["topic"] == "some-topic")
        assert first["evidence"] == "msg-ref-1"
        assert first["should_have_been"] == "lesson:some-slug"
    print("self-test: 7/7 passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", help="topic slug this miss belongs to")
    ap.add_argument("--location", default="chat", choices=["chat", "voice", "link"])
    ap.add_argument("--should-have-been", dest="should",
                    help="canonical sink that should have received it (e.g. lesson:foo)")
    ap.add_argument("--evidence", default="", help="pointer to the message/artifact")
    ap.add_argument("--at", default=dt.date.today().isoformat(), help="ISO date (default today)")
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()
    if not a.topic or not a.should:
        ap.error("--topic and --should-have-been are required")

    reg = a.repo / REGISTER
    if not reg.exists():
        print(f"error: register not found: {reg}", file=sys.stderr)
        return 2
    rec = {"topic": a.topic, "at": a.at, "location": a.location,
           "should_have_been": a.should, "evidence": a.evidence}
    try:
        status = add_miss(reg, rec)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"miss-add: {status} -> {reg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
