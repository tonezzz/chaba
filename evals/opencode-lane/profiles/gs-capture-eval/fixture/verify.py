#!/usr/bin/env python3
"""Held-out verifier for the gs-capture-eval profile fixture. Re-runs
the deterministic image-set evaluator on the declared image_dir and
compares the agent's artifact against fresh ground truth — never trusts
the agent's narrative."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
EVAL_SCRIPT = REPO / "scripts" / "gs" / "image_set_eval.py"

REQ = ("dataset", "image_count", "same_dimensions", "duplicate_groups",
       "min_sharpness", "sharpness_median", "recommendation",
       "read_only", "tools_used")


def _fresh(image_dir):
    try:
        out = subprocess.run(
            [sys.executable, str(EVAL_SCRIPT), image_dir],
            capture_output=True, text=True, timeout=300, cwd=str(REPO))
        return json.loads(out.stdout)
    except Exception as e:
        return {"error": str(e)}


def verify(run_dir):
    rd = Path(run_dir)
    checks = {}
    try:
        man = json.loads((rd / "manifest.json").read_text())
        a = json.loads((rd / "artifact.out").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}
    env = man.get("envelope") or {}

    checks["required fields"] = all(k in a for k in REQ)
    checks["read_only true"] = a.get("read_only") is True
    checks["tools_used non-empty"] = bool(a.get("tools_used"))
    checks["dataset matches envelope task"] = (
        str(a.get("dataset") or "") in str(env.get("task") or ""))

    image_dir = None
    task = str(env.get("task") or "")
    for tok in task.replace(",", " ").split():
        if tok.startswith("/") and Path(tok).is_dir():
            image_dir = tok
            break
    checks["image_dir found in task"] = image_dir is not None

    if image_dir:
        fresh = _fresh(image_dir)
        if "error" in fresh:
            checks["fresh eval ran"] = False
        else:
            checks["fresh eval ran"] = True
            checks["image_count matches"] = (
                a.get("image_count") == fresh.get("images"))
            checks["same_dimensions matches"] = (
                a.get("same_dimensions")
                == (fresh.get("gates") or {}).get("same_dimensions"))
            checks["duplicate_groups matches"] = (
                a.get("duplicate_groups")
                == (fresh.get("gates") or {}).get("duplicate_groups"))
            checks["recommendation matches"] = (
                a.get("recommendation") == fresh.get("recommendation"))
            try:
                checks["min_sharpness within 0.5"] = abs(
                    float(a.get("min_sharpness"))
                    - float((fresh.get("gates") or {})
                            .get("min_sharpness"))) <= 0.5
            except Exception:
                checks["min_sharpness within 0.5"] = False

    checks["mcp tools only"] = all(
        str(t).startswith(("inspect_image_set", "match_views",
                           "propose_foreground_masks",
                           "score_capture_manifest", "compare_gs_runs"))
        for t in (a.get("tools_used") or []))

    verdict = "pass" if checks and all(v is True for v in checks.values()) \
        else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": (env.get("artifact") or {}).get("path", "?")}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
