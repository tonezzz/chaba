#!/usr/bin/env python3
"""One Managed Agents repo-source probe in background mode, then poll via GET.

Synthetic public repo only. Env: GEMINI_API_KEY, AGENT, OUT.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

AGENT = os.environ.get("AGENT", "antigravity-preview-09-2026")
OUT = os.environ.get("OUT", "/tmp/opencode/g4-ma-repo-bg.json")
KEY = os.environ["GEMINI_API_KEY"]
BASE = "https://generativelanguage.googleapis.com/v1beta/interactions"


def post(payload):
    req = urllib.request.Request(
        BASE, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": KEY},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get(iid):
    req = urllib.request.Request(
        f"{BASE}/{iid}", method="GET", headers={"x-goog-api-key": KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


out = {
    "schema": "g4-ma-repo-bg",
    "date": datetime.now(timezone.utc).isoformat(),
    "host": "idc03",
    "agent": AGENT,
    "key_env": "GEMINI_API_KEY_MICHAEL (free tier)",
    "key_printed": False,
    "mode": "background POST + GET polling",
}

try:
    r = post({
        "agent": AGENT,
        "input": [{"type": "text", "text": (
            "List the top-level file names in /workspace/spoon-knife. Reply with "
            "only those names separated by commas."
        )}],
        "background": True,
        "environment": {
            "type": "remote",
            "sources": [{
                "type": "repository",
                "source": "https://github.com/octocat/Spoon-Knife",
                "target": "/workspace/spoon-knife",
            }],
        },
    })
    iid = r.get("id")
    out["interaction_id"] = iid
    out["initial_status"] = r.get("status")
    out["environment_id"] = r.get("environment_id")
    statuses = [r.get("status")]
    t0 = time.monotonic()
    while time.monotonic() - t0 < 540:
        time.sleep(10)
        g = get(iid)
        st = g.get("status")
        statuses.append(st)
        if st not in ("in_progress", "queued", "requires_action"):
            break
    out["statuses"] = statuses
    out["terminal_status"] = statuses[-1]
    out["elapsed_s"] = round(time.monotonic() - t0, 2)
    steps = g.get("steps") or []
    out["step_types"] = [s.get("type") for s in steps]
    out["step_results"] = [
        {"type": s.get("type"),
         "result": str(s.get("result"))[:1200],
         "content": json.dumps(s.get("content"))[:1200]}
        for s in steps
    ]
    out["usage"] = g.get("usage")
    blob = " ".join(str(s.get("result") or "") + json.dumps(s.get("content") or "")
                    for s in steps).lower()
    out["grade_repo_listed"] = any(
        name in blob for name in ("readme", "gitignore", "changed", "test"))
except Exception as e:
    out["ok"] = False
    out["error"] = f"{type(e).__name__}: {str(e)[:500]}"
else:
    out["ok"] = out.get("grade_repo_listed", False)

with open(OUT, "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: out[k] for k in ("ok", "terminal_status", "elapsed_s", "grade_repo_listed", "error") if k in out}, indent=2))
