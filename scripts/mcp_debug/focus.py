"""MCP Focus session-start router."""
from datetime import datetime
from pathlib import Path
import yaml
from .config import REPO_DIR


REPO = REPO_DIR
CURRENT = REPO / "docs" / "ssot" / "ssot.focus.current.yml"
FOCUS = REPO / "docs" / "ssot" / "ssot.focus.yml"
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"

PRIORITY = {"high": 3, "medium": 2, "low": 1}
QUICK_WIN_CUES = ("fix", "tweak", "small", "quick", "minor")
BACKLOG_CUES = ("design", "workflow", "rebuild", "implement", "refactor")


def _priority_value(item):
    return PRIORITY.get(item.get("priority", "medium"), 2)


def _triage_score(item):
    triage = item.get("triage", {})
    if not triage:
        return 0.0
    try:
        urgency = float(triage.get("urgency", 0))
        importance = float(triage.get("importance", 0))
        complication = float(triage.get("complication", 0))
    except (TypeError, ValueError):
        return 0.0
    return round(urgency * 0.4 + importance * 0.35 + (10 - complication) * 0.25, 2)


def _find_section(sections, title):
    for sec in sections:
        if sec.get("title") == title:
            return sec
    return None


def _load_current():
    with open(CURRENT) as f:
        return yaml.safe_load(f)


def _load_focus():
    with open(FOCUS) as f:
        return yaml.safe_load(f)


def _active_items(doc):
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
    return active, quick_wins


def _inbox_items():
    items = []
    if not INBOX_DIR.is_dir():
        return items
    for p in sorted(INBOX_DIR.glob("*.yml")):
        if p.name.startswith("TEMPLATE") or p.name == "processed":
            continue
        try:
            doc = yaml.safe_load(p.read_text())
        except yaml.YAMLError as e:
            continue
        focus = doc.get("focus") or doc
        if not focus or not focus.get("label"):
            continue
        focus["__file"] = p
        items.append(focus)
    return items


def _backlog_items():
    doc = _load_focus()
    section = _find_section(doc.get("sections", []), "Backlog - Triage Queue")
    if not section:
        return []
    return [
        i for i in section.get("items", [])
        if i and i.get("status") not in ("completed", "archived")
    ]


def _match_active(req, active):
    for key in ("branch", "shared"):
        it = active.get(key)
        if not it:
            continue
        if it.get("label", "").lower() in req:
            return key, it, "focus"
        for st in it.get("subtasks", []):
            if st.get("label", "").lower() in req:
                return key, it, st["label"]
    return None, None, None


def _match_quick_win(req, quick_wins):
    for q in quick_wins:
        if q.get("label", "").lower() in req:
            return q
    return None


def _match_backlog(req, backlog):
    for item in backlog:
        haystack = " ".join([
            item.get("label", ""),
            item.get("text", ""),
            " ".join(str(t) for t in item.get("tags", []))
        ]).lower()
        if req in haystack:
            return item
    return None


def _best_backlog(backlog):
    if not backlog:
        return None
    return max(backlog, key=lambda i: (_triage_score(i), _priority_value(i), i.get("started", "")))


def _best_inbox(inbox):
    if not inbox:
        return None
    return max(inbox, key=lambda i: (_priority_value(i), i.get("__file", Path("")).stem))


def _draft_inbox(request):
    label = request.strip()[:80]
    return {
        "title": "Focus Inbox Item",
        "subtitle": f"Intake for: {request}",
        "focus": {
            "label": label,
            "text": request.strip(),
            "status": "draft",
            "priority": "medium",
            "tags": ["intake"],
            "missing_info": ["What is the desired outcome?"],
        },
    }


def log_decision(request, action, target, reason, confidence, source, matched_to, dry_run=False):
    if dry_run:
        return
    path = REPO_DIR / "docs" / "ssot" / "ssot.focus.decisions.yml"
    if not path.exists():
        return
    try:
        with open(path) as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return
    items = doc.get("sections", [{}])[0].get("items", [])
    items.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "request": str(request),
        "action": action,
        "target": target,
        "reason": str(reason),
        "confidence": confidence,
        "source": source,
        "matched_to": matched_to,
    })
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)


