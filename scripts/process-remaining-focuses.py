#!/usr/bin/env python3
"""Process remaining focus items (parked, backlog, inbox, auto-improvements) and produce a plan."""
import os
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from mcp_debug.focus import _load_current, _load_focus, _make_recommendation, _active_items  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FOCUS_INBOX = REPO / "docs" / "ssot" / "focus-inbox"
REPORT = REPO / "reports" / "REMAINING_FOCUS_PLAN.md"


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _pending_improvements():
    doc = _load_yaml(REPO / "docs" / "ssot" / "ssot.improvements.yml")
    items = []
    for section in doc.get("sections", []):
        for item in section.get("items", []):
            if item.get("status") == "pending":
                items.append({
                    "source": "ssot.improvements.yml",
                    "label": item.get("label", ""),
                    "text": item.get("text", "").replace("\n", " ")[:200],
                    "priority": item.get("priority", "medium"),
                })
    return items


def _unprocessed_inbox():
    items = []
    if not FOCUS_INBOX.is_dir():
        return items
    for p in sorted(FOCUS_INBOX.glob("*.yml")):
        if p.name.startswith("TEMPLATE") or p.name == "processed":
            continue
        doc = _load_yaml(p)
        if doc.get("status") in ("draft", "unprocessed", "pending"):
            items.append({
                "source": f"focus-inbox/{p.name}",
                "label": doc.get("label", p.stem),
                "text": (doc.get("text") or doc.get("description") or "").replace("\n", " ")[:200],
                "priority": doc.get("priority", "medium"),
            })
    return items


def main():
    current = _load_current()
    focus = _load_focus()
    active, quick_wins = _active_items(current)

    # Collect all remaining items
    remaining = []

    # Active focus subtasks
    for section in current.get("sections", []):
        for item in section.get("items", []):
            if item.get("status") == "active":
                for sub in item.get("subtasks", []):
                    if sub.get("status") == "not_started":
                        remaining.append({
                            "source": "ssot.focus.current.yml active subtask",
                            "label": sub["label"],
                            "text": sub["label"],
                            "priority": item.get("priority", "medium"),
                        })

    # Parked
    for section in current.get("sections", []):
        for item in section.get("items", []):
            if item.get("status") == "parked":
                remaining.append({
                    "source": "ssot.focus.current.yml parked",
                    "label": item["label"],
                    "text": (item.get("text") or "").replace("\n", " ")[:200],
                    "priority": item.get("priority", "medium"),
                })

    # Backlog
    for section in focus.get("sections", []):
        if section.get("title") == "Backlog - Triage Queue":
            for item in section.get("items", []):
                if item.get("status") == "pending":
                    remaining.append({
                        "source": "ssot.focus.yml backlog",
                        "label": item["label"],
                        "text": (item.get("text") or "").replace("\n", " ")[:200],
                        "priority": item.get("priority", "medium"),
                    })

    # Improvements
    remaining.extend(_pending_improvements())

    # Inbox drafts
    remaining.extend(_unprocessed_inbox())

    # Decide on each
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Remaining Focus Plan\n\n"]
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n\n")
    lines.append("| Source | Label | Priority | mcp_focus action | Target | Confidence |\n")
    lines.append("|---|---|---|---|---|---|\n")

    for r in remaining:
        request = f"{r['label']}: {r['text']}".strip()
        rec = _make_recommendation(request, active, quick_wins)
        lines.append(
            f"| {r['source']} | {r['label'][:60]} | {r['priority']} | "
            f"{rec['action']} | {rec.get('target','')[:40]} | {rec.get('confidence','')} |\n"
        )

    with open(REPORT, "w") as f:
        f.writelines(lines)

    print(f"[process-remaining-focuses] processed {len(remaining)} items")
    print(f"[process-remaining-focuses] wrote {REPORT}")
    return 0


if __name__ == "__main__":
    from datetime import datetime
    sys.exit(main())
