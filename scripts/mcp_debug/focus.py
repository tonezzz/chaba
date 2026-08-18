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


def _save_current(doc):
    with open(CURRENT, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def _save_focus(doc):
    with open(FOCUS, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def _load_focus():
    with open(FOCUS) as f:
        return yaml.safe_load(f)


def _active_items(doc):
    active = {}
    quick_wins = []
    hand_off_queue = []
    ready_safe = []
    for sec in doc.get("sections", []):
        title = sec.get("title", "")
        if title == "Quick Wins":
            quick_wins = [i for i in sec.get("items", [])]
        elif title == "Hand-off Queue":
            hand_off_queue = [i for i in sec.get("items", [])]
        elif title == "Ready (Safe)":
            ready_safe = [i for i in sec.get("items", [])]
        elif title in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not item or item.get("status") != "active":
                    continue
                section = sec.get("title")
                if section == "Active Shared Focus":
                    active["shared"] = item
                else:
                    active["branch"] = item
    return active, quick_wins, hand_off_queue, ready_safe


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


def _sweep_candidates(doc, active, backlog, inbox):
    candidates = []
    seen = set()
    # Current sections (active and parked)
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if not item or not item.get("label"):
                    continue
                seen.add(item.get("label"))
                candidates.append({
                    "label": item.get("label"),
                    "text": item.get("text", ""),
                    "status": item.get("status"),
                    "priority": item.get("priority", "medium"),
                    "branch": item.get("branch"),
                    "score": _triage_score(item),
                    "source": item.get("source", "ssot.focus.current.yml"),
                    "why": "current " + sec.get("title", "").lower().replace(" focus", ""),
                })
    # Backlog + parked
    for item in backlog:
        label = item.get("label")
        if not label or label in seen:
            continue
        seen.add(label)
        candidates.append({
            "label": label,
            "text": item.get("text", ""),
            "status": item.get("status"),
            "priority": item.get("priority", "medium"),
            "branch": item.get("branch"),
            "score": _triage_score(item),
            "source": item.get("source", "ssot.focus.yml"),
            "why": "backlog" if item.get("status") not in ("parked",) else "parked",
        })
    # Inbox (not yet processed)
    for item in inbox:
        label = item.get("label")
        if not label or label in seen:
            continue
        seen.add(label)
        candidates.append({
            "label": label,
            "text": item.get("text", ""),
            "status": item.get("status", "pending"),
            "priority": item.get("priority", "medium"),
            "branch": item.get("branch"),
            "score": _triage_score(item),
            "source": str(item.get("__file", "")),
            "why": "inbox",
        })
    # Active focus deferred subtasks
    for key in ("branch", "shared"):
        it = active.get(key)
        if not it:
            continue
        for st in it.get("subtasks", []):
            if st.get("status") == "deferred":
                label = st.get("label", "")
                if label and label not in seen:
                    seen.add(label)
                    candidates.append({
                        "label": label,
                        "text": it.get("text", ""),
                        "status": "deferred",
                        "priority": it.get("priority", "medium"),
                        "branch": it.get("branch"),
                        "score": _triage_score(it),
                        "source": it.get("source", ""),
                        "why": f"deferred subtask of {it.get('label')}",
                    })
    candidates.sort(key=lambda x: (x["score"], _priority_value(x), x["label"]), reverse=True)
    return candidates


def _resolve_session(session_map, candidate, bulk_session):
    if not session_map:
        return bulk_session
    if isinstance(session_map, str):
        return session_map
    label = candidate.get("label", "")
    branch = candidate.get("branch", "")
    return session_map.get(label) or session_map.get(branch) or session_map.get("default") or bulk_session


def _sweep_summary(hold, process_queue):
    hold_label = hold.get("label", "(no active focus)") if hold else "(no active focus)"
    lines = [
        f"Hold: {hold_label}",
        f"Queue: {len(process_queue)} focus(es) to process",
    ]
    if process_queue:
        lines.append("")
    for i, c in enumerate(process_queue, 1):
        session = c.get("deferred_session") or "-"
        lines.append(f"{i}. {c['label']} ({c.get('status')}, {c.get('branch', 'no branch')}, session: {session})")
    return "\n".join(lines)


def _session_groups(active, backlog, inbox, current_doc=None):
    groups = {}
    def add(label, session, why, status):
        if not session:
            return
        if session not in groups:
            groups[session] = []
        groups[session].append({"label": label, "status": status, "why": why})

    # Active/parked in current + deferred subtasks
    for key in ("branch", "shared"):
        it = active.get(key)
        if not it:
            continue
        # whole focus deferred
        d = it.get("deferred") or {}
        add(it.get("label"), d.get("to_session"), "focus", it.get("status"))
        # subtasks
        for st in it.get("subtasks", []):
            if st.get("status") == "deferred":
                add(st.get("label"), st.get("resume_session"), f"subtask of {it.get('label')}", "deferred")

    # Parked in current sections (when no active)
    if current_doc is None:
        current_doc = _load_current()
    for sec in current_doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for it in sec.get("items", []):
                if not it:
                    continue
                d = it.get("deferred") or {}
                add(it.get("label"), d.get("to_session"), f"current {it.get('status')}", it.get("status"))
                for st in it.get("subtasks", []):
                    if st.get("status") == "deferred":
                        add(st.get("label"), st.get("resume_session"), f"subtask of {it.get('label')}", "deferred")

    # Backlog
    for item in backlog:
        d = item.get("deferred") or {}
        add(item.get("label"), d.get("to_session"), "backlog", item.get("status"))
    # Inbox
    for item in inbox:
        add(item.get("label"), item.get("deferred_session"), "inbox", item.get("status", "pending"))
    return groups


def _bulk_defer(candidates, hold_label, session_map, bulk_session, reason):
    today = datetime.now().strftime("%Y-%m-%d")
    changed = []
    # Load focus doc once for backlog edits
    focus_doc = _load_focus()
    focus_section = _find_section(focus_doc.get("sections", []), "Backlog - Triage Queue")
    current_doc = _load_current()

    for c in candidates:
        if hold_label and c["label"].lower() == hold_label:
            continue
        source = c.get("source", "")
        if not source:
            continue
        session = _resolve_session(session_map, c, bulk_session)

        # Focus-inbox file (not already processed/moved)
        if "focus-inbox" in source and "processed" not in source:
            p = Path(source)
            if p.exists():
                doc = yaml.safe_load(p.read_text()) or {}
                focus = doc.get("focus") or doc
                focus["status"] = "deferred"
                focus["deferred_at"] = today
                focus["deferred_session"] = session
                focus["deferred_reason"] = reason
                if "focus" in doc:
                    doc["focus"] = focus
                else:
                    doc = focus
                with open(p, "w") as f:
                    yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)
                changed.append({"label": c["label"], "to": "deferred", "session": session, "file": str(p)})
            continue

        # Backlog in ssot.focus.yml
        if "ssot.focus.yml" in source:
            for item in focus_section.get("items", []):
                if item and item.get("label") == c["label"]:
                    prev = item.get("status")
                    if prev == "parked":
                        prev = item.get("previous_status", prev)
                    item["status"] = "parked"
                    item["parked"] = today
                    item["previous_status"] = prev
                    item["deferred"] = {
                        "to_session": session,
                        "reason": reason,
                    }
                    changed.append({"label": c["label"], "to": "parked in backlog", "session": session})
            continue

        # Active/ parked in ssot.focus.current.yml
        for sec in current_doc.get("sections", []):
            if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
                for item in sec.get("items", []):
                    if item and item.get("label") == c["label"]:
                        prev = item.get("status")
                        if prev == "parked":
                            prev = item.get("previous_status", prev)
                        item["status"] = "parked"
                        item["parked"] = today
                        item["previous_status"] = prev
                        item["deferred"] = {
                            "to_session": session,
                            "reason": reason,
                        }
                        changed.append({"label": c["label"], "to": "parked in current", "session": session})

    _save_focus(focus_doc)
    _save_current(current_doc)
    return changed


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


def _active_branches(active):
    branches = set()
    for it in active.values():
        if it:
            branches.add(it.get("branch", ""))
    return branches


def _is_safe_to_parallel(item, active):
    if not item:
        return False, "empty item"
    safe = item.get("safe_to_parallel")
    if safe is False:
        return False, "explicitly marked not safe"
    if safe is True:
        return True, "explicitly marked safe"
    # criteria-based check
    if item.get("missing_info"):
        return False, "missing_info not empty"
    if item.get("subagent", {}).get("requires_approval"):
        return False, "requires user approval"
    triage = item.get("triage", {})
    try:
        complication = float(triage.get("complication", 10))
    except (TypeError, ValueError):
        complication = 10
    if complication > 4:
        return False, "complication above 4"
    item_branch = item.get("branch", "")
    if item_branch in _active_branches(active) and item_branch:
        return False, "branch conflicts with active focus"
    return True, "meets safe-to-parallel criteria"


def _best_safe_focus(active, backlog, inbox):
    candidates = []
    for item in backlog + inbox:
        is_safe, reason = _is_safe_to_parallel(item, active)
        if not is_safe:
            continue
        item["reason"] = reason
        item["source"] = "backlog" if item in backlog else "inbox"
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda i: (_triage_score(i), _priority_value(i), i.get("started", "")))


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
    active, quick_wins, hand_off_queue, ready_safe = _active_items(doc)
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