def _make_recommendation(request, active, quick_wins):
    req = str(request).lower()

    # Step 1: active focus match / continue
    key, it, subtask = _match_active(req, active)
    continue_cues = ("continue", "next", "proceed", "go on")
    if it or not req or any(c in req for c in continue_cues):
        if not it:
            it = active.get("branch") or active.get("shared")
            key = "branch" if active.get("branch") else "shared"
        if it:
            target = it.get("label", "")
            return {
                "action": "continue",
                "target": subtask or target,
                "confidence": "high" if subtask or not req else "medium",
                "reasoning": f"Request matches the active {key} focus '{target}'." if subtask or not req or "focus" in req else "Continuing the active focus.",
                "next_prompt": f"Continue working on '{target}'.",
            }

    # Step 2 & 3: quick win
    q = _match_quick_win(req, quick_wins)
    if q:
        return {
            "action": "quick_win",
            "target": q.get("label", ""),
            "confidence": "high",
            "reasoning": "Request matches a completed quick win or uses a quick-win cue.",
            "next_prompt": f"Add '{q.get('label', '')}' to Quick Wins and complete immediately.",
        }
    if any(cue in req for cue in QUICK_WIN_CUES):
        return {
            "action": "quick_win",
            "target": "quick win",
            "confidence": "medium",
            "reasoning": "Request sounds small and concrete.",
            "next_prompt": "Add a new Quick Win and complete immediately.",
        }

    # Step 4 & 5: backlog
    backlog = _backlog_items()
    match = _match_backlog(req, backlog)
    if match:
        return {
            "action": "triage_backlog",
            "target": match.get("label", ""),
            "confidence": "high",
            "reasoning": "Request matches an existing backlog item.",
            "next_prompt": f"Activate backlog item '{match.get('label', '')}' or add it to the current focus.",
        }
    best = _best_backlog(backlog)
    if best:
        return {
            "action": "triage_backlog",
            "target": best.get("label", ""),
            "confidence": "medium",
            "reasoning": "No active or quick-win match; the highest-scoring backlog item is the best next focus.",
            "next_prompt": f"Consider activating backlog item '{best.get('label', '')}'.",
        }

    # Step 6: inbox
    inbox = _inbox_items()
    best_inbox = _best_inbox(inbox)
    if best_inbox:
        return {
            "action": "triage_inbox",
            "target": best_inbox.get("label", ""),
            "confidence": "medium",
            "reasoning": "No active, quick-win, or backlog match; an unprocessed inbox item is available.",
            "next_prompt": f"Review and potentially activate inbox item '{best_inbox.get('label', '')}'.",
        }

    # Step 7: draft inbox
    draft = _draft_inbox(request)
    return {
        "action": "draft_inbox",
        "target": draft["focus"]["label"],
        "confidence": "low",
        "reasoning": "No existing match; a new inbox draft should be reviewed.",
        "next_prompt": "Review the draft inbox item below before saving.",
        "suggestion": draft,
    }


def mcp_focus(request=None, mode="recommend"):
    if not CURRENT.exists():
        return {"ok": False, "error": "ssot.focus.current.yml not found"}

    doc = _load_current()
    active, quick_wins = _active_items(doc)

    if mode == "status":
        return {"ok": True, "active": active, "quick_wins": quick_wins}

    if not request:
        recommendation = _make_recommendation("", active, quick_wins)
    else:
        recommendation = _make_recommendation(request, active, quick_wins)

    matched_to = recommendation.get("target", "")
    log_decision(request or "", recommendation["action"], matched_to, recommendation["reasoning"], recommendation["confidence"], "mcp_focus", matched_to)

    return {
        "ok": True,
        "active": active,
        "quick_wins": quick_wins,
        "recommendation": recommendation,
    }
