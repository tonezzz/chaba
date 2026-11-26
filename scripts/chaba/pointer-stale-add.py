#!/usr/bin/env python3
"""Record a stale-pointer incident for the Phase D capture metric.

A stale pointer is a captured ref (path/key/query) that no longer resolves to
the canonical source. Repeated hits on one pointer should be promoted to a
card — this helper only records them; promotion stays a separate decision.

Posture: writes ONLY the local `incidents:` block of the capture log
(~/.local/share/chaba/capture/pointer-incidents.yml). Nothing canonical is
written; no SSOT mutation, no board mutation, no Ada memory write. Dedupe key:
(pointer_ref, canonical_ref, found_at).

Usage:
  python3 scripts/chaba/pointer-stale-add.py --init
  python3 scripts/chaba/pointer-stale-add.py --pointer-ref <ref> \
      --canonical-ref <ref> [--as-of YYYY-MM-DD] [--found-at YYYY-MM-DD] \
      [--fix <text>] [--fix-ref <card-or-comm-ref>]
  python3 scripts/chaba/pointer-stale-add.py --self-test
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

DEFAULT_LOG = Path.home() / ".local/share/chaba/capture/pointer-incidents.yml"
INCIDENT_LINE = re.compile(r"^(incidents:[ \t]*)(.*)$", re.MULTILINE)
HEADER = (
    "# Stale-pointer incident log (Phase D local telemetry)\n"
    "# Written by scripts/chaba/pointer-stale-add.py; read by capture-metrics.py.\n"
    "# Local-only: no canonical sink, no board mutation.\n"
    "# 3+ hits on one pointer_ref -> promote to a kanban card (separate decision).\n"
)


def _quote(value: Any) -> str:
    return json.dumps(str(value if value is not None else ""), ensure_ascii=False)


def _records(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in (data.get("incidents") or []) if isinstance(r, dict)]


def _key(rec: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(rec.get(k) or "") for k in ("pointer_ref", "canonical_ref", "found_at"))


def init_log(log: Path) -> str:
    if log.exists():
        return "log already initialized"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(HEADER + "incidents: []\n", encoding="utf-8")
    return "log initialized"


def add_incident(log: Path, rec: dict[str, Any]) -> str:
    if not log.exists():
        init_log(log)
    raw = log.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    data = yaml.safe_load(raw) or {}
    key = _key(rec)
    if any(_key(e) == key for e in _records(data)):
        return "already recorded (dedupe hit)"

    m = INCIDENT_LINE.search(raw)
    if not m:
        raise ValueError(f"no incidents: block in {log}")
    fields = ("pointer_ref", "as_of", "canonical_ref", "found_at", "fix", "fix_ref")
    lines = ["  - pointer_ref: " + _quote(rec.get("pointer_ref", ""))]
    lines += ["    " + f + ": " + _quote(rec.get(f, "")) for f in fields[1:]]
    block = nl.join(lines)
    if m.group(2).strip() in ("", "[]", "null", "~"):
        new_raw = raw[:m.start()] + "incidents:" + nl + block + raw[m.end():]
    else:
        item = re.compile(r"^  - ", re.MULTILINE).search(raw, m.end())
        if not item:
            raise ValueError(f"malformed incidents: block in {log}")
        new_raw = raw[:item.start()] + block + nl + raw[item.start():]

    fd, tmp = tempfile.mkstemp(dir=log.parent, prefix=".ptr-stale-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_raw)
        os.replace(tmp, log)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "incident recorded"


def self_test() -> int:
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "pointer-incidents.yml"
        assert init_log(log) == "log initialized"
        assert init_log(log) == "log already initialized"
        rec = {"pointer_ref": "docs/ssot/old.yml", "as_of": "2026-01-01",
               "canonical_ref": "docs/ssot/new.yml", "found_at": "2026-11-23",
               "fix": "retarget pointer", "fix_ref": "OPS-0016"}
        assert add_incident(log, rec) == "incident recorded"
        assert add_incident(log, rec) == "already recorded (dedupe hit)"
        rec2 = dict(rec, canonical_ref="docs/ssot/newer.yml")
        assert add_incident(log, rec2) == "incident recorded"
        data = yaml.safe_load(log.read_text())
        assert len(data["incidents"]) == 2, data
        assert log.read_text().startswith("# Stale-pointer incident log")
    print("self-test: 7/7 passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--init", action="store_true", help="create the log schema if absent")
    ap.add_argument("--pointer-ref", help="the stale pointer ref/path/key")
    ap.add_argument("--canonical-ref", help="where it should point now")
    ap.add_argument("--as-of", default="", help="stale pointer's declared as_of")
    ap.add_argument("--found-at", default=dt.date.today().isoformat())
    ap.add_argument("--fix", default="", help="short fix description")
    ap.add_argument("--fix-ref", default="", help="card/comm ref tracking the fix")
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()
    if a.init and not a.pointer_ref:
        print(f"pointer-stale-add: {init_log(a.log)} -> {a.log}")
        return 0
    if not a.pointer_ref or not a.canonical_ref:
        ap.error("--pointer-ref and --canonical-ref are required (or use --init)")
    rec = {"pointer_ref": a.pointer_ref, "as_of": a.as_of,
           "canonical_ref": a.canonical_ref, "found_at": a.found_at,
           "fix": a.fix, "fix_ref": a.fix_ref}
    try:
        status = add_incident(a.log, rec)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"pointer-stale-add: {status} -> {a.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
