"""MCP Focus session-start router."""
from datetime import datetime
from pathlib import Path
import yaml
from .config import REPO_DIR


REPO = REPO_DIR
CURRENT = REPO / "docs" / "ssot" / "ssot.focus.current.yml"
FOCUS = REPO / "docs" / "ssot" / "ssot.focus.yml"
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"
DECISIONS = REPO / "docs" / "ssot" / "ssot.focus.decisions.yml"
TECHNICAL = REPO / "docs" / "ssot" / "decisions" / "ssot.technical-decisions.yml"
SESSIONS = REPO / "docs" / "ssot" / "ssot.focus.sessions.yml"

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
    quick_wins = []
    hand_off_queue = []
    for sec in doc.get("sections", []):
        if sec.get("title") == "Quick Wins":
            quick_wins = [i for i in sec.get("items", [])]
        elif sec.get("title") == "Hand-off Queue":
            hand_off_queue = [i for i in sec.get("items", [])]
        elif sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not item or item.get("status") != "active":
                    continue
                section = sec.get("title")
                if section == "Active Shared Focus":
                    active["shared"] = item
                else:
                    active["branch"] = item
    return active, quick_wins, hand_off_queue


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
    now = datetime.now()
    label = f"{action}: {target} ({now.strftime('%Y-%m-%d %H:%M:%S')})"[:120]
    items.append({
        "label": label,
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


def log_technical_decision(decision, dry_run=False):
    if dry_run:
        return
    if not TECHNICAL.exists():
        return
    try:
        with open(TECHNICAL) as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return
    decisions = doc.setdefault("decisions", [])
    decision.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
    decisions.append(decision)
    with open(TECHNICAL, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def log_session_summary(summary, dry_run=False):
    if dry_run:
        return
    if not SESSIONS.exists():
        return
    try:
        with open(SESSIONS) as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return
    sessions = doc.setdefault("sessions", [])
    summary.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
    sessions.append(summary)
    with open(SESSIONS, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def _historical_items():
    doc = _load_focus()
    sections = doc.get("sections", [])
    historical = []
    for sec in sections:
        if "History" in sec.get("title", "") or sec.get("title") == "Archived - Focus History":
            historical.extend(sec.get("items", []))
    return historical


def _decision_tree_cases():
    doc = _load_current()
    tree = doc.get("decision_tree", {}) or {}
    return tree.get("cases", []) if isinstance(tree, dict) else tree


def _decision_log():
    if not DECISIONS.exists():
        return []
    try:
        with open(DECISIONS) as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return []
    return doc.get("sections", [{}])[0].get("items", [])


def _pre_action_summary(request):
    doc = _load_current()
    active, quick_wins, hand_off_queue = _active_items(doc)
    req = str(request).lower()

    duplicate_active = []
    for key in ("shared", "branch"):
        it = active.get(key)
        if it and (not req or any(part in it.get("label", "").lower() for part in req.split())):
            duplicate_active.append(f"{key}: {it.get('label', '')}")

    similar_historical = []
    for h in _historical_items():
        text = " ".join([
            h.get("label", ""),
            h.get("text", ""),
            " ".join(str(t) for t in h.get("tags", []))
        ]).lower()
        if not req or any(part in text for part in req.split()):
            similar_historical.append({
                "label": h.get("label", ""),
                "date": str(h.get("date", "")),
                "outcome": h.get("outcome", "")[:120]
            })

    related_cases = []
    for case in _decision_tree_cases():
        case_text = " ".join([
            str(case.get("case", "")),
            str(case.get("condition", "")),
            str(case.get("action", "")),
        ]).lower()
        if not req or any(part in case_text for part in req.split()):
            related_cases.append({
                "case": case.get("case", ""),
                "condition": case.get("condition", "")[:120],
                "action": case.get("action", "")[:120],
            })

    related_decisions = []
    for d in _decision_log():
        decision_text = " ".join([
            str(d.get("request", "")),
            str(d.get("action", "")),
            str(d.get("reason", "")),
        ]).lower()
        if not req or any(part in decision_text for part in req.split()):
            related_decisions.append({
                "date": str(d.get("date", "")),
                "action": d.get("action", ""),
                "target": d.get("target", "")[:120]
            })

    return {
        "request": request,
        "active_foci": active,
        "hand_off_queue": hand_off_queue,
        "duplicate_active_matches": duplicate_active,
        "similar_historical": similar_historical[:5],
        "related_decision_tree_cases": related_cases[:5],
        "related_decision_log": related_decisions[:5],
        "ready_to_proceed": not duplicate_active and not similar_historical,
    }


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


def mcp_focus(request=None, mode="recommend", decision=None, summary=None):
    if mode == "technical_decision":
        if not decision:
            return {"ok": False, "error": "decision is required for technical_decision mode"}
        log_technical_decision(decision)
        return {"ok": True, "action": "logged", "target": decision.get("id", "")}

    if mode == "session_summary":
        if not summary:
            return {"ok": False, "error": "summary is required for session_summary mode"}
        log_session_summary(summary)
        return {"ok": True, "action": "logged", "focus": summary.get("focus", "")}

    if not CURRENT.exists():
        return {"ok": False, "error": "ssot.focus.current.yml not found"}

    doc = _load_current()
    active, quick_wins, hand_off_queue = _active_items(doc)

    if mode == "status":
        return {"ok": True, "active": active, "quick_wins": quick_wins, "hand_off_queue": hand_off_queue}

    if mode == "pre_action":
        return {
            "ok": True,
            "pre_action_summary": _pre_action_summary(request or ""),
        }

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
        "hand_off_queue": hand_off_queue,
        "recommendation": recommendation,
    }
