from __future__ import annotations

import pytest

from scripts.board.ada_job_envelope import (
    can_transition, receipt, transition_record, validate_envelope,
    validate_result, validate_transition,
)


def envelope(**overrides):
    value = {
        "job_id": "ada-1010-envelope",
        "card_id": "ada-dev-control-plane-envelope",
        "project": "chaba",
        "repo": "chaba",
        "worktree": "/tmp/chaba-ada-1010",
        "task_class": "bounded-development",
        "objective": "Define the shared job envelope.",
        "requirements": ["preserve board truth"],
        "acceptance_criteria": ["schema and tests pass"],
        "executor": "opencode",
        "model": "test-model",
        "target_host": "tony-dell",
        "allowed_paths": ["schemas", "scripts/board", "tests/board"],
        "input_artifacts": [],
        "output_artifacts": ["result.json", "summary.md", "diff.patch", "tests.json"],
        "verify": ["pytest"],
        "approval_required": ["merge", "deploy"],
        "timeout_s": 900,
        "idempotency_key": "ada-1010-envelope-v1",
        "state": "draft",
    }
    value.update(overrides)
    return value


def result(**overrides):
    value = {
        "status": "pass",
        "artifacts": ["result.json", "summary.md", "diff.patch", "tests.json"],
        "verifier": "pytest",
        "evidence": ["tests/board/test_ada_job_envelope.py"],
    }
    value.update(overrides)
    return value


def test_valid_envelope():
    assert validate_envelope(envelope()) == []


def test_required_and_path_safety():
    assert "missing:objective" in validate_envelope({})
    assert "allowed_paths:path-traversal:../secret" in validate_envelope(envelope(allowed_paths=["../secret"]))


def test_executor_and_unknown_fields_fail_closed():
    assert "executor:unknown" in validate_envelope(envelope(executor="ada"))
    assert "unknown:surprise" in validate_envelope(envelope(surprise=True))


def test_lifecycle_is_forward_only():
    assert can_transition("draft", "ready")
    assert can_transition("review", "approved")
    assert not can_transition("done", "running")
    assert not can_transition("running", "done")
    assert can_transition("running", "failed")
    assert can_transition("stalled", "claimed")
    assert can_transition("failed", "ready")
    assert not can_transition("cancelled", "ready")


def test_result_requires_artifacts_verifier_and_evidence():
    assert validate_result(result()) == []
    assert "artifact:missing:diff.patch" in validate_result(result(artifacts=[]))
    assert "verifier:missing" in validate_result(result(verifier=""))


def test_receipt_never_turns_pass_into_approval():
    value = receipt(envelope(), result())
    assert value["verified"] is True
    assert "merge" in value["approval_required"]
    assert "approved" not in value


def test_transition_record_is_durable_and_attributed():
    rec = transition_record(
        envelope(state="ready"), "claimed",
        actor="devin", host="tony-dell",
        evidence=["dispatch-wt-20261106"], at="2026-11-06T13:00:00+00:00")
    assert rec["job_id"] == "ada-1010-envelope"
    assert rec["from"] == "ready" and rec["to"] == "claimed"
    assert rec["actor"] == "devin" and rec["host"] == "tony-dell"
    assert rec["at"] == "2026-11-06T13:00:00+00:00"
    assert rec["evidence"] == ["dispatch-wt-20261106"]


def test_transition_record_rejects_invalid_or_unattributed():
    with pytest.raises(ValueError):
        transition_record(envelope(state="done"), "running",
                          actor="devin", host="tony-dell")
    with pytest.raises(ValueError):
        transition_record(envelope(state="ready"), "claimed",
                          actor="", host="tony-dell")
    with pytest.raises(ValueError):
        transition_record(envelope(state="ready"), "claimed",
                          actor="devin", host="")
    with pytest.raises(ValueError):
        validate_transition("bogus", "ready")
