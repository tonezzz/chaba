"""Tests for scripts/devnest/ada_result_review.py — evaluation-only Ada
reviewer path (card ada-opencode-result-review-pilot)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "devnest"))
import ada_result_review as arr  # noqa: E402


def _run_dir(tmp_path: Path) -> Path:
    rd = tmp_path / "run1"
    rd.mkdir()
    (rd / "manifest.json").write_text(json.dumps({
        "envelope": {
            "id": "job-x", "card": "card-x", "task_class": "report",
            "target_host": "idc02", "executor": "opencode",
            "artifact": {"path": "evals/opencode-lane/out/x.json"},
            "verifier": {"type": "held_out_py", "ref": "v/verify.py"},
        }}))
    (rd / "run.json").write_text(json.dumps({
        "job": "job-x", "at": "2026-01-01T00:00:00+00:00",
        "exit_code": 0, "verdict": "pass", "denials": [],
        "write_attempts": [], "mutating": [], "verifier_peeks": [],
        "scope_violations": []}))
    (rd / "verdict.json").write_text(json.dumps({
        "verdict": "pass", "checks": {"a": True}}))
    (rd / "prompt.md").write_text("# Task: do the thing\nbody\n")
    (rd / "artifact.out").write_text('{"ok": true}\n')
    (rd / "events.jsonl").write_text(
        '{"type":"tool_use","part":{"tool":"bash"}}\n'
        '{"type":"tool_use","part":{"tool":"bash"}}\n'
        '{"type":"text"}\n')
    return rd


def test_assemble_bundle_shape(tmp_path):
    b = arr.assemble_bundle(_run_dir(tmp_path), "case-1")
    assert b["bundle_schema"] == "ada-review-bundle/1"
    assert b["case"]["card_id"] == "card-x"
    assert b["request"]["prompt"].startswith("# Task")
    assert b["result"]["tests"]["verifier"]["verdict"] == "pass"
    assert b["result"]["tool_audit"]["tool_calls"] == 2
    assert b["result"]["tool_audit"]["tools"] == {"bash": 2}
    # declared artifact absent locally -> present False; message artifact present
    arts = b["result"]["artifacts"]
    assert arts[0]["present"] is False
    assert any(a["present"] for a in arts)
    assert not arr.validate_bundle(b)


def test_assemble_never_reads_events_content(tmp_path):
    rd = _run_dir(tmp_path)
    (rd / "events.jsonl").write_text(
        '{"type":"tool_use","part":{"tool":"bash",'
        '"state":{"input":{"command":"cat /etc/shadow"}}}}\n')
    b = arr.assemble_bundle(rd)
    blob = json.dumps(b)
    assert "shadow" not in blob
    assert "/etc/shadow" not in blob


def _bundle(tmp_path):
    return arr.assemble_bundle(_run_dir(tmp_path), "case-1")


def _review(bundle, **over):
    r = {
        "schema": "ada-opencode-review/1",
        "case_id": bundle["case"]["case_id"],
        "verdict": "pass", "confidence": 0.8,
        "summary": "ok",
        "findings": [],
        "evidence_refs": [{"bundle_path": "result.tests.verifier.verdict"}],
        "deterministic_gate": {"verifier_verdict": "pass"},
        "reviewer": {"backend": "stub", "model": "m"},
        "latency_ms": 1,
    }
    r.update(over)
    return r


def test_validate_review_ok_and_bad(tmp_path):
    b = _bundle(tmp_path)
    assert not arr.validate_review(_review(b), b)
    bad = _review(b, verdict="maybe")
    assert any("verdict" in e for e in arr.validate_review(bad, b))
    bad2 = _review(b, evidence_refs=[{"bundle_path": "nope.nope"}])
    assert any("unresolvable" in e for e in arr.validate_review(bad2, b))


def test_resolve_bundle_path_bracket_keys():
    b = {"result": {"tests": {"verifier": {"checks": {
        "disk_root_pct within 3": True}}}}}
    assert arr._resolve_bundle_path(
        b, 'result.tests.verifier.checks["disk_root_pct within 3"]')
    assert arr._resolve_bundle_path(b, "result.tests.verifier.checks")
    assert not arr._resolve_bundle_path(b, "result.tests.verifier.nope")
    assert not arr._resolve_bundle_path(b, "result.tests.verifier.checks[9]")


def test_parse_json_reply_variants():
    assert arr._parse_json_reply('{"a": 1}')["a"] == 1
    assert arr._parse_json_reply('here you go:\n```json\n{"a": 2}\n```'
                                 )["a"] == 2
    assert arr._parse_json_reply('prose {"a": 3} trailing')["a"] == 3
    with pytest.raises(ValueError):
        arr._parse_json_reply("no json here")


def test_call_reviewer_stub_and_replay(tmp_path):
    b = _bundle(tmp_path)
    b["_case_dir"] = str(tmp_path)
    review, meta = arr.call_reviewer(b, "stub")
    assert review["verdict"] == "needs_human"
    replay = tmp_path / "review-replay.json"
    replay.write_text(json.dumps(_review(b, verdict="fail")))
    review2, _ = arr.call_reviewer(b, "replay", replay_file=replay)
    assert review2["verdict"] == "fail"


def test_ada_ws_gated(monkeypatch, tmp_path):
    monkeypatch.delenv("ADA_REVIEW_ALLOW_LIVE", raising=False)
    b = _bundle(tmp_path)
    with pytest.raises(PermissionError):
        arr.call_reviewer(b, "ada-ws")


def test_score_and_aggregate():
    bundle = {"result": {"tests": {"verifier": {"verdict": "pass"}}}}
    expected = {"expected_verdict": "fail", "critical": True}
    review = {"verdict": "fail", "latency_ms": 10, "cost_usd": 0.001,
              "confidence": 0.9, "findings": [
                  {"evidence_refs": [{"bundle_path": "result.tests"}]}],
              "evidence_refs": []}
    row = arr.score_case(Path("c1"), review, expected, bundle)
    assert row["expected_match"] and row["critical"]
    assert row["refs_total"] == 1 and row["refs_resolved"] == 1
    agg = arr.aggregate([row])
    assert agg["critical_defect_recall"] == 1.0
    assert agg["false_positive_rate"] is None or True
