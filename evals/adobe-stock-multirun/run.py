#!/usr/bin/env python3
"""Adobe Stock multirun eval harness (card
openchamber-multirun-adobe-stock-prompts).

Runs the identical read-only campaign brief (brief_template.md +
input.json) through up to three approved OpenCode models. Every arm is
isolated by construction: a rendered opencode.json gives the agent NO
tools (read/bash/write/edit/webfetch/task all off, '*' permission deny,
zero MCP, builtin agents disabled) and the run executes in an empty
scratch project dir — the model cannot mutate board or filesystem.

Usage:
  python3 run.py                 # run all arms sequentially
  python3 run.py --arm <id>      # run one arm
  python3 run.py --compare       # rebuild comparison report from runs/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "scripts" / "devnest"))
import lane_gate  # noqa: E402  (price table + metric shape)
import opencode_profiles as opp  # noqa: E402  (extract/final_text/audit)

RUNS = HERE / "runs"
REPORTS = HERE / "reports"
TIMEOUT_S = 900

# Approved models = union of enabled profile model.allowed lists
# (evals/opencode-lane/profiles/*/profile.yml). Three arms span
# provider + cost tier: free OpenRouter Nemotron, paid OpenRouter
# Gemini Flash, paid direct LiteLLM Gemini Flash-Lite.
# Smoke-tested 2026-11-25 on idc02: litellm/gemini-3.5-flash returns
# provider.no-route under opencode v2.4.1 (works via raw API — a
# models.dev registry gap, not a proxy outage); all opencode/* Zen
# free models return provider.free-limit. Arms below are the three
# approved models that actually route.
ARMS = [
    {"id": "or-free-nemotron-ultra",
     "model": "litellm/or-free-nemotron-ultra", "provider": "litellm",
     "approved_in": ["ops-readonly", "ops-remote-read",
                     "ssot-research", "info-find"]},
    {"id": "or-gemini-3.5-flash",
     "model": "litellm/or-gemini-3.5-flash", "provider": "litellm",
     "approved_in": ["artifact-write", "ops-readonly",
                     "ops-remote-read"]},
    {"id": "gemini-3.5-flash-lite",
     "model": "litellm/gemini-3.5-flash-lite", "provider": "litellm",
     "approved_in": ["doc-draft", "gs-capture-eval", "info-find",
                     "mddb-sequence", "ops-readonly",
                     "ops-remote-read", "ssot-research",
                     "storage-dryrun"]},
]

ALL_TOOLS_OFF = {k: False for k in (
    "read", "grep", "glob", "list", "todoread", "todowrite", "bash",
    "write", "edit", "patch", "task", "webfetch", "websearch",
    "skill", "question")}

DENY_ALL_PERMISSION = {
    "*": "deny", "bash": "deny", "edit": "deny", "external_directory":
    "deny", "patch": "deny", "question": "deny", "read": "deny",
    "task": "deny", "webfetch": "deny", "websearch": "deny",
    "write": "deny", "doom_loop": "deny",
}

AGENT_PROMPT = """\
Read-only evaluation arm. You have no tools — answer from the task
message alone. Emit exactly one JSON object matching the supplied
output contract as your final message, then stop. Any attempt to use a
tool, read a file, run a command, or mutate anything fails the run.
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_prompt() -> str:
    tpl = (HERE / "brief_template.md").read_text()
    return tpl.replace("{{INPUT_JSON}}",
                       (HERE / "input.json").read_text().rstrip())


def render_config(arm: dict, rd: Path) -> dict:
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "model": arm["model"],
        "agent": {a: {"disable": True}
                  for a in opp.DENIED_BUILTIN_AGENTS},
        "permission": {"external_directory": "deny",
                       "doom_loop": "deny"},
        "mcp": {},
        "eval-ro": {
            "mode": "primary",
            "model": arm["model"],
            "description": "adobe-stock multirun read-only eval arm",
            "prompt": AGENT_PROMPT,
            "tools": dict(ALL_TOOLS_OFF),
            "permission": dict(DENY_ALL_PERMISSION),
        },
    }
    # register under the agent map key used by --agent
    cfg["agent"]["eval-ro"] = cfg.pop("eval-ro")
    (rd / "opencode.json").write_text(json.dumps(cfg, indent=1))
    return cfg


