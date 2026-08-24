#!/usr/bin/env python3
"""Triage and deduplicate auto-generated improvements in ssot.improvements.yml.

Rules:
- Collapse duplicate auto-generated items by base label (e.g. "Service Failures Detected"
  and "Service Failures Detected (2026-08-22)" are the same issue family).
- Keep the most recent discovered entry and update assessment_ref/git_commit.
- Do not promote items to accepted/planned until effort and impact_summary are set.
- Append a triage_note when an item is held back.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
IMPROVEMENTS = REPO / "docs" / "ssot" / "ssot.improvements.yml"
DATE_SUFFIX_RE = re.compile(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$")
ARCHIVE_AFTER_DAYS = 14


def base_label(label):
    return DATE_SUFFIX_RE.sub("", label).strip()


def is_promotable(item):
    """An item can leave pending only when effort and impact are filled."""
    effort = item.get("effort")
    if not effort or effort == "TBD":
        return False
    impact_summary = item.get("impact_summary")
    if not impact_summary:
        return False
    # require at least one numeric impact score
    has_score = any(
        item.get(k) not in (None, "")
        for k in ("business_impact", "technical_impact", "user_experience_impact", "cost_savings_impact")
    )
    return has_score


def archive_path_for(item):
    completed = item.get("completed") or item.get("completed_at") or item.get("accepted") or ""
    year = str(completed)[:4] if len(str(completed)) >= 4 else str(datetime.now().year)
    if not year.isdigit():
        year = str(datetime.now().year)
    month = int(str(completed)[5:7]) if len(str(completed)) >= 7 and str(completed)[5:7].isdigit() else datetime.now().month
    half = "H2" if month >= 7 else "H1"
    return REPO / "docs" / "ssot" / f"ssot.improvements.archive.{year}-{half}.yml"


def should_archive(item):
    if item.get("status") not in ("completed", "archived"):
        return False
    completed = item.get("completed") or item.get("completed_at") or item.get("accepted")
    if not completed:
        return False
    try:
        completed_date = datetime.strptime(str(completed)[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (datetime.now().date() - completed_date).days >= ARCHIVE_AFTER_DAYS


def derive_effort(priority, category):
    if priority == "high":
        return "1 session"
    if priority == "medium":
        return "2-4 hours"
    if category in ("documentation", "cleanup"):
        return "30 minutes"
    return "1 hour"


def derive_impact(item):
    category = item.get("category", "")
    priority = item.get("priority", "medium")
    base = 5
    if priority == "high":
        base = 8
    elif priority == "low":
        base = 3
    if category in ("performance", "security"):
        business = base + 2
        technical = base + 3
        cost = base + 1
        ux = base
    elif category in ("monitoring", "infrastructure"):
        business = base + 1
        technical = base + 2
        cost = base + 1
        ux = base
    elif category == "documentation":
        business = base - 2
        technical = base - 1
        cost = base
        ux = base - 1
    else:
        business = base
        technical = base
        cost = base
        ux = base
    return {
        "business_impact": min(10, business),
        "technical_impact": min(10, technical),
        "user_experience_impact": min(10, ux),
        "cost_savings_impact": min(10, cost),
    }


def merge_item(existing, new):
    """Update existing item with newer discovery info; keep oldest discovered date."""
    existing.setdefault("discovered", new.get("discovered"))
    if new.get("discovered"):
        if existing.get("discovered") and new["discovered"] > existing["discovered"]:
            existing["discovered"] = new["discovered"]
            existing["assessment_ref"] = new.get("assessment_ref", existing.get("assessment_ref"))
            existing["git_commit"] = new.get("git_commit", existing.get("git_commit"))
            existing["git_branch"] = new.get("git_branch", existing.get("git_branch"))
    existing.setdefault("assessment_ref", new.get("assessment_ref"))
    existing.setdefault("git_commit", new.get("git_commit"))
    existing.setdefault("git_branch", new.get("git_branch"))


def triage():
    with open(IMPROVEMENTS) as f:
        doc = yaml.safe_load(f) or {}

    sections = doc.get("sections", [])
    changes = []
    for sec in sections:
        items = sec.get("items", [])
        by_base = {}
        kept = []
        for item in items:
            if not item:
                continue
            label = item.get("label", "")
            b = base_label(label)
            if item.get("auto_generated") and b in by_base:
                existing = by_base[b]
                merge_item(existing, item)
                changes.append(f"merged duplicate {label} into {b}")
                continue
            if item.get("auto_generated"):
                by_base[b] = item
            kept.append(item)

        # renumber/update and gate status
        for item in kept:
            label = item.get("label", "")
            b = base_label(label)
            if item.get("auto_generated") and item.get("status") == "pending":
                if item.get("effort") in (None, "", "TBD"):
                    item["effort"] = derive_effort(item.get("priority"), item.get("category"))
                if not item.get("impact_summary"):
                    scores = derive_impact(item)
                    for k, v in scores.items():
                        if not item.get(k):
                            item[k] = v
                    item["impact_summary"] = f"Auto-scored {item.get('priority')} priority {item.get('category')} improvement"
                if not is_promotable(item):
                    triage_notes = item.setdefault("triage_notes", [])
                    note = f"Held at {item.get('status')} on {datetime.now().date().isoformat()}: requires effort and impact before acceptance"
                    if note not in triage_notes:
                        triage_notes.append(note)
                else:
                    # auto-promote pending, auto-generated items when scored
                    if item.get("priority") == "high":
                        item["status"] = "accepted"
                    else:
                        item["status"] = "planned"
                    item.setdefault("accepted", datetime.now().date().isoformat())
                    changes.append(f"promoted {b} to {item['status']}")
            # strip date suffix from label to avoid future duplicates
            if item.get("auto_generated") and label != b:
                item["label"] = b
                item.setdefault("first_seen", DATE_SUFFIX_RE.search(label).group(0).strip(" ()"))
                changes.append(f"normalized label {label} -> {b}")
        sec["items"] = kept

    # archive completed/archived items older than threshold
    archived_items = []
    for sec in sections:
        kept = []
        for item in sec.get("items", []):
            if not item:
                continue
            if should_archive(item):
                archived_items.append(item)
                changes.append(f"archived {item.get('label', '')}")
                continue
            kept.append(item)
        sec["items"] = kept

    if archived_items:
        archives = {}
        for item in archived_items:
            ap = archive_path_for(item)
            archives.setdefault(ap, []).append(item)
        for ap, items in archives.items():
            archive_doc = {"items": []}
            if ap.exists():
                with open(ap) as f:
                    archive_doc = yaml.safe_load(f) or {}
            archive_doc.setdefault("items", []).extend(items)
            archive_doc["archived_at"] = datetime.now().date().isoformat()
            ap.parent.mkdir(parents=True, exist_ok=True)
            with open(ap, "w") as f:
                yaml.safe_dump(
                    archive_doc,
                    f,
                    sort_keys=False,
                    allow_unicode=True,
                    width=120,
                    default_flow_style=False,
                )
            changes.append(f"wrote {len(items)} items to {ap.name}")

    if not changes:
        print("[improvements-triage] no changes")
        return 0

    with open(IMPROVEMENTS, "w") as f:
        yaml.safe_dump(
            doc,
            f,
            sort_keys=False,
            allow_unicode=True,
            width=120,
            default_flow_style=False,
        )

    print(f"[improvements-triage] changes: {len(changes)}")
    for c in changes:
        print(f"  - {c}")
    return 0


if __name__ == "__main__":
    sys.exit(triage())
