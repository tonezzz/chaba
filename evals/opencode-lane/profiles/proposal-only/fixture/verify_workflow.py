import json
from pathlib import Path


POLICY_FIELDS = {
    "task_class", "risk_level", "target_host", "allowed_paths",
    "mcp_allowlist", "execution_allowed", "human_gate_required",
    "output_artifact", "verifier", "done_condition", "lane", "route",
    "policy",
}


def verify(run_dir):
    root = Path(run_dir)
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        proposal = json.loads((root / "artifact.out").read_text())
        events = [json.loads(line) for line in
                  (root / "events.jsonl").read_text().splitlines()
                  if line.strip()]
        config = json.loads((root / "opencode.json").read_text())
    except Exception as exc:
        return {"verdict": "fail",
                "checks": {"evidence readable": False,
                           "error": str(exc)[:300]}}
    if not isinstance(proposal, dict):
        return {"verdict": "fail",
                "checks": {"proposal is an object": False}}

    env = manifest.get("envelope") or {}
    proposal_text = json.dumps(proposal, ensure_ascii=False).lower()
    views = proposal.get("viewpoints")
    options = proposal.get("options")
    questions = proposal.get("open_questions")
    matches = proposal.get("matching_existing_work")
    checks = {
        "required fields": all(key in proposal for key in (
            "case_id", "goal", "recommendation", "viewpoints", "options",
            "assumptions", "open_questions", "matching_existing_work")),
        "case id matches": proposal.get("case_id") == env.get("case_id"),
        "goal and recommendation": all(
            isinstance(proposal.get(key), str) and proposal[key].strip()
            for key in ("goal", "recommendation")),
        "four viewpoint lenses": (
            isinstance(views, dict)
            and all(isinstance(views.get(key), str)
                    and len(views[key].split()) >= 7
                    for key in ("user_value", "technical",
                                "operations_safety", "cost_effort"))),
        "two options with tradeoffs": (
            isinstance(options, list) and len(options) == 2
            and all(isinstance(item, dict) and item.get("label")
                    and item.get("benefit") and item.get("tradeoff")
                    for item in options)),
        "assumptions and questions are lists": (
            isinstance(proposal.get("assumptions"), list)
            and isinstance(questions, list)),
        "existing work not invented": (
            isinstance(matches, dict)
            and matches.get("status") == "not_evaluated"
            and matches.get("matches") == []),
        "user value anchors canonical board": (
            isinstance(views, dict)
            and "chaba" in views.get("user_value", "").lower()
            and any(term in views.get("user_value", "").lower()
                    for term in ("card", "board"))),
        "technical role separation": (
            isinstance(views, dict)
            and all(term in views.get("technical", "").lower()
                    for term in ("opencode", "jev", "nest", "cline", "verifier"))),
        "safety mentions deterministic policy and human gate": (
            isinstance(views, dict)
            and any(term in views.get("operations_safety", "").lower()
                    for term in ("policy", "permission"))
            and any(term in views.get("operations_safety", "").lower()
                    for term in ("human", "gate"))
            and "isolated" in views.get("operations_safety", "").lower()),
        "cost considers local latency": (
            isinstance(views, dict)
            and any(term in views.get("cost_effort", "").lower()
                    for term in ("local", "latency", "slow"))),
        "recommendation honors repair-first card answer": (
            any(term in proposal.get("recommendation", "").lower()
                for term in ("repair", "adapter", "artifact"))
            and any(term in proposal.get("recommendation", "").lower()
                    for term in ("before", "first", "until"))),
        "options compare repair and manual analysis": (
            isinstance(options, list) and len(options) == 2
            and any(any(term in str(item.get("label", "")).lower()
                        for term in ("repair", "adapter"))
                    for item in options)
            and any(any(term in str(item.get("label", "")).lower()
                        for term in ("manual", "ui"))
                    for item in options)),
        "open question includes artifact contract": (
            isinstance(questions, list)
            and any(any(term in q.lower()
                        for term in ("artifact", "result_ref", "review"))
                    for q in questions if isinstance(q, str))),
        "no policy fields in model output": not (
            POLICY_FIELDS & set(proposal)),
        "no tool calls": not [
            (event.get("part") or {}).get("tool") for event in events
            if (event.get("part") or {}).get("tool")],
        "no MCP configured": not (config.get("mcp") or {}),
    }
    return {"verdict": "pass" if all(checks.values()) else "fail",
            "checks": checks, "case_id": env.get("case_id")}