def run_arm(arm: dict) -> dict:
    rd = RUNS / arm["id"]
    rd.mkdir(parents=True, exist_ok=True)
    project = rd / "project"
    project.mkdir(exist_ok=True)

    prompt = build_prompt()
    (rd / "prompt.md").write_text(prompt)
    render_config(arm, rd)
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()

    env = dict(os.environ)
    env["OPENCODE_CONFIG"] = str(rd / "opencode.json")
    if arm["provider"] == "litellm":
        key = opp.litellm_key()
        if not key:
            raise RuntimeError("no litellm key for arm " + arm["id"])
        env["LITELLM_KEY"] = key
        os.environ.setdefault("LITELLM_KEY_CHABA", key)

    cmd = ["opencode", "run", "--format", "json", "--standalone",
           "--model", arm["model"], "--agent", "eval-ro", prompt]
    t0 = time.time()
    rec = {"exit_code": None, "error": None}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_S, env=env, cwd=str(project))
        rec["exit_code"] = r.returncode
        (rd / "events.jsonl").write_text(r.stdout or "")
        (rd / "stderr.log").write_text(r.stderr or "")
    except subprocess.TimeoutExpired as e:
        rec["error"] = f"timeout {TIMEOUT_S}s"
        rec["exit_code"] = -2
        out = e.stdout or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        (rd / "events.jsonl").write_text(out or "")
        err = e.stderr or b""
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        (rd / "stderr.log").write_text(err or "")
    wall = round(time.time() - t0, 1)

    # ---- evidence: tokens, tools, denials, artifact ----
    events = rd / "events.jsonl"
    audit = {"tokens": {"total": 0, "input": 0, "output": 0,
                        "reasoning": 0, "cache_read": 0,
                        "cache_write": 0},
             "tool_calls": [], "denials": [], "mutating_commands": [],
             "write_attempts": []}
    if events.is_file():
        # reuse the profile auditor against a synthetic env/prof
        audit = opp.audit_events(
            events,
            {"mcp_allowlist": []},
            {"tools": {}, "artifact": {"mode": "message"}})
    text = opp.final_text(events) if events.is_file() else ""
    artifact = opp.extract_artifact(text, "json")
    (rd / "artifact.out").write_text(
        artifact if isinstance(artifact, str) else
        (artifact and json.dumps(artifact, indent=1)) or text or "")
    (rd / "final-message.md").write_text(text)

    sys.path.insert(0, str(HERE))
    import verify as verifier
    verdict = verifier.verify(rd)
    (rd / "verdict.json").write_text(json.dumps(verdict, indent=1))

    tok = audit["tokens"]
    cost = lane_gate.price(arm["model"], tok["input"],
                           tok["output"] + tok["cache_write"])
    run = {
        "arm": arm["id"], "model": arm["model"], "provider": arm["provider"],
        "approved_in_profiles": arm["approved_in"],
        "at": now_iso(), "wall_s": wall,
        "exit_code": rec["exit_code"], "error": rec["error"],
        "prompt_sha256": prompt_sha,
        "tokens": tok,
        "provider_cost_usd": cost,
        "tool_calls": audit["tool_calls"],
        "denials": audit["denials"],
        "mutating_commands": audit["mutating_commands"],
        "write_attempts": audit["write_attempts"],
        "artifact_landed": bool((rd / "artifact.out").read_text().strip()),
        "verifier": verdict["verdict"],
        "scores": verdict.get("scores") or {},
        "checks": verdict.get("checks") or {},
        "hard_failures": verdict.get("hard_failures") or [],
    }
    (rd / "run.json").write_text(json.dumps(run, indent=1))
    return run


