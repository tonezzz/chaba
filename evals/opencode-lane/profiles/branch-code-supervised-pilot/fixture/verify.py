#!/usr/bin/env python3
"""Schema-floor verifier for branch-code. The profile is disabled in
this card, so this only ever validates shape — a run that produced an
artifact still must have tests_run > 0 and a review_ref (independent
review is the point of the profile)."""
import json
import os
import sys
from pathlib import Path


def verify(run_dir):
    rd = Path(run_dir)
    try:
        a = json.loads((rd / "artifact.out").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}
    req = ("task", "branch", "worktree", "files_changed", "tests_run",
           "tests_passed", "review_ref", "artifact_complete")
    checks = {f"field:{k}": k in a for k in req}
    checks["tests actually ran"] = isinstance(
        a.get("tests_run"), int) and a.get("tests_run", 0) > 0
    checks["tests all passed"] = (
        a.get("tests_passed") == a.get("tests_run"))
    checks["review ref present"] = bool(a.get("review_ref"))
    checks["artifact complete"] = a.get("artifact_complete") is True
    verdict = "pass" if all(v is True for v in checks.values()) \
        else "fail"
    return {"verdict": verdict, "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
