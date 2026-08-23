"""Prompt / command preprocessor for context and precision.

Read-only v1 prototype. Loads active focus, backlog, quick wins, and inbox,
then resolves an ambiguous user request into a structured, grounded prompt.

Usage:
    python scripts/prompt_preprocessor.py "promt preprocessor"
"""
import difflib
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ACTIVE = REPO / "docs" / "ssot" / "ssot.focus.current.active.yml"
BACKLOG = REPO / "docs" / "ssot" / "ssot.focus.current.backlog.yml"
FOCUS = REPO / "docs" / "ssot" / "ssot.focus.yml"
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"
JOBS_DIR = REPO / "docs" / "ssot" / "jobs"

# Lightweight alias and cue expansion
ALIASES = {
    "promt": "prompt",
    "preproc": "preprocessor",
    "preprocesor": "preprocessor",
    "/preprocessor": "preprocessor",
    "mcpfocus": "mcp focus",
    "mcp-focus": "mcp focus",
    "focussys": "focus system",
    "audit": "infrastructure audit",
    "realsetup": "real infrastructure",
    "next": "next",
    "do this": "do this",
}

# Command patterns and canonicalization suggestions for mcp_debug / mcp_raw
COMMAND_PATTERNS = {
    re.compile(r"^\s*mcp_raw\s+"):
        "mcp_raw",
    re.compile(r"^\s*mcp_debug\s+"):
        "mcp_debug",
    re.compile(r"^\s*git\s+"):
        "git",
    re.compile(r"^\s*ssh\s+"):
        "ssh",
    re.compile(r"^\s*docker\s+"):
        "docker",
    re.compile(r"^\s*systemctl\s+"):
        "systemctl",
    re.compile(r"^\s*journalctl\s+"):
        "journalctl",
    re.compile(r"^\s*curl\s+"):
        "curl",
    re.compile(r"^\s*python\s+"):
        "python",
    re.compile(r"^\s*node\s+"):
        "node",
}


def _norm(text):
    return re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).split()


def _expand_tokens(tokens):
    expanded = []
    for t in tokens:
        if t in ALIASES:
            expanded.extend(_norm(ALIASES[t]))
        else:
            expanded.append(t)
    return expanded


