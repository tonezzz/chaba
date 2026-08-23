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
