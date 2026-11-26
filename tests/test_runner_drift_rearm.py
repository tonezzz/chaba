"""Fixtures-only tests for the runner drift -> board re-arm helper."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "runner_drift_rearm", REPO / "scripts" / "board" / "runner-drift-rearm.py")
rearm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rearm)


def test_parses_drift_and_missing_dest_by_host():
    transcript = """
ok: [idc02] => {
    "msg": [
        "DRIFT  runner-agent src=1514c75c4679 inst=2a2fdcaf7f8a",
        "MISSING-DEST dispatch-queue"
    ]
}
ok: [idc03] => {
    "msg": [
        "OK     runner-agent src=1514c75c4679 inst=1514c75c4679"
    ]
}
"""
    findings = rearm.parse_audit(transcript)
    assert findings["idc02"] == ["DRIFT runner-agent", "MISSING-DEST dispatch-queue"]
    assert "idc03" not in findings


def test_clean_audit_has_no_findings():
    transcript = 'ok: [tony-omen] => {\n    "msg": ["OK     runner-agent src=a inst=a"]\n}\n'
    assert rearm.parse_audit(transcript) == {}