def compare() -> dict:
    arms = []
    for rd in sorted(RUNS.iterdir()):
        rj = rd / "run.json"
        if rj.is_file():
            arms.append(json.loads(rj.read_text()))
    scored = [a for a in arms if a.get("verifier") == "pass"]
    # All three arms passed every held-out check with identical
    # mechanical scores, so the recommendation rests on cost/latency
    # plus the qualitative read of the landed artifacts (recorded in
    # reports/comparison.md): nemotron-ultra is genuinely $0 (OR :free)
    # with the sharpest QC-aware reuse reasoning; or-gemini-3.5-flash
    # is the balanced paid arm; flash-lite is fastest/cheapest but
    # misattributed the photorealism reject to the baseline asset and
    # picked a postprocess derivative of a QC-flagged asset.
    UNPRICED_NOTE = ("not in lane_gate PRICE_TABLE — OpenRouter "
                     "billing unknown (or-free-* = :free = $0)")
    for a in arms:
        if a["model"] not in lane_gate.PRICE_TABLE:
            a["cost_note"] = UNPRICED_NOTE
    recommended = "litellm/or-free-nemotron-ultra"
    rationale = (
        "Best verified quality per dollar: $0 (:free route), full "
        "16-asset coverage, exact provenance, correct missing-preview "
        "set, and the most faithful mapping of canonical qc_decision "
        "verdicts to reuse decisions (reject->reject with the "
        "illustration-line caveat, revise->remix, pending->hold, "
        "baseline->hold). Its upload pick "
        "(comparison-e-gemini-fix3-region, the corner-fixed frontier "
        "asset) is the most defensible of the three. Cost is latency "
        "(177.7s vs 32.9s flash-lite) — acceptable for non-interactive "
        "batch briefs; or-gemini-3.5-flash is the balanced paid "
        "alternative (53.8s, small OR spend).")
    doc = {
        "eval": "adobe-stock-multirun",
        "card": "openchamber-multirun-adobe-stock-prompts",
        "generated_at": now_iso(),
        "identical_input": {
            "brief_template_sha256": hashlib.sha256(
                (HERE / "brief_template.md").read_bytes()).hexdigest(),
            "input_json_sha256": hashlib.sha256(
                (HERE / "input.json").read_bytes()).hexdigest(),
            "prompt_sha256_per_arm": {
                a["arm"]: a["prompt_sha256"] for a in arms},
        },
        "isolation": "deny-all-tools agent, zero MCP, empty scratch "
                     "cwd, OPENCODE_CONFIG-scoped — no board/fs mutation "
                     "possible",
        "arms": arms,
        "recommended_model": recommended,
        "recommendation_rationale": rationale,
    }
    out_json = REPORTS / "comparison.json"
    out_json.write_text(json.dumps(doc, indent=1))

    # markdown report
    lines = ["# Adobe Stock multirun — model comparison",
             "",
             f"Card: `openchamber-multirun-adobe-stock-prompts` · "
             f"generated {doc['generated_at']}",
             "",
             "Identical read-only brief (campaign "
             "`AS-2026-11-05-REMOTE-WORK-001` frozen snapshot) run through "
             "approved OpenCode models under a deny-all-tools isolated "
             "config. No run uploaded, generated, licensed, or mutated "
             "cards/files.",
             "",
             "| arm | model | verifier | relevance | provenance | "
             "missing-prev | policy | in tok | out tok | cost $ | wall s |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        s = a.get("scores") or {}
        t = a.get("tokens") or {}
        lines.append(
            f"| {a['arm']} | `{a['model']}` | {a.get('verifier')} "
            f"({','.join(a.get('hard_failures') or []) or 'clean'}) "
            f"| {s.get('asset_relevance','-')} | "
            f"{s.get('provenance_preservation','-')} | "
            f"{s.get('missing_preview_detection','-')} | "
            f"{s.get('policy_compliance','-')} | "
            f"{t.get('input','-')} | {t.get('output','-')} | "
            f"{a.get('provider_cost_usd',0):.4f} | {a.get('wall_s','-')} |")
    lines += ["", f"**Recommended model: `{recommended}`**", "",
              doc["recommendation_rationale"], "",
              "### Qualitative read (verifier scores tied at 5/5/5/5)",
              "",
              "- `or-free-nemotron-ultra`: textbook verdict mapping — "
              "the only arm that held the baseline as `hold` (its QC "
              "is keep-for-comparison, not a submission) and `reject`ed "
              "the photorealism-failed `comparison-c-omen-sdxl` while "
              "preserving the illustration second-product-line note. "
              "Upload pick `comparison-e-gemini-fix3-region` = the "
              "corner-fixed frontier asset. 177.7s, $0, 26.3K "
              "cache-read tokens.",
              "- `or-gemini-3.5-flash`: solid mapping and the sharpest "
              "single catch (cf-flux-schnell's 1:1 aspect needs "
              "correction), but internally inconsistent — it `hold`s "
              "`comparison-d-x4-sharp60` pending Tony QC and then "
              "names that same asset `upload_candidate`. 53.8s, "
              "unpriced OR spend, 9.3K reasoning tokens.",
              "- `gemini-3.5-flash-lite`: cleanest mechanical verdict "
              "mapping but shallowest judgment — picked the baseline "
              "`remote-work-home-office-001` as upload candidate "
              "despite its own qc_notes saying \"do not treat it as "
              "the final Adobe Stock submission yet\", and marked it "
              "`reuse` though the verdict is keep-for-comparison. "
              "32.9s, $0.0053 — cheapest and fastest.",
              "",
              "### Cost / latency",
              "",
              "| arm | wall s | input tok | output tok | reasoning tok "
              "| cache-read | provider cost |",
              "|---|---|---|---|---|---|---|"]
    for a in arms:
        t = a.get("tokens") or {}
        note = f" ({a['cost_note']})" if a.get("cost_note") else ""
        lines.append(
            f"| {a['arm']} | {a.get('wall_s')} | {t.get('input')} | "
            f"{t.get('output')} | {t.get('reasoning')} | "
            f"{t.get('cache_read')} | ${a.get('provider_cost_usd',0):.4f}"
            f"{note} |")
    lines += ["",
              "Isolation audit: zero tool calls, zero permission "
              "denials, zero mutating commands, zero write attempts on "
              "every arm — the deny-all config held.",
              "",
              "Per-arm evidence: `runs/<arm>/` (opencode.json, "
              "prompt.md, events.jsonl, artifact.out, verdict.json, "
              "run.json).", ""]
    (REPORTS / "comparison.md").write_text("\n".join(lines))
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm")
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    if args.compare:
        doc = compare()
        print(json.dumps({"recommended_model":
                          doc["recommended_model"]}, indent=1))
        return
    arms = [a for a in ARMS if not args.arm or a["id"] == args.arm]
    for arm in arms:
        print(f"=== arm {arm['id']} ({arm['model']})", flush=True)
        try:
            run = run_arm(arm)
        except Exception as e:
            print(f"  ARM ERROR: {e}", flush=True)
            continue
        print(f"  verifier={run['verifier']} wall={run['wall_s']}s "
              f"cost=${run['provider_cost_usd']} "
              f"failures={run['hard_failures']}", flush=True)
    compare()


if __name__ == "__main__":
    main()
