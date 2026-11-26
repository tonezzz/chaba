"""Regression guard for the systemd ExecStart exit-status contract.

2026-11-21: the rate-limit retry change added ``rc=${PIPESTATUS[0]}`` to
the ``/bin/bash -c`` payload of devin-dispatch's transient unit. systemd
expands ``${VAR}`` in ExecStart itself, so ``PIPESTATUS[0]`` was consumed
before bash ever saw it ("Invalid environment variable name evaluates to
an empty string: PIPESTATUS[0]") and the dispatch reported the wrong exit
code. ADA-1279 hit this after its re-lane: exit=2/INVALIDARGUMENT with a
real agent run behind it.

The fix is ``set -o pipefail`` plus ``rc=$?``: ``$?`` is not a braced
variable, so systemd leaves it for bash. Probe-verified on idc02 with a
unit that piped a failing command through tee (rc=7, as expected).

Source inspection only — no systemd, network, or dispatch side effects.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DISPATCH = REPO / "scripts" / "devin" / "devin-dispatch.sh"

UNIT_RE = re.compile(r"/bin/bash -c '([^']*)'")
SYSTEMD_VAR_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def execstart_body() -> str:
    match = UNIT_RE.search(DISPATCH.read_text())
    assert match, "devin-dispatch.sh lost its /bin/bash -c ExecStart payload"
    return match.group(1)


class DevinUnitExitStatusTest(unittest.TestCase):
    def setUp(self):
        self.body = execstart_body()

    def test_no_pipestatus_in_execstart(self):
        # $${PIPESTATUS[0]} is NOT a fix: systemd consumes the ${...}
        # before bash can expand PIPESTATUS. Verified on a live transient
        # unit. The token must be absent from the payload entirely.
        self.assertNotIn("PIPESTATUS", self.body)

    def test_pipefail_captures_pipeline_status(self):
        self.assertIn("set -o pipefail", self.body)
        self.assertIn("| tee", self.body)
        self.assertIn("rc=$?;", self.body)
        self.assertLess(
            self.body.index("| tee"), self.body.index("rc=$?;"),
            "pipeline exit code must be captured with pipefail + $?")

    def test_no_systemd_expandable_braced_variables(self):
        expandable = SYSTEMD_VAR_RE.findall(self.body)
        self.assertFalse(
            expandable,
            "systemd expands ${NAME} in ExecStart before bash: "
            f"{expandable}")


if __name__ == "__main__":
    unittest.main()
