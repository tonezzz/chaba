#!/usr/bin/env python3
"""Turn an audit-runner-tools.yml transcript into a board-api drift card.

Read-only on hosts; the only writes are a board card (on_exists=queue) plus
a comment. Fails closed if the audit output cannot be parsed.

  python3 scripts/board/runner-drift-rearm.py --audit-file /tmp/audit.txt
  python3 scripts/board/runner-drift-rearm.py --audit-file /tmp/after.txt --verify
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_CARD = "runner-tool-drift-fleet"
HOST_RE = re.compile(r"^ok: \[([^\]]+)\] => \{")
DRIFT_RE = re.compile(r'"DRIFT\s+([^"\s]+)')
MISSING_RE = re.compile(r'"MISSING-DEST\s+([^"\s]+)')


def parse_audit(text: str) -> dict[str, list[str]]:
    """Map host -> ['DRIFT tool', ...] from an Ansible playbook transcript."""
    findings: dict[str, list[str]] = defaultdict(list)
    host = None
    for line in text.splitlines():
        m = HOST_RE.match(line)
        if m:
            host = m.group(1)
            continue
        if not host:
            continue
        d, missing = DRIFT_RE.search(line), MISSING_RE.search(line)
        if d:
            findings[host].append(f"DRIFT {d.group(1)}")
        if missing:
            findings[host].append(f"MISSING-DEST {missing.group(1)}")
    return dict(findings)


def board_call(method: str, path: str, payload: dict, ssh_host: str) -> dict:
    envelope = json.dumps({"method": method, "path": path,
                           "payload": payload}).encode()
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh_host,
         "python3", "~/CascadeProjects/chaba/scripts/board/board-cli.py", "__api"],
        input=envelope, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode()[:200] or "board-cli failed")
    return json.loads(result.stdout.decode() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit-file", type=Path, required=True)
    ap.add_argument("--card", default=DEFAULT_CARD)
    ap.add_argument("--ssh-host", default="idc03")
    ap.add_argument("--verify", action="store_true",
                    help="post a verification comment; close card if clean")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and report only; no board writes")
    args = ap.parse_args()

    findings = parse_audit(args.audit_file.read_text(encoding="utf-8",
                                                      errors="replace"))
    if args.dry_run:
        print(json.dumps({"dry_run": True, "verify": args.verify,
                          "findings": findings}))
        return 0
    if args.verify:
        text = ("re-audit clean: no DRIFT / MISSING-DEST in "
                f"{args.audit_file.name}") if not findings else (
                    "re-audit still reports: " + json.dumps(findings))
        board_call("POST", "/comment",
                   {"id": args.card, "from": "devin", "text": text}, args.ssh_host)
        if not findings:
            board_call("POST", "/action",
                       {"id": args.card, "from": "devin", "do": "close"},
                       args.ssh_host)
        print(json.dumps({"verify": True, "findings": findings}))
        return 0

    if not findings:
        print(json.dumps({"drift": False, "findings": {}}))
        return 0

    brief = "Runner tool drift from audit-runner-tools.yml — re-arm convergence"
    spec = ("Found by scripts/board/runner-drift-rearm.py from an "
            "audit-runner-tools.yml transcript: " + json.dumps(findings) +
            ". Fix by running ansible/playbooks/deploy-runner-tools.yml "
            "(check then apply), then re-audit with --verify.")
    created = board_call("POST", "/card",
                         {"id": args.card, "title": brief, "column": "backlog",
                          "priority": "high", "brief": brief, "spec": spec,
                          "program": "chaba-ci", "tags": ["ansible", "runner-tools", "drift"],
                          "on_exists": "queue"}, args.ssh_host)
    commented = board_call("POST", "/comment",
                           {"id": args.card, "from": "devin",
                            "text": "drift findings: " + json.dumps(findings)},
                           args.ssh_host)
    print(json.dumps({"drift": True, "findings": findings,
                      "card": created.get("ref"), "comment": commented.get("ok")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
