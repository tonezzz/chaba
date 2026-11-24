from pathlib import PurePosixPath


MODEL_POLICY_FIELDS = {
    "task_class", "risk_level", "target_host", "allowed_paths",
    "mcp_allowlist", "execution_allowed", "human_gate_required",
    "output_artifact", "verifier", "done_condition", "lane", "route",
    "policy",
}
PROPOSAL_FIELDS = {
    "case_id", "goal", "recommendation", "viewpoints", "options",
    "assumptions", "open_questions", "matching_existing_work",
}
SNAPSHOT_FIELDS = {
    "source", "card_id", "version", "case_id", "task_class",
    "risk_level", "target_host", "allowed_paths", "mcp_allowlist",
    "artifact", "verifier", "done_condition", "human_gate_required",
    "expected_jev_route",
}
TASK_CLASSES = {"report", "read_only", "artifact_write", "manual"}
RISK_LEVELS = {"low", "medium", "high"}
JEV_ROUTES = {"free_lane", "manual", "devin", "standard"}


def _errors_for_policy(snapshot):
    errors = [
        f"missing_snapshot_field:{key}"
        for key in sorted(SNAPSHOT_FIELDS - set(snapshot))
    ]
    if errors:
        return errors
    if not isinstance(snapshot["card_id"], str) or not snapshot["card_id"].strip():
        errors.append("bad_snapshot_field:card_id")
    if not isinstance(snapshot["version"], (str, int)) or \
            not str(snapshot["version"]).strip():
        errors.append("bad_snapshot_field:version")
    if not isinstance(snapshot["case_id"], str) or not snapshot["case_id"].strip():
        errors.append("bad_snapshot_field:case_id")
    if snapshot["task_class"] not in TASK_CLASSES:
        errors.append(f"bad_snapshot_field:task_class={snapshot['task_class']}")
    if snapshot["risk_level"] not in RISK_LEVELS:
        errors.append(f"bad_snapshot_field:risk_level={snapshot['risk_level']}")
    if snapshot["target_host"] is not None and (
            not isinstance(snapshot["target_host"], str)
            or not snapshot["target_host"].strip()):
        errors.append("bad_snapshot_field:target_host")
    paths = snapshot["allowed_paths"]
    if not isinstance(paths, list):
        errors.append("bad_snapshot_field:allowed_paths")
    else:
        for path in paths:
            if not isinstance(path, str) or not path.strip():
                errors.append("bad_snapshot_path:empty")
                continue
            parsed = PurePosixPath(path)
            if parsed.is_absolute() or ".." in parsed.parts:
                errors.append(f"unsafe_snapshot_path:{path}")
    if snapshot["mcp_allowlist"] != []:
        errors.append("review_compiler_requires_empty_mcp_allowlist")
    if snapshot["artifact"] is not None and not isinstance(snapshot["artifact"], dict):
        errors.append("bad_snapshot_field:artifact")
    if not isinstance(snapshot["verifier"], dict) or not snapshot["verifier"]:
        errors.append("bad_snapshot_field:verifier")
    if not isinstance(snapshot["done_condition"], str) \
            or not snapshot["done_condition"].strip():
        errors.append("bad_snapshot_field:done_condition")
    if not isinstance(snapshot["human_gate_required"], bool):
        errors.append("bad_snapshot_field:human_gate_required")
    if snapshot["expected_jev_route"] not in JEV_ROUTES:
        errors.append(
            f"bad_snapshot_field:expected_jev_route={snapshot['expected_jev_route']}")
    return errors


def _errors_for_proposal(proposal, snapshot):
    errors = []
    if not isinstance(proposal, dict):
        return ["proposal_not_object"]
    errors.extend(
        f"missing_proposal_field:{key}"
        for key in sorted(PROPOSAL_FIELDS - set(proposal))
    )
    errors.extend(
        f"model_policy_field_present:{key}"
        for key in sorted(MODEL_POLICY_FIELDS & set(proposal))
    )
    if proposal.get("case_id") != snapshot["case_id"]:
        errors.append("proposal_case_id_mismatch")
    for key in ("goal", "recommendation"):
        if not isinstance(proposal.get(key), str) or not proposal[key].strip():
            errors.append(f"empty_proposal_field:{key}")
    viewpoints = proposal.get("viewpoints")
    lenses = ("user_value", "technical", "operations_safety", "cost_effort")
    if not isinstance(viewpoints, dict) or any(
            not isinstance(viewpoints.get(key), str)
            or not viewpoints[key].strip() for key in lenses):
        errors.append("invalid_proposal_field:viewpoints")
    options = proposal.get("options")
    if not isinstance(options, list) or len(options) != 2 or any(
            not isinstance(item, dict) or not item.get("label")
            or not item.get("benefit") or not item.get("tradeoff")
            for item in options):
        errors.append("invalid_proposal_field:options")
    if not isinstance(proposal.get("assumptions"), list):
        errors.append("invalid_proposal_field:assumptions")
    if not isinstance(proposal.get("open_questions"), list):
        errors.append("invalid_proposal_field:open_questions")
    matches = proposal.get("matching_existing_work")
    if not isinstance(matches, dict) or matches.get("status") != "not_evaluated" \
            or matches.get("matches") != []:
        errors.append("invalid_proposal_field:matching_existing_work")
    return errors


def compile_proposal(proposal, snapshot, jev_result):
    if not isinstance(snapshot, dict):
        return {"ok": False, "errors": ["snapshot_not_object"]}
    errors = _errors_for_policy(snapshot)
    if errors:
        return {"ok": False, "errors": errors}
    errors.extend(_errors_for_proposal(proposal, snapshot))
    if not isinstance(jev_result, dict):
        return {"ok": False, "errors": errors + ["jev_result_not_object"]}
    route = jev_result.get("lane")
    if route not in JEV_ROUTES:
        errors.append(f"bad_jev_route:{route}")
    elif route != snapshot["expected_jev_route"]:
        errors.append(
            f"jev_route_mismatch:expected={snapshot['expected_jev_route']}:"
            f"actual={route}")
    if route == "manual":
        if not snapshot["human_gate_required"]:
            errors.append("manual_route_requires_human_gate")
        if snapshot["allowed_paths"]:
            errors.append("manual_route_has_write_paths")
    if errors:
        return {"ok": False, "errors": errors}

    policy = {key: snapshot[key] for key in (
        "task_class", "risk_level", "target_host", "allowed_paths",
        "mcp_allowlist", "artifact", "verifier", "done_condition",
        "human_gate_required",
    )}
    policy["execution_allowed"] = False
    status = "proposal_ready"
    if snapshot["target_host"] is None or proposal["open_questions"]:
        status = "needs_clarification"
    elif snapshot["human_gate_required"] or route == "manual":
        status = "human_review_required"

    return {
        "ok": True,
        "compiled": {
            "schema_version": 1,
            "status": status,
            "card_snapshot": {
                "source": snapshot["source"],
                "id": snapshot["card_id"],
                "version": snapshot["version"],
            },
            "jev": {
                "route": route,
                "source": jev_result.get("source", "unknown"),
            },
            "proposal": proposal,
            "policy": policy,
            "execution_authorized": False,
            "human_review_required": (
                snapshot["human_gate_required"] or route == "manual"),
        },
    }