def _load_yaml(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _active_items(doc):
    items = []
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Active Shared Focus", "Active Branch Focus"):
            for it in sec.get("items", []):
                if it and it.get("label"):
                    it["_source"] = "ssot.focus.current.active.yml"
                    it["_why"] = sec.get("title", "").lower()
                    items.append(it)
    return items


def _quick_wins(doc):
    wins = []
    for sec in doc.get("sections", []):
        if sec.get("title") == "Quick Wins":
            for it in sec.get("items", []):
                if it and it.get("label"):
                    it["_source"] = "ssot.focus.current.backlog.yml"
                    it["_why"] = "quick_win"
                    wins.append(it)
    return wins


def _backlog_items(doc):
    items = []
    for sec in doc.get("sections", []):
        if sec.get("title") in ("Backlog - Triage Queue", "Backlog"):
            for it in sec.get("items", []):
                if it and it.get("label") and it.get("status") not in ("completed", "archived"):
                    it["_source"] = "ssot.focus.yml"
                    it["_why"] = "backlog"
                    items.append(it)
    return items


def _inbox_items():
    items = []
    if not INBOX_DIR.is_dir():
        return items
    for p in sorted(INBOX_DIR.glob("*.yml")):
        if p.name.startswith("TEMPLATE"):
            continue
        doc = _load_yaml(p)
        focus = doc.get("focus") or doc
        if focus and focus.get("label"):
            focus["_source"] = f"docs/ssot/focus-inbox/inbox/{p.name}"
            focus["_why"] = "inbox"
            items.append(focus)
    return items


def _job_items():
    items = []
    if not JOBS_DIR.is_dir():
        return items
    for p in sorted(JOBS_DIR.rglob("*.yml")):
        try:
            doc = _load_yaml(p)
        except Exception:
            continue
        title = doc.get("title") or doc.get("label")
        if not title:
            continue
        it = {
            "label": title,
            "text": (doc.get("planning", {}).get("goal")) or doc.get("subtitle", ""),
            "_source": str(p.relative_to(REPO)),
            "_why": "job",
        }
        items.append(it)
    return items


def _score(item, tokens):
    label_tokens = _expand_tokens(_norm(item.get("label", "")))
    text_tokens = _expand_tokens(_norm(item.get("text", "")))
    all_tokens = set(label_tokens + text_tokens)
    if not all_tokens:
        return 0.0

    # token overlap
    matched = sum(1 for t in tokens if t in all_tokens)
    overlap = matched / max(len(tokens), 1)

    # fuzzy label match
    label = item.get("label", "").lower()
    query = " ".join(tokens)
    fuzzy = difflib.SequenceMatcher(None, query, label).ratio()

    # exact keyword in label
    exact = any(t in label for t in tokens if len(t) > 3)
    bonus = 0.15 if exact else 0.0

    return round(overlap * 0.6 + fuzzy * 0.4 + bonus, 3)


def _detect_command(request):
    for pattern, tool in COMMAND_PATTERNS.items():
        if pattern.search(request):
            return {
                "tool": tool,
                "canonical_request": request.strip(),
                "note": f"Request looks like a {tool} command. Consider dispatch through mcp_debug/mcp_raw after SSOT policy check.",
            }
    return None


def preprocess(request):
    if not request or not request.strip():
        return {"ok": False, "error": "request is required"}

    # Cue expansion
    raw_tokens = _norm(request)
    tokens = _expand_tokens(raw_tokens)

    command_info = _detect_command(request)

    active = _load_yaml(ACTIVE)
    backlog = _load_yaml(BACKLOG)
    focus = _load_yaml(FOCUS)

    candidates = (
        _active_items(active)
        + _quick_wins(backlog)
        + _backlog_items(focus)
        + _inbox_items()
        + _job_items()
    )

    scored = []
    for item in candidates:
        s = _score(item, tokens)
        if s > 0.0:
            scored.append({"score": s, "item": item})

    scored.sort(key=lambda x: x["score"], reverse=True)

    if not scored:
        return {
            "ok": True,
            "request": request,
            "canonical_request": request,
            "confidence": 0.0,
            "suggested_action": "inbox",
            "reason": "No matching focus, backlog, or job found.",
            "grounding": {},
            "command": command_info,
            "similar_items": [],
        }

    best = scored[0]
    item = best["item"]
    confidence = best["score"]

    if command_info:
        action = "direct"
        canonical = (
            f"Dispatch canonical command via {command_info['tool']}: "
            f"{command_info['canonical_request']}"
        )
    else:
        why = item.get("_why", "backlog")
        if why in ("active shared focus", "active branch focus"):
            action = "continue_focus"
        elif why == "quick_win":
            action = "quick_win"
        elif why == "backlog":
            action = "backlog"
        elif why == "inbox":
            action = "inbox"
        elif why == "job":
            action = "continue_job"
        else:
            action = "direct"

        canonical = (
            f"Continue work on '{item.get('label')}' ({why}): "
            f"{item.get('text', '').strip().splitlines()[0] if item.get('text') else 'No summary'}"
        )

    grounding = {
        "source": item.get("_source", ""),
        "label": item.get("label", ""),
        "status": item.get("status", ""),
        "priority": item.get("priority", ""),
        "branch": item.get("branch", ""),
    }

    similar = [
        {
            "label": x["item"].get("label"),
            "score": x["score"],
            "source": x["item"].get("_source"),
            "why": x["item"].get("_why"),
        }
        for x in scored[1:4]
    ]

    return {
        "ok": True,
        "request": request,
        "canonical_request": canonical,
        "confidence": confidence,
        "suggested_action": action,
        "grounding": grounding,
        "command": command_info,
        "similar_items": similar,
    }


if __name__ == "__main__":
    req = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    print(json.dumps(preprocess(req), indent=2, ensure_ascii=False))