def _find_current_active_item(doc):
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for item in sec.get("items", []):
                if item and item.get("status") == "active":
                    return item
    return None


def _defer_active_focus(doc, resume_session, reason):
    item = _find_current_active_item(doc)
    if not item:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    # Prefer the in_progress subtask, otherwise the first not_started subtask
    target_subtask = None
    for st in item.get("subtasks", []):
        if st.get("status") == "in_progress":
            target_subtask = st
            break
    if not target_subtask:
        for st in item.get("subtasks", []):
            if st.get("status") == "not_started":
                target_subtask = st
                break
    if target_subtask:
        target_subtask["status"] = "deferred"
        target_subtask["deferred_at"] = today
        if resume_session:
            target_subtask["resume_session"] = resume_session
        if reason:
            target_subtask["resume_note"] = reason
    else:
        item["status"] = "parked"
        item["parked"] = today
        item["deferred"] = {
            "to_session": resume_session or "",
            "reason": reason or "",
        }
    return item, target_subtask


def _resume_suggestion():
    sessions = _load_sessions()
    candidates = []
    for s in sessions.get("sessions", []):
        next_action = s.get("next_action", [])
        if not next_action:
            continue
        if isinstance(next_action, str):
            next_action = [next_action]
        for action in next_action:
            if isinstance(action, str) and ("resume" in action.lower() or "continue" in action.lower()):
                candidates.append({
                    "focus": s.get("focus"),
                    "date": s.get("date"),
                    "next_action": action,
                    "plan": s.get("plan", []),
                })
    return candidates


