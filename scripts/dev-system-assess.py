#!/usr/bin/env python3
"""Assess the chaba development system and update SSOT/reports."""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SSOT = REPO / "docs" / "ssot" / "ssot.dev-system.assessment.yml"
REPORTS_DIR = REPO / "reports"

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: pip install pyyaml")


def run(cmd, cwd=None):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, cwd=cwd or REPO).strip()
    except subprocess.CalledProcessError:
        return ""


def count_branches():
    out = run("git for-each-ref --format='%(refname:short)' refs/heads")
    return len([b for b in out.splitlines() if b and b != "master"])


def branches_ahead_of_master():
    out = run("git for-each-ref --format='%(refname:short)' refs/heads")
    ahead = []
    for b in out.splitlines():
        if not b or b == "master":
            continue
        n = run(f"git rev-list --count master..{b}")
        if n and int(n) > 0:
            ahead.append({"branch": b, "commits_ahead": int(n)})
    return ahead


def count_worktrees():
    out = run("git worktree list")
    return len([l for l in out.splitlines() if l.strip()])


def count_untracked():
    out = run("git status --short")
    return len([l for l in out.splitlines() if l.strip().startswith('??')])


def count_active_foci():
    active = REPO / "docs" / "ssot" / "ssot.focus.current.active.yml"
    if not active.exists():
        return 0
    with open(active) as f:
        data = yaml.safe_load(f) or {}
    n = 0
    for section in data.get("sections", []):
        for item in section.get("items", []):
            if item.get("status") in ("active", "parked"):
                n += 1
    return n


