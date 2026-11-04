#!/usr/bin/env python3
"""Validation and evidence contracts for ADA-1010 job envelopes."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

EXECUTORS = {"opencode", "devin", "script", "manual", "kk_mac_local"}
LIFECYCLE = (
    "draft", "ready", "claimed", "running", "verifying",
    "review", "approved", "merged", "done",
    "failed", "stalled", "cancelled",
)
RESULT_ARTIFACTS = ("result.json", "summary.md", "diff.patch", "tests.json")
REQUIRED = (
    "job_id", "card_id", "project", "repo", "worktree", "task_class",
    "objective", "requirements", "acceptance_criteria", "executor", "model",
    "target_host", "allowed_paths", "input_artifacts", "output_artifacts",
    "verify", "approval_required", "timeout_s", "idempotency_key", "state",
)
_TRANSITIONS = {
    "draft": {"ready", "cancelled"},
    "ready": {"claimed", "cancelled"},
    "claimed": {"running", "failed", "stalled", "cancelled"},
    "running": {"verifying", "failed", "stalled", "cancelled"},
    "verifying": {"review", "failed", "stalled"},
    "review": {"approved", "failed", "cancelled"},
    "approved": {"merged", "failed"},
    "merged": {"done", "failed"},
    "done": set(),
    "failed": {"ready", "cancelled"},
    "stalled": {"claimed", "cancelled"},
    "cancelled": set(),
}


def validate_envelope(envelope: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    known = set(REQUIRED) | {"lane", "profile"}
    errors.extend(f"unknown:{key}" for key in sorted(set(envelope) - known))
    missing = [key for key in REQUIRED if key not in envelope]
    errors.extend(f"missing:{key}" for key in missing)
    job_id = envelope.get("job_id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", job_id):
        errors.append("job_id:invalid-slug")
    if envelope.get("executor") not in EXECUTORS:
        errors.append("executor:unknown")
    if envelope.get("state") not in LIFECYCLE:
        errors.append("state:unknown")
    timeout = envelope.get("timeout_s")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 30 <= timeout <= 86400:
        errors.append("timeout_s:outside-30..86400")
    for field in ("requirements", "acceptance_criteria", "allowed_paths", "input_artifacts", "output_artifacts", "verify", "approval_required"):
        if field in envelope and not isinstance(envelope[field], list):
            errors.append(f"{field}:must-be-list")
    for field in ("allowed_paths", "input_artifacts", "output_artifacts"):
        for value in envelope.get(field, []) if isinstance(envelope.get(field), list) else []:
            path = PurePosixPath(str(value))
            if path.is_absolute() or ".." in path.parts:
                errors.append(f"{field}:path-traversal:{value}")
    return errors


def can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, set())


def validate_transition(current: str, target: str) -> None:
    if current not in LIFECYCLE:
        raise ValueError(f"unknown lifecycle state: {current}")
    if not can_transition(current, target):
        raise ValueError(f"invalid lifecycle transition: {current} -> {target}")


def validate_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if result.get("status") not in {"pass", "fail", "held"}:
        errors.append("status:must-be-pass-fail-held")
    artifacts = set(result.get("artifacts") or [])
    for required in RESULT_ARTIFACTS:
        if required not in artifacts:
            errors.append(f"artifact:missing:{required}")
    if not result.get("verifier"):
        errors.append("verifier:missing")
    if not result.get("evidence"):
        errors.append("evidence:missing")
    return errors


def receipt(envelope: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Create a compact evidence receipt; never claims approval or merge."""
    errors = validate_envelope(envelope) + validate_result(result)
    return {
        "job_id": envelope.get("job_id"),
        "card_id": envelope.get("card_id"),
        "executor": envelope.get("executor"),
        "status": "invalid" if errors else result.get("status"),
        "verified": not errors and result.get("status") == "pass",
        "errors": errors,
        "artifacts": result.get("artifacts") or [],
        "verifier": result.get("verifier"),
        "evidence": result.get("evidence") or [],
        "approval_required": envelope.get("approval_required") or [],
    }