def _load_sessions():
    if not SESSIONS.exists():
        return {}
    try:
        with open(SESSIONS) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def mcp_focus(request=None, mode="recommend", decision=None, summary=None, resume_session=None, reason=None, hold=None, bulk_session=None, session_map=None):
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
    active, quick_wins, hand_off_queue, ready_safe = _active_items(doc)

    if mode == "status":
        return {
            "ok": True,
            "active": active,
            "quick_wins": quick_wins,
            "hand_off_queue": hand_off_queue,
            "ready_safe": ready_safe,
            "session_groups": _session_groups(active, _backlog_items(), _inbox_items(), doc),
        }

    if mode == "safe_next":
        best = _best_safe_focus(active, backlog=_backlog_items(), inbox=_inbox_items())
        if not best:
            return {"ok": True, "ready_safe": ready_safe, "recommendation": None, "reason": "No safe-to-parallel focus found."}
        return {
            "ok": True,
            "ready_safe": ready_safe,
            "recommendation": {
                "action": "safe_next",
                "target": best.get("label", ""),
                "source": best.get("source", ""),
                "confidence": "medium",
                "reasoning": best.get("reason", "Highest-scoring safe focus available to run in parallel."),
                "next_prompt": f"Activate safe focus '{best.get('label', '')}' in the Ready (Safe) lane.",
            },
        }

    if mode == "ready_queue":
        return {"ok": True, "ready_safe": ready_safe}

    if mode == "defer":
        item, subtask = _defer_active_focus(doc, resume_session or request or "", reason or request or "")
        if not item:
            return {"ok": False, "error": "no active focus to defer"}
        _save_current(doc)
        focus_label = item.get("label", "")
        subtask_label = subtask.get("label", "") if subtask else ""
        log_session_summary({
            "focus": focus_label,
            "source": "mcp_focus defer",
            "plan": [f"Defer {subtask_label or focus_label}"],
            "done": [],
            "follow_up": [],
            "next_action": [f"Resume {focus_label}"],
        })
        return {
            "ok": True,
            "action": "deferred",
            "focus": focus_label,
            "subtask": subtask_label,
            "resume_session": resume_session or request or "",
            "reason": reason or request or "",
        }

    if mode == "resume":
        candidates = _resume_suggestion()
        if resume_session:
            resume_session = resume_session.strip().lower()
            candidates = [c for c in candidates if resume_session in c.get("next_action", "").lower()]
        if not candidates:
            return {"ok": True, "candidates": [], "recommendation": None, "reason": f"No resume candidates found for session '{resume_session}'."}
        best = candidates[-1]
        return {
            "ok": True,
            "candidates": candidates,
            "recommendation": {
                "action": "resume",
                "target": best.get("focus"),
                "confidence": "medium",
                "reasoning": f"Latest session for '{best.get('focus')}' has a resume next_action.",
                "next_prompt": f"Reactivate focus '{best.get('focus')}' to continue.",
            },
        }

    if mode == "sweep":
        candidates = _sweep_candidates(doc, active, _backlog_items(), _inbox_items())
        hold_label = (hold or "").strip().lower()
        # default hold to the active branch focus if not specified unless explicitly none
        use_default_hold = hold is None
        if hold is not None and hold_label in ("", "__none__", "none"):
            use_default_hold = False
            hold_label = ""
        if use_default_hold and active.get("branch"):
            hold_label = active["branch"].get("label", "").lower()
        hold_item = None
        process_queue = []
        for c in candidates:
            if hold_label and c["label"].lower() == hold_label:
                hold_item = c
            else:
                process_queue.append(c)
        if not hold_item and active.get("branch") and hold_label:
            hold_item = {"label": active["branch"].get("label"), "status": "active", "why": "active branch focus"}

        deferred = []
        if bulk_session or session_map:
            deferred = _bulk_defer(process_queue, hold_label, session_map, bulk_session, reason or "Bulk defer via mcp_focus sweep")
            plan = ([f"Hold {hold_item.get('label', '')}"] if hold_item else ["No hold; defer all"]) + [f"Defer {d['label']} to {d.get('session', bulk_session)}" for d in deferred]
            log_session_summary({
                "focus": hold_item.get("label", "") if hold_item else "sweep",
                "source": "mcp_focus sweep bulk defer",
                "plan": plan,
                "done": [],
                "follow_up": ["Re-assess process queue after bulk defer"],
                "next_action": [f"Continue {hold_item.get('label', '')}"] if hold_item else ["Activate next focus from queue"],
            })

        for c in process_queue:
            c["deferred_session"] = _resolve_session(session_map, c, bulk_session) if (bulk_session or session_map) else "-"
        return {
            "ok": True,
            "hold": hold_item,
            "candidates": candidates,
            "process_queue": process_queue,
            "deferred": deferred,
            "summary": _sweep_summary(hold_item, process_queue),
            "recommendation": {
                "action": "sweep",
                "target": hold_item.get("label") if hold_item else None,
                "confidence": "medium",
                "reasoning": f"Hold '{hold_item.get('label') if hold_item else 'none'}' and process {len(process_queue)} remaining focuses/parked/backlog items." if hold_item else f"No hold; process/defer all {len(process_queue)} remaining focuses.",
                "next_prompt": f"Review the {len(process_queue)} items in process_queue. Activate the first, or defer them all to specific sessions." if not (bulk_session or session_map) else f"Bulk-deferred {len(deferred)} items to their assigned sessions. {'Continue ' + hold_item.get('label', '') if hold_item else 'No active focus; activate one from the queue when ready.'}",
            },
        }

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
        "ready_safe": ready_safe,
        "recommendation": recommendation,
    }
