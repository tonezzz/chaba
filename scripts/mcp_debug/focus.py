"""MCP Debug focus integration."""
import yaml
from .config import REPO_DIR


def mcp_focus(request=None):
    focus_current = REPO_DIR / "docs" / "ssot" / "ssot.focus.current.yml"
    if not focus_current.exists():
        return {"ok": False, "error": "ssot.focus.current.yml not found"}
    with open(focus_current) as f:
        doc = yaml.safe_load(f)
    active = {}
    quick_wins = [
        i for s in doc.get("sections", [])
        if s.get("title") == "Quick Wins"
        for i in s.get("items", [])
    ]
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not item or item.get("status") != "active":
                    continue
                section = sec.get("title")
                if section == "Active Shared Focus":
                    active["shared"] = item
                else:
                    active["branch"] = item

    if not request:
        return {"ok": True, "active": active, "quick_wins": quick_wins}

    # Simple intake suggestion based on the decision_tree in ssot.focus.current.yml
    req = str(request).lower()
    suggestion = {"request": request, "action": "inbox", "reason": "No obvious match; needs triage"}

    for label, it in [("shared", active.get("shared")), ("branch", active.get("branch"))]:
        if not it:
            continue
        if it.get("label", "").lower() in req:
            suggestion = {"action": "active", "section": label, "label": it["label"], "reason": "Request mentions the active focus"}
            break
        for st in it.get("subtasks", []):
            if st.get("label", "").lower() in req:
                suggestion = {"action": "active", "section": label, "label": it["label"], "subtask": st["label"], "reason": "Request matches an active subtask"}
                break
        else:
            continue
        break
    else:
        for q in quick_wins:
            if q.get("label", "").lower() in req:
                suggestion = {"action": "quick_win", "label": q["label"], "reason": "Request matches a completed quick win"}
                break

    for cue, action, reason in [
        ("all", "active", "Request uses 'all' or implies continuing current work"),
        ("focus", "active", "Request is about the focus system; continue active focus"),
        ("quick", "quick_win", "Request sounds small"),
        ("small", "quick_win", "Request sounds small"),
        ("fix", "quick_win", "Request sounds small"),
        ("tweak", "quick_win", "Request sounds small"),
        ("design", "backlog", "Request is new strategic design work"),
        ("workflow", "backlog", "Request is new strategic design work"),
        ("rebuild", "backlog", "Request is new strategic design work"),
        ("implement", "backlog", "Request is multi-step implementation"),
    ]:
        if cue in req:
            suggestion = {"action": action, "reason": reason}
            break

    return {"ok": True, "active": active, "quick_wins": quick_wins, "intake_suggestion": suggestion}

