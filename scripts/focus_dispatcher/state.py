"""Focus dispatcher state, paths, and helpers."""
import yaml

from . import REPO

CURRENT = REPO / "docs" / "ssot" / "ssot.focus.current.yml"
FOCUS = REPO / "docs" / "ssot" / "ssot.focus.yml"
DECISIONS = REPO / "docs" / "ssot" / "ssot.focus.decisions.yml"
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"
PROCESSED_DIR = INBOX_DIR / "processed"
REPORTS_DIR = REPO / "reports"
NEXT_FOCUS_MD = REPORTS_DIR / "NEXT_FOCUS.md"
SUBAGENT_CONTRACT_MD = REPORTS_DIR / "SUBAGENT_CONTRACT.md"

PRIORITY = {"high": 3, "medium": 2, "low": 1}


def is_active(item):
    status = item.get("status", "")
    return status in ("active", "in_progress", "not_started")


def is_parked(item):
    return item.get("status", "") == "parked"


def is_completed(item):
    return item.get("status", "") == "completed"


def incomplete_subtasks(item):
    return [s for s in item.get("subtasks", []) if s.get("status") != "completed"]


def load_current():
    with open(CURRENT) as f:
        return yaml.safe_load(f)


def load_focus():
    with open(FOCUS) as f:
        return yaml.safe_load(f)


def save_current(doc):
    with open(CURRENT, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def save_focus(doc):
    with open(FOCUS, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def find_section(sections, title):
    for sec in sections:
        if sec.get("title") == title:
            return sec
    return None


def validate_current(doc=None):
    if doc is None:
        doc = load_current()
    validation = doc.get("validation", {})
    limits = {
        "Active Shared Focus": validation.get("max_active_shared_focus", 1),
        "Active Branch Focus": validation.get("max_active_branch_focus", 1),
    }
    for section_title, limit in limits.items():
        sec = find_section(doc.get("sections", []), section_title)
        if sec is None:
            continue
        active_count = sum(1 for it in sec.get("items", []) if is_active(it))
        if active_count > limit:
            labels = ", ".join(it.get("label", "?") for it in sec.get("items", []) if is_active(it))
            raise RuntimeError(f"{section_title} has {active_count} active items (limit {limit}): {labels}")
    return True
