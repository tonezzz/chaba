#!/usr/bin/env python3
"""Probe Managed Agents (Interactions API) on the Gemini free tier.

Synthetic tasks only. No repo, host, key, billing or gateway changes.
Env: GEMINI_API_KEY, AGENT, OUT.
"""
import json
import os
import signal
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

AGENT = os.environ.get("AGENT", "antigravity-preview-09-2026")
OUT = os.environ.get("OUT", "/tmp/opencode/g4-managed-agents-eval.json")
KEY = os.environ["GEMINI_API_KEY"]
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
results = {}
context = {}


class CallTimeout(Exception):
    pass


def _alarm(_signum, _frame):
    raise CallTimeout("per-task timeout (300s)")


signal.signal(signal.SIGALRM, _alarm)


def save_partial(complete=False):
    with open(OUT, "w") as f:
        json.dump({
            "schema": "g4-managed-agents-eval",
            "schema_version": 1,
            "date": datetime.now(timezone.utc).isoformat(),
            "host": "idc03",
            "agent": AGENT,
            "key_env": "GEMINI_API_KEY_MICHAEL (free tier)",
            "key_printed": False,
            "endpoint": ENDPOINT,
            "results": results,
            "complete": complete,
        }, f, indent=2)


def call(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": KEY},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=290) as resp:
        return json.loads(resp.read().decode("utf-8"))


def summarize(interaction):
    u = interaction.get("usage") or {}
    steps = interaction.get("steps") or []
    tool_steps = []
    for s in steps:
        if s.get("type") not in ("model_output", "thought"):
            tool_steps.append({
                "type": s.get("type"),
                "keys": sorted(s.keys()),
                "result": str(s.get("result") or "")[:800],
            })
    # Raw REST POST responses do not carry the SDK-only `output_text` field;
    # derive the answer from model_output steps instead.
    text = "".join(
        c.get("text", "")
        for s in steps if s.get("type") == "model_output"
        for c in (s.get("content") or []) if c.get("type") == "text"
    )
    return {
        "interaction_id": interaction.get("id"),
        "status": interaction.get("status"),
        "output_text": text[:800],
        "environment_id": interaction.get("environment_id"),
        "service_tier": interaction.get("service_tier"),
        "step_types": [s.get("type") for s in steps],
        "tool_steps": tool_steps,
        "usage": u,
        "input_tokens": u.get("total_input_tokens"),
        "output_tokens": u.get("total_output_tokens"),
        "thought_tokens": u.get("total_thought_tokens"),
    }


def record(name, fn):
    t0 = time.monotonic()
    signal.alarm(300)
    try:
        out = fn() or {}
        results[name] = {"ok": True, "elapsed_s": round(time.monotonic() - t0, 2), **out}
    except Exception as e:
        results[name] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:500]}",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    finally:
        signal.alarm(0)
        save_partial()
    r = results[name]
    print(name, "OK" if r["ok"] else "FAIL",
          str(r.get("error", ""))[:200], "elapsed", r["elapsed_s"], flush=True)


def fresh_sandbox():
    r = call({
        "agent": AGENT,
        "input": [{"type": "text", "text": (
            "In the sandbox, use Python code execution to write the exact string "
            "ADA-MA-OK-42 to /workspace/ada-proof.txt, then read the file back. "
            "Reply with only the file contents."
        )}],
        "environment": "remote",
    })
    out = summarize(r)
    context["env1"] = out["environment_id"]
    context["int1"] = out["interaction_id"]
    out["grade_file_created"] = "ADA-MA-OK-42" in out["output_text"]
    return out


def reuse_sandbox():
    if not context.get("env1") or not context.get("int1"):
        return {"error": "no environment_id/interaction_id from fresh_sandbox"}
    r = call({
        "agent": AGENT,
        "input": [{"type": "text", "text": (
            "Use Python code execution to append the exact text -REUSED to "
            "/workspace/ada-proof.txt, then read the file back. Reply with only "
            "the file contents."
        )}],
        "environment": context["env1"],
        "previous_interaction_id": context["int1"],
    })
    out = summarize(r)
    out["reused_environment_id"] = out["environment_id"] == context["env1"]
    out["grade_persistence"] = "ADA-MA-OK-42-REUSED" in out["output_text"]
    return out


def repo_source_mount():
    r = call({
        "agent": AGENT,
        "input": [{"type": "text", "text": (
            "List the top-level file names in /workspace/spoon-knife. Reply with "
            "only those names separated by commas."
        )}],
        "environment": {
            "type": "remote",
            "sources": [{
                "type": "repository",
                "source": "https://github.com/octocat/Spoon-Knife",
                "target": "/workspace/spoon-knife",
            }],
        },
    })
    out = summarize(r)
    out["grade_repo_listed"] = any(
        name in out["output_text"].lower()
        for name in ("readme", "gitignore", "changed", "test")
    )
    return out


if __name__ == "__main__":
    save_partial()
    record("fresh_sandbox_write_read", fresh_sandbox)
    record("reuse_sandbox", reuse_sandbox)
    record("repo_source_mount", repo_source_mount)
    save_partial(complete=True)
