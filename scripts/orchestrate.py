#!/usr/bin/env python3
"""Generic DAG orchestrator for SSOT-defined workflows."""

import argparse
import json
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import events

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: pip install pyyaml")

SSOT_DIR = REPO / "docs" / "ssot" / "infrastructure"
REPORTS_DIR = REPO / "reports"


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def find_workflow(name):
    path = SSOT_DIR / f"ssot.orchestration.{name}.yml"
    if path.exists():
        return path
    raise FileNotFoundError(f"No workflow SSOT found for {name}")


def topo_sort(steps):
    by_id = {s["id"]: s for s in steps}
    in_degree = {s["id"]: 0 for s in steps}
    adj = {s["id"]: [] for s in steps}
    for s in steps:
        for dep in s.get("depends_on", []):
            if dep in by_id:
                in_degree[s["id"]] += 1
                adj[dep].append(s["id"])
    queue = deque([sid for sid, d in in_degree.items() if d == 0])
    result = []
    while queue:
        sid = queue.popleft()
        result.append(sid)
        for nxt in adj[sid]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    if len(result) != len(steps):
        raise ValueError("Cycle detected in workflow steps")
    return [by_id[sid] for sid in result]


def load_state(state_file):
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state_file, state):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def run_step(step, dry_run=False, timeout=60):
    cmd = step.get("run")
    if not cmd:
        return {"ok": False, "error": "no run command", "rc": -1}
    if dry_run:
        return {"ok": True, "dry_run": True, "cmd": cmd, "rc": 0}
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "cmd": cmd,
            "rc": result.returncode,
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-5000:],
            "duration_ms": round((time.time() - t0) * 1000, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "cmd": cmd, "rc": -1, "error": f"timeout after {timeout}s", "stdout": e.stdout[-5000:] if e.stdout else "", "stderr": e.stderr[-5000:] if e.stderr else "", "duration_ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "cmd": cmd, "rc": -1, "error": str(e), "duration_ms": round((time.time() - t0) * 1000, 1)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", default="overnight", help="Workflow name (SSOT: ssot.orchestration.<name>.yml)")
    parser.add_argument("--dry-run", action="store_true", help="Print planned steps without running")
    parser.add_argument("--force", action="store_true", help="Run all steps even if already completed in state")
    parser.add_argument("--step", help="Run one step and its dependencies")
    args = parser.parse_args()

    ssot = load_yaml(find_workflow(args.workflow))
    workflow = ssot.get("workflow", {})
    steps = ssot.get("steps", [])
    ordered = topo_sort(steps)
    by_id = {s["id"]: s for s in steps}

    state_file = REPORTS_DIR / (workflow.get("state_file", "reports/ORCHESTRATION_STATE.json").lstrip("reports/"))
    report_file = REPORTS_DIR / (workflow.get("report_file", "reports/ORCHESTRATION.json").lstrip("reports/"))
    state = load_state(state_file) if not args.dry_run else {}
    run_id = datetime.now(timezone.utc).isoformat()

    if args.step:
        if args.step not in by_id:
            raise SystemExit(f"Unknown step: {args.step}")
        needed = {args.step}
        queue = [args.step]
        while queue:
            sid = queue.pop()
            for dep in by_id[sid].get("depends_on", []):
                if dep not in needed:
                    needed.add(dep)
                    queue.append(dep)
        ordered = [s for s in ordered if s["id"] in needed]

    results = {}
    report = {
        "workflow": args.workflow,
        "run_id": run_id,
        "dry_run": args.dry_run,
        "steps": [],
    }

    for step in ordered:
        sid = step["id"]
        if not args.force and not args.dry_run and state.get(sid) == "completed":
            results[sid] = {"ok": True, "skipped": True, "state": "completed"}
            continue

        timeout = step.get("timeout", 60)
        if args.dry_run:
            print(f"[dry-run] {sid}: {step.get('run')}")
            result = {"ok": True, "dry_run": True, "cmd": step.get("run")}
        else:
            print(f"[run] {sid}")
            result = run_step(step, timeout=timeout)
            state[sid] = "completed" if result.get("ok") else "failed"
            events.log_event(
                source="orchestrate",
                etype="step_completed" if result.get("ok") else "step_failed",
                severity="info" if result.get("ok") else "error",
                data={"workflow": args.workflow, "step": sid, "rc": result.get("rc"), "duration_ms": result.get("duration_ms")},
            )
            if not result.get("ok") and step.get("on_fail", "abort") == "abort":
                results[sid] = result
                break
        results[sid] = result

    overall = all(r.get("ok") or r.get("skipped") for r in results.values())

    if not args.dry_run:
        save_state(state_file, state)
        report["steps"] = [
            {
                "id": sid,
                "name": by_id.get(sid, {}).get("name", sid),
                **res,
            }
            for sid, res in results.items()
        ]
        report["ok"] = overall
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"Workflow {args.workflow}: {len(results)} step(s), ok={overall}")
    if not overall and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