def load_report_json(name):
    path = REPORTS_DIR / name
    if not path.exists():
        return {}
    with open(path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def load_ssot():
    if not SSOT.exists():
        return {}
    with open(SSOT) as f:
        return yaml.safe_load(f) or {}


def save_ssot(data):
    SSOT.parent.mkdir(parents=True, exist_ok=True)
    with open(SSOT, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def trend(old_score, new_score):
    if not old_score:
        return "stable"
    if new_score["ssot_warnings"] > 0 or new_score["service_errors_last_night"] > 0:
        return "declining"
    if new_score["branches_ahead_of_master"] < old_score.get("branches_ahead_of_master", 0):
        return "improving"
    if new_score["branches_ahead_of_master"] > old_score.get("branches_ahead_of_master", 0):
        return "declining"
    return "stable"


def build_assessment(check_only=False, metrics_only=False):
    old = load_ssot()
    score = old.get("score", {})
    ahead = branches_ahead_of_master()
    ssot_metrics = load_report_json("SSOT_OPTIMIZATION_METRICS.json")
    service_errors = load_report_json("SERVICE_ERRORS.json")

    new_score = {
        "branches_total": count_branches(),
        "branches_ahead_of_master": len(ahead),
        "worktrees_total": count_worktrees(),
        "active_foci": count_active_foci(),
        "ssot_warnings": (
            ssot_metrics.get("bloat", 0)
            + ssot_metrics.get("data_isolation", 0)
            + ssot_metrics.get("other", 0)
            + ssot_metrics.get("logs", {}).get("issues", 0)
        ),
        "service_errors_last_night": service_errors.get("total_error_occurrences", 0),
        "ci_failures_7d": score.get("ci_failures_7d", 0),
        "untracked_files": count_untracked(),
    }

    cons = []
    if new_score["branches_ahead_of_master"] > 2:
        cons.append({
            "label": "Branch/worktree sprawl",
            "severity": "medium" if new_score["branches_ahead_of_master"] <= 5 else "high",
            "evidence": f"{new_score['branches_ahead_of_master']} branches are ahead of master; {new_score['worktrees_total']} worktrees active",
            "owner": "tony",
            "status": "open",
            "improvement": "Consolidate long-tail branches into master and archive or delete merged branches",
        })
    if new_score["ssot_warnings"] > 0:
        cons.append({
            "label": "SSOT quality regression",
            "severity": "high",
            "evidence": f"{new_score['ssot_warnings']} SSOT optimization warning(s)",
            "owner": "tony",
            "status": "open",
            "improvement": "Fix SSOT bloat, data-isolation, or log-reference warnings",
        })
    if new_score["service_errors_last_night"] > 0:
        cons.append({
            "label": "Service log errors",
            "severity": "high",
            "evidence": f"{new_score['service_errors_last_night']} error occurrence(s) in the last overnight sweep",
            "owner": "tony",
            "status": "open",
            "improvement": "Triage reports/SERVICE_ERRORS.md and restart or fix affected services",
        })
    if new_score["untracked_files"] > 0:
        cons.append({
            "label": "Uncommitted working tree",
            "severity": "medium",
            "evidence": f"{new_score['untracked_files']} untracked or modified file(s)",
            "owner": "tony",
            "status": "open",
            "improvement": "Commit or .gitignore outstanding changes before the next session",
        })

    next_review = (date.today() + timedelta(days=1)).isoformat()
    if old.get("next_review"):
        try:
            old_next = date.fromisoformat(old["next_review"])
            if old_next > date.today():
                next_review = old["next_review"]
        except ValueError:
            pass

    assessment = {
        "title": "Development System Assessment",
        "subtitle": "Periodic assessment of the chaba development workflow itself",
        "icon": "clipboard-check",
        "last_reviewed": datetime.now(timezone.utc).isoformat(),
        "reviewer": "assistant",
        "score": new_score,
        "trend": trend(old.get("score", {}), new_score),
        "pros": old.get("pros", []),
        "cons": cons if cons else [{"label": "No active cons", "severity": "none", "evidence": "All tracked metrics are within thresholds", "owner": "tony", "status": "resolved", "improvement": "Keep monitoring"}],
        "improvements": old.get("improvements", []),
        "next_review": next_review,
    }

    if not check_only:
        save_ssot(assessment)
    if not check_only or metrics_only:
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "DEV_SYSTEM_ASSESSMENT.json").write_text(json.dumps(assessment, indent=2, default=str), encoding="utf-8")
        md = [f"# {assessment['title']}", f"**Reviewed:** {assessment['last_reviewed']}  ", f"**Trend:** {assessment['trend']}", ""]
        md.append("## Score")
        for k, v in new_score.items():
            md.append(f"- {k}: {v}")
        md.append("")
        md.append("## Cons")
        for c in assessment["cons"]:
            md.append(f"- **{c['label']}** ({c['severity']}): {c['evidence']}")
        md.append("")
        md.append("## Improvements")
        for i in assessment["improvements"]:
            md.append(f"- {i['label']} [{i.get('status', 'not_started')}]: {i.get('target_score', '')}")
        (REPORTS_DIR / "DEV_SYSTEM_ASSESSMENT.md").write_text("\n".join(md), encoding="utf-8")

    return assessment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if any metric is outside thresholds or review is overdue")
    parser.add_argument("--metrics-only", action="store_true", help="Only produce reports/DEV_SYSTEM_ASSESSMENT.json, do not overwrite SSOT")
    args = parser.parse_args()

    assessment = build_assessment(check_only=args.check, metrics_only=args.metrics_only)
    score = assessment["score"]
    failures = []
    if score["ssot_warnings"] > 0:
        failures.append(f"SSOT warnings: {score['ssot_warnings']}")
    if score["service_errors_last_night"] > 0:
        failures.append(f"Service errors: {score['service_errors_last_night']}")
    if score["branches_ahead_of_master"] > 10:
        failures.append(f"Too many branches ahead: {score['branches_ahead_of_master']}")
    if score["untracked_files"] > 0:
        failures.append(f"Untracked files: {score['untracked_files']}")
    try:
        if date.fromisoformat(assessment["next_review"]) < date.today():
            failures.append(f"Review overdue: {assessment['next_review']}")
    except ValueError:
        pass

    print(f"dev-system: branches={score['branches_total']} ahead={score['branches_ahead_of_master']} worktrees={score['worktrees_total']} foci={score['active_foci']} ssot_warnings={score['ssot_warnings']} errors={score['service_errors_last_night']} untracked={score['untracked_files']}")
    if failures:
        print("FAIL: " + "; ".join(failures))
        if args.check:
            sys.exit(1)
    else:
        print("OK: dev-system assessment within thresholds")


if __name__ == "__main__":
    main()
