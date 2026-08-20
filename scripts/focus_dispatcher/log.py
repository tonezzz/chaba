"""Logging helpers for focus decisions, technical decisions, and session summaries."""
from datetime import datetime

import yaml

from .state import DECISIONS, SESSIONS, TECHNICAL


def log_decision(request, action, target, reason, confidence, source, matched_to, dry_run=False):
    if dry_run:
        return
    if not DECISIONS.exists():
        return
    try:
        with open(DECISIONS) as f:
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
    with open(DECISIONS, "w") as f:
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
