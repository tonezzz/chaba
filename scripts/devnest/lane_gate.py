#!/usr/bin/env python3
"""Graduated OpenCode routing gate — stages S0..S5.

This is the fail-closed admission controller + metrics ledger for the
graduated OpenCode routing procedure (card
opencode-graduated-routing-standard). Every job that wants the OpenCode
lane presents a YAML *envelope*; the gate either admits it into the
current stage or denies it with explicit reasons. Nothing in this file
executes a job itself except `s0-run`, which delegates execution to
shadow_eval's isolated-worktree arm runner.

Stages (promotion is via `promote-review`, never automatic):

    S0  shadow/replay on the frozen evals/shadow fixtures only —
        paired arms (l0/opencode[/devin]), isolated worktrees, nothing
        production-visible.
    S1  supervised read-only report canary — ONE runner, requires
        OPENCODE_LANES=1 in the environment and concurrency=1, a human
        watches the run.
    S2  five-job read-only pilot — every artifact is independently
        verified by Devin (verifier.type=independent_devin).
    S3  10-20 job sampled production-read-only lane — read-only tasks
        against real hosts, concurrency cap, Telegram summaries.
    S4  reversible artifact writes — rollback must be a real mechanism
        (git-revert/file-restore), write scope limited to allowed_paths.
    S5  branch/code tasks — worktree-only, requires a strong-tier model
        and a held-out + independent verifier.
    production/destructive/secret/deploy classes are NEVER admitted —
    they route to human/Devin regardless of stage.

Fail-closed deny reasons: kill_switch, missing_envelope_field,
denied_class, wrong_stage, class_not_in_stage, wrong_host,
missing_verifier, denied_tool, denied_path, env_gate, quota_exceeded,
stale_heartbeat, failed_provider, concurrency_cap, missing_rollback,
weak_model, weak_verifier. Post-run failure reasons: missing_artifact,
unverified_exit, tool_denial, timeout, executor_error.

Layout:
    evals/opencode-lane/jobs/*.yaml        committed envelope library
    lane state dir (per-host, STABLE across checkouts — resolved as
        $OPENCODE_LANE_STATE, else
        ${XDG_STATE_HOME:-~/.local/state}/opencode-lane/):
        stage.json        current stage + promotion history + review_due
        metrics.jsonl     per-job metric ledger
        KILLED            kill-switch marker (presence = lane dead)
        inflight/<id>.json  concurrency markers
        heartbeat-<id>.json freshness markers
        AUD-0950: this used to live at evals/opencode-lane/state/
        inside the checkout — dispatch worktree deletion destroyed the
        S0 ledger. A surviving legacy dir is migrated once on first use.
    evals/opencode-lane/reports/           committed review reports;
        each review JSON embeds the stage ledger records so the
        verified-job aggregate stays re-derivable even if the state
        dir is lost again.

Subcommands:
    lint <job.yaml>         envelope validation only
    admit <job.yaml>        full fail-closed decision (JSON)
    s0-run <job.yaml>       admit + execute fixture arm(s) + verify + record
    stage                   print stage state
    review                  weekly promotion review -> report + recommendation
    promote                 apply a 'promote' recommendation from review
    demote <S>              operator rollback to an earlier stage
    restore <S> --from-review <review.json>
                            rebuild stage.json after state loss — only
                            accepts a committed review whose decision
                            promotes to <S>
    kill --reason R         engage kill switch (all admits deny)
    resume                  lift kill switch (records history)
    begin|end <job_id>      inflight markers (concurrency cap)
    heartbeat <job_id>      freshness marker for supervised jobs
    record <metric.json>    append a metric record to the ledger
    metrics [--stage S]     aggregate report from the ledger
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANE = REPO / "evals" / "opencode-lane"
JOBS = LANE / "jobs"
REPORTS = LANE / "reports"
PROFILES = LANE / "profiles"    # task-scoped agent profiles
                                # (opencode-task-agent-profiles)
LEGACY_STATE = LANE / "state"   # pre-AUD-0950 per-checkout location


def state_dir() -> Path:
    """Lane state dir — per-host and stable across checkouts.

    Resolved as $OPENCODE_LANE_STATE, else
    ${XDG_STATE_HOME:-~/.local/state}/opencode-lane. State lived inside
    the checkout until AUD-0950 showed dispatch worktree deletion
    destroys the ledger and every fresh worktree silently re-inits at
    S0; a surviving legacy repo-local dir is migrated once."""
    env = os.environ.get("OPENCODE_LANE_STATE")
    if env:
        return Path(env)
    base = Path(os.environ.get("XDG_STATE_HOME")
                or Path.home() / ".local" / "state")
    d = base / "opencode-lane"
    if not d.exists() and LEGACY_STATE.is_dir():
        try:
            shutil.copytree(LEGACY_STATE, d)
        except Exception:
            return LEGACY_STATE   # can't migrate — keep working in place
    return d


def stage_file() -> Path:
    return state_dir() / "stage.json"


def ledger_file() -> Path:
    return state_dir() / "metrics.jsonl"


def kill_file() -> Path:
    return state_dir() / "KILLED"


def inflight_dir() -> Path:
    return state_dir() / "inflight"

# import the shadow harness without duplicating its machinery
_spec = importlib.util.spec_from_file_location(
    "shadow_eval", REPO / "scripts" / "devnest" / "shadow_eval.py")
shadow_eval = importlib.util.module_from_spec(_spec)
sys.modules["shadow_eval"] = _spec
_spec.loader.exec_module(shadow_eval)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------- stage book

TASK_CLASSES = ["shadow_replay", "report", "read_only",
                "artifact_write", "branch_code"]
# never admitted to the OpenCode lane at any stage — human/Devin only
DENIED_CLASSES = ["production", "destructive", "deploy", "secret",
                  "payment", "credential"]

# MCP tools the lane may ever request. Anything outside this set denies
# as denied_tool. S4/S5 add no MCP tools — writes go through declared
# allowed_paths, not MCP.
READONLY_MCP_TOOLS = [
    "mcp_debug", "mcp_health", "mcp_get_file", "mcp_read_ssot",
    "mcp_search_ssot", "mcp_ssot_query", "mcp_ssot_get", "mcp_mddb_doc",
]

# models permitted for S5 branch/code work — strong tier only
STRONG_MODELS = [
    "litellm/claude-fable-5.1", "litellm/gemini-3-pro",
    "litellm/gpt-5.2-codex", "openrouter/anthropic/claude-fable-5.1",
]

# rough $/1M-token {input, output} planning rates — used only to roll
# provider cost into combined_cost; 0.0 = unpriced/free
PRICE_TABLE = {
    "litellm/gemini-3.5-flash-lite": (0.10, 0.40),
    "litellm/gemini-3-flash": (0.30, 2.50),
    "litellm/claude-fable-5.1": (10.0, 50.0),
    "opencode/deepseek-v4.1-flash-free": (0.0, 0.0),
    "ollama/qwen2.5:7b-instruct": (0.0, 0.0),
}
HUMAN_MIN_RATE_USD = 1.0   # planning rate for intervention minutes

# roots the lane is ever allowed to write under, by stage. allowed_paths
# in an envelope must each fall inside one of these prefixes.
STAGE_ALLOWED_ROOTS = {
    "S0": ["evals/shadow/task/"],
    "S1": ["evals/opencode-lane/out/", "reports/"],
    "S2": ["evals/opencode-lane/out/", "reports/"],
    "S3": ["evals/opencode-lane/out/", "reports/"],
    "S4": ["evals/opencode-lane/out/", "reports/", "docs/reports/"],
    "S5": ["evals/opencode-lane/out/", "reports/", "docs/", "scripts/",
           "tests/"],
}

STAGES = {
    "S0": {
        "desc": "shadow/replay on frozen fixtures only",
        "classes": ["shadow_replay"],
        "mcp_tools": [],
        "concurrency": 1,
        "quota": None,
        "env_required": {},
        "independent_verifier": False,
        "supervised": False,
        "promote_gate": {
            "min_jobs": 5,
            "min_verified_rate": 0.6,
            "max_tool_denials": 0,
            "max_escalations": None,
            "note": "every fixture replayed on opencode arm; zero "
                    "mutating commands, scope violations, verifier "
                    "peeks; >=60% held-out verifier pass"},
    },
    "S1": {
        "desc": "supervised read-only report canary, one runner",
        "classes": ["report", "read_only"],
        "mcp_tools": READONLY_MCP_TOOLS,
        "concurrency": 1,
        "quota": 3,
        "env_required": {"OPENCODE_LANES": "1"},
        "independent_verifier": False,
        "supervised": True,          # human_minutes must be recorded
        "promote_gate": {
            "min_jobs": 1,
            "min_verified_rate": 1.0,
            "max_tool_denials": 0,
            "max_escalations": 0,
            "note": "canary artifact + verifier pass + human watched"},
    },
    "S2": {
        "desc": "five-job read-only pilot, Devin-verified",
        "classes": ["read_only", "report"],
        "mcp_tools": READONLY_MCP_TOOLS,
        "concurrency": 1,
        "quota": 5,
        "env_required": {"OPENCODE_LANES": "1"},
        "independent_verifier": True,  # verifier.type=independent_devin
        "supervised": False,
        "promote_gate": {
            "min_jobs": 5,
            "min_verified_rate": 1.0,
            "max_tool_denials": 0,
            "max_escalations": None,
            "note": "5/5 artifacts landed AND independently verified"},
    },
    "S3": {
        "desc": "sampled production read-only lane + Telegram summaries",
        "classes": ["read_only", "report"],
        "mcp_tools": READONLY_MCP_TOOLS,
        "concurrency": 2,
        "quota": 20,
        "env_required": {"OPENCODE_LANES": "1"},
        "independent_verifier": False,
        "supervised": False,
        "promote_gate": {
            "min_jobs": 10,
            "min_verified_rate": 0.8,
            "max_tool_denials": 0,
            "max_escalations": None,
            "note": ">=80% verified over 10-20 sampled jobs"},
    },
    "S4": {
        "desc": "reversible artifact writes",
        "classes": ["read_only", "report", "artifact_write"],
        "mcp_tools": READONLY_MCP_TOOLS,
        "concurrency": 2,
        "quota": None,
        "env_required": {"OPENCODE_LANES": "1"},
        "independent_verifier": False,
        "supervised": False,
        "promote_gate": {
            "min_jobs": 5,
            "min_verified_rate": 1.0,
            "max_tool_denials": 0,
            "max_escalations": None,
            "note": "write jobs verified + rollback drills recorded"},
    },
    "S5": {
        "desc": "branch/code tasks, strong model + strong verifier",
        "classes": ["read_only", "report", "artifact_write",
                    "branch_code"],
        "mcp_tools": READONLY_MCP_TOOLS,
        "concurrency": 2,
        "quota": None,
        "env_required": {"OPENCODE_LANES": "1"},
        "independent_verifier": True,
        "supervised": False,
        "promote_gate": None,          # terminal stage
    },
}
STAGE_ORDER = list(STAGES)

# the executor the graduated lane is for — reviews filter the ledger to
# this arm; l0/devin run records are baselines, not lane evidence
LANE_EXECUTOR = "opencode"

ENVELOPE_REQUIRED = [
    "id", "card", "task_class", "stage", "target_host", "executor",
    "model", "provider", "mcp_allowlist", "allowed_paths",
    "artifact", "verifier", "escalation", "rollback", "heartbeat",
]

PROVIDER_PROBE = {          # envelope provider -> probe.net keys needed
    "litellm": ["litellm", "litellm_authed"],
    "zen": ["wan"],
    "openrouter": ["wan"],
    "ollama": ["ollama_local", "ollama_idc02", "ollama_idc03"],  # any-of
    "devin": ["wan", "devin_cloud"],
    "local": [],
    "none": [],
}
ANY_OF_PROVIDERS = {"ollama"}


# ------------------------------------------------------------ yaml lite

def _load_yaml_min(path: Path):
    try:
        import yaml  # type: ignore
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        pass
    except Exception as e:
        raise SystemExit(f"{path}: yaml parse error: {e}")
    # dependency-free fallback: enough for our envelope shape
    # (flat maps, nested maps, and "- item" / "[a, b]" lists)
    root = {}
    stack = [(-1, root)]

    def _scalar(s):
        s = s.strip()
        if s in ("[]", ""):
            return [] if s == "[]" else ""
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
        if s.startswith("[") and s.endswith("]"):
            return [x.strip().strip('"').strip("'")
                    for x in s[1:-1].split(",") if x.strip()]
        try:
            return int(s)
        except ValueError:
            return s.strip('"').strip("'")

    for raw in path.read_text().splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if isinstance(parent, dict) and parent:
                # last key opened an empty value that is actually a list
                last = next(reversed(parent))
                if parent[last] == {}:
                    parent[last] = []
                    stack[-1] = (stack[-1][0], parent[last])
                    parent = parent[last]
            if not isinstance(parent, list):
                continue
            parent.append(_scalar(line[2:]))
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        if v.strip() == "":
            nxt = {}
            parent[k] = nxt
            stack.append((indent, nxt))
        else:
            parent[k] = _scalar(v)
    return root


def load_envelope(path: Path) -> dict:
    env = _load_yaml_min(path)
    if not isinstance(env, dict):
        raise SystemExit(f"{path}: not a mapping")
    env.setdefault("_path", str(path))
    return env


# ------------------------------------------------------------ lint/admit

def lint_envelope(env: dict) -> list:
    """Missing/invalid envelope fields. Empty list = structurally OK."""
    errs = []
    for k in ENVELOPE_REQUIRED:
        if k not in env:
            errs.append(f"missing_envelope_field:{k}")
    if errs:
        return errs
    if env.get("task_class") not in TASK_CLASSES + DENIED_CLASSES:
        errs.append(f"bad_value:task_class={env.get('task_class')}")
    if env.get("stage") not in STAGES:
        errs.append(f"bad_value:stage={env.get('stage')}")
    if "profile" in env and not isinstance(env.get("profile"), str):
        errs.append("bad_value:profile must be a profile id string")
    if not isinstance(env.get("mcp_allowlist"), list):
        errs.append("bad_value:mcp_allowlist must be a list")
    if not isinstance(env.get("allowed_paths"), list) or \
            not env.get("allowed_paths"):
        errs.append("bad_value:allowed_paths must be a non-empty list")
    for sect, keys in (("artifact", ["path", "schema"]),
                       ("verifier", ["type", "ref"]),
                       ("escalation", ["on_fail", "max_retries"]),
                       ("rollback", ["kind"]),
                       ("heartbeat", ["required"])):
        sub = env.get(sect)
        if not isinstance(sub, dict):
            errs.append(f"missing_envelope_field:{sect}")
            continue
        for k in keys:
            if k not in sub:
                errs.append(f"missing_envelope_field:{sect}.{k}")
    return errs


def killed() -> str:
    """Kill-switch reason, or ''. KILLED file or env var both count."""
    if os.environ.get("OPENCODE_LANE_KILL"):
        return "env:OPENCODE_LANE_KILL"
    if kill_file().is_file():
        try:
            return json.loads(kill_file().read_text()).get(
                "reason", "killed") or "killed"
        except Exception:
            return "killed"
    return ""


def load_stage() -> dict:
    if stage_file().is_file():
        return json.loads(stage_file().read_text())
    return {"current_stage": "S0",
            "history": [{"at": now_iso(), "from": None, "to": "S0",
                         "by": "init",
                         "reason": "lane initialised at S0"}],
            "jobs_completed": {},
            "review_due": None}


def save_stage(st: dict):
    state_dir().mkdir(parents=True, exist_ok=True)
    stage_file().write_text(json.dumps(st, indent=1))


def _heartbeat_age_s(job_id: str):
    f = state_dir() / f"heartbeat-{job_id}.json"
    if not f.is_file():
        return None
    try:
        at = json.loads(f.read_text())["at"]
        dt = datetime.fromisoformat(at)
        return time.time() - dt.timestamp()
    except Exception:
        return None


def _inflight_count(stale_s: int = 3600) -> int:
    if not inflight_dir().is_dir():
        return 0
    n = 0
    for f in inflight_dir().glob("*.json"):
        try:
            at = json.loads(f.read_text())["at"]
            if time.time() - datetime.fromisoformat(at).timestamp() \
                    < stale_s:
                n += 1
        except Exception:
            n += 1          # unreadable marker counts — fail closed
    return n


def _path_under(path: str, roots: list) -> bool:
    p = path.lstrip("/")
    return any(p == r.rstrip("/") or p.startswith(r) for r in roots)


def admit(env: dict, probe: dict = None, host: str = "",
          stage_state: dict = None, inflight: int = None,
          env_get=os.environ.get) -> dict:
    """Fail-closed admission decision. Collects every applicable deny
    reason so operators see the full list, not just the first."""
    reasons = []
    ks = killed()
    if ks:
        reasons.append(f"kill_switch:{ks}")

    lint = lint_envelope(env)
    if lint:
        return {"admit": False, "job": env.get("id"),
                "reasons": reasons + lint}

    st = stage_state or load_stage()
    cur = st.get("current_stage", "S0")
    stage = STAGES[cur]
    estage = env["stage"]

    cls = env["task_class"]
    if cls in DENIED_CLASSES:
        reasons.append(f"denied_class:{cls}")
    if estage != cur:
        reasons.append(f"wrong_stage:job={estage} lane={cur}")
    elif cls not in stage["classes"]:
        reasons.append(f"class_not_in_stage:{cls}")

    # task-scoped profiles (opencode-task-agent-profiles): an opencode
    # job outside the frozen S0 shadow corpus must name a profile —
    # the generic build agent is never an unattended executor. Deep
    # envelope<->profile consistency (tool/path/model/verifier/rollback
    # ceilings) is checked by opencode_profiles.check_envelope.
    if env.get("executor") == "opencode" and cls != "shadow_replay":
        pid = env.get("profile")
        if not pid:
            reasons.append(
                "missing_profile:unattended opencode jobs must name "
                "a task profile")
        elif not (PROFILES / pid / "profile.yml").is_file():
            reasons.append(f"unknown_profile:{pid}")
        else:
            pdata = _load_yaml_min(PROFILES / pid / "profile.yml")
            if isinstance(pdata, dict):
                if pdata.get("status") != "enabled":
                    reasons.append(f"profile_disabled:{pid}")
                if pdata.get("unattended") is False and \
                        env.get("unattended", True) is not False:
                    reasons.append(f"profile_not_unattended:{pid}")

    h = host or os.uname().nodename
    if env["target_host"] != h:
        reasons.append(
            f"wrong_host:job={env['target_host']} here={h}")

    v = env.get("verifier") or {}
    vref = str(v.get("ref", ""))
    if not vref:
        reasons.append("missing_verifier")
    elif v.get("type") in ("held_out_py", "command") and \
            not (REPO / vref).is_file():
        reasons.append(f"missing_verifier:{vref}")
    if stage.get("independent_verifier") and \
            v.get("type") != "independent_devin":
        reasons.append(
            "weak_verifier:stage requires independent_devin")

    permitted = stage["mcp_tools"]
    for t in env.get("mcp_allowlist") or []:
        if t not in permitted:
            reasons.append(f"denied_tool:{t}")

    roots = STAGE_ALLOWED_ROOTS[cur]
    for p in env.get("allowed_paths") or []:
        if not _path_under(p, roots):
            reasons.append(f"denied_path:{p}")

    for var, want in (stage.get("env_required") or {}).items():
        if env_get(var) != want:
            reasons.append(f"env_gate:{var}!={want}")

    quota = stage.get("quota")
    done = (st.get("jobs_completed") or {}).get(cur, 0)
    if quota is not None and done >= quota:
        reasons.append(f"quota_exceeded:{cur} did {done}/{quota}")

    hb = env.get("heartbeat") or {}
    if hb.get("required"):
        age = _heartbeat_age_s(env["id"])
        if age is None or age > int(hb.get("stale_s", 300)):
            reasons.append("stale_heartbeat")

    prov = env.get("provider", "none")
    p = probe if probe is not None else shadow_eval.probe("")
    need = PROVIDER_PROBE.get(prov)
    if need is None:
        reasons.append(f"failed_provider:unknown:{prov}")
    elif need:
        flags = [bool((p.get("net") or {}).get(k)) for k in need]
        ok = any(flags) if prov in ANY_OF_PROVIDERS else all(flags)
        if not ok:
            reasons.append(f"failed_provider:{prov}")

    cap = stage.get("concurrency") or 1
    n_in = _inflight_count() if inflight is None else inflight
    if n_in >= cap:
        reasons.append(f"concurrency_cap:{n_in}>={cap}")

    needs_rb = cls == "branch_code" or (
        cur in ("S4", "S5") and cls == "artifact_write")
    if needs_rb:
        rb = (env.get("rollback") or {}).get("kind")
        if rb not in ("git-revert", "file-restore", "worktree-drop"):
            reasons.append(f"missing_rollback:{rb}")
    if cur == "S5" and cls == "branch_code":
        if env.get("model") not in STRONG_MODELS:
            reasons.append(f"weak_model:{env.get('model')}")

    return {"admit": not reasons, "job": env.get("id"),
            "stage": cur, "reasons": reasons}


# -------------------------------------------------------------- metrics

METRIC_FIELDS = [
    "job_id", "card", "stage", "task_class", "executor", "profile",
    "model",
    "provider", "input_tokens", "cache_read_tokens", "cache_write_tokens",
    "output_tokens", "provider_cost_usd", "wall_s", "queue_s", "retries",
    "tool_denials", "human_minutes", "verifier_pass", "artifact_landed",
    "escalated", "combined_cost_usd", "devin_equiv_tokens",
    "failure_reason", "at",
]


def price(provider_model: str, inp: int, outp: int) -> float:
    inp_r, out_r = PRICE_TABLE.get(provider_model, (0.0, 0.0))
    return round((inp * inp_r + outp * out_r) / 1_000_000, 6)


def new_metric(env: dict, executor: str) -> dict:
    m = {k: None for k in METRIC_FIELDS}
    m.update({"job_id": env.get("id"), "card": env.get("card"),
              "stage": env.get("stage"), "task_class": env.get("task_class"),
              "executor": executor, "profile": env.get("profile"),
              "model": env.get("model", ""),
              "provider": env.get("provider", ""), "at": now_iso(),
              "input_tokens": 0, "cache_read_tokens": 0,
              "cache_write_tokens": 0, "output_tokens": 0,
              "provider_cost_usd": 0.0, "wall_s": 0.0, "queue_s": 0.0,
              "retries": 0, "tool_denials": 0, "human_minutes": 0.0,
              "verifier_pass": False, "artifact_landed": False,
              "escalated": False, "combined_cost_usd": 0.0,
              "devin_equiv_tokens": None, "failure_reason": None})
    return m


def finalize_cost(m: dict):
    m["provider_cost_usd"] = price(
        m.get("model") or "", m.get("input_tokens") or 0,
        (m.get("output_tokens") or 0) + (m.get("cache_write_tokens") or 0))
    m["combined_cost_usd"] = round(
        m["provider_cost_usd"] +
        (m.get("human_minutes") or 0) * HUMAN_MIN_RATE_USD, 6)


def record_metric(m: dict):
    finalize_cost(m)
    state_dir().mkdir(parents=True, exist_ok=True)
    with open(ledger_file(), "a") as f:
        f.write(json.dumps(m) + "\n")


def load_ledger(stage: str = "") -> list:
    if not ledger_file().is_file():
        return []
    out = []
    for line in ledger_file().read_text().splitlines():
        try:
            m = json.loads(line)
        except Exception:
            continue
        if stage and m.get("stage") != stage:
            continue
        out.append(m)
    return out


def _pct(vals: list, q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, int(q * len(s) + 0.5))
    return s[i]


def aggregate(recs: list) -> dict:
    """Aggregate report per the card: verified rate, cost/tokens per
    verified job, median/p95 time, retries, intervention minutes, Devin
    tokens displaced, failure reasons."""
    n = len(recs)
    verified = [m for m in recs
                if m.get("verifier_pass") and m.get("artifact_landed")]
    nv = len(verified)

    def tot(k, ms=recs):
        return sum(m.get(k) or 0 for m in ms)

    tok = lambda m: (m.get("input_tokens") or 0) + \
        (m.get("output_tokens") or 0) + (m.get("cache_read_tokens") or 0) + \
        (m.get("cache_write_tokens") or 0)
    walls = [m.get("wall_s") or 0 for m in recs]
    queues = [m.get("queue_s") or 0 for m in recs]
    displaced = sum(max(0, (m.get("devin_equiv_tokens") or 0) - tok(m))
                    for m in verified if m.get("devin_equiv_tokens"))
    fails = {}
    for m in recs:
        r = m.get("failure_reason")
        if r:
            fails[r.split(":")[0]] = fails.get(r.split(":")[0], 0) + 1
    by_stage = {}
    for m in recs:
        s = m.get("stage") or "?"
        d = by_stage.setdefault(s, {"jobs": 0, "verified": 0})
        d["jobs"] += 1
        d["verified"] += int(bool(m.get("verifier_pass")
                                and m.get("artifact_landed")))
    return {
        "jobs": n,
        "verified": nv,
        "verified_success_rate": round(nv / n, 3) if n else 0.0,
        "tokens_per_verified_job":
        round(sum(tok(m) for m in verified) / nv, 1) if nv else 0,
        "total_tokens": tot("input_tokens") + tot("output_tokens") +
        tot("cache_read_tokens") + tot("cache_write_tokens"),
        "cost_per_verified_job_usd":
        round(tot("combined_cost_usd", verified) / nv, 4) if nv else 0,
        "total_cost_usd": round(tot("combined_cost_usd"), 4),
        "wall_s_median": statistics.median(walls) if walls else 0,
        "wall_s_p95": _pct(walls, 0.95),
        "queue_s_median": statistics.median(queues) if queues else 0,
        "queue_s_p95": _pct(queues, 0.95),
        "retries_total": tot("retries"),
        "tool_denials_total": tot("tool_denials"),
        "human_minutes_total": tot("human_minutes"),
        "escalations": sum(1 for m in recs if m.get("escalated")),
        "devin_tokens_displaced": displaced,
        "failure_reasons": fails,
        "by_stage": by_stage,
    }


# --------------------------------------------------------------- review

def review(stage_state: dict = None, recs: list = None) -> dict:
    """Weekly promotion review. Compares ledger evidence for the current
    stage against its promote_gate and emits promote|hold|rollback."""
    st = stage_state or load_stage()
    cur = st.get("current_stage", "S0")
    stage = STAGES[cur]
    recs = load_ledger(stage=cur) if recs is None else recs
    # the gate measures the lane arm only — l0/devin baseline records
    # stay in the ledger for pairing but never inflate promotion math
    recs = [m for m in recs if m.get("executor") == LANE_EXECUTOR]
    agg = aggregate(recs)
    gate = stage.get("promote_gate")
    reasons, decision = [], "hold"

    # hard rollback triggers anywhere in the stage's ledger
    bad = [m for m in recs if m.get("failure_reason") and
           m["failure_reason"].split(":")[0] in
           ("tool_denial", "denied_tool", "scope_violation",
            "mutating_command", "verifier_peek")]
    if killed():
        decision, reasons = "hold", ["kill switch engaged"]
    elif bad:
        decision = "rollback"
        reasons = [f"{len(bad)} safety-critical failure(s): "
                   + ", ".join(sorted({m['failure_reason'].split(':')[0]
                                        for m in bad}))]
    elif gate is None:
        decision, reasons = "hold", ["terminal stage — no promotion"]
    else:
        if agg["jobs"] < gate["min_jobs"]:
            reasons.append(
                f"jobs {agg['jobs']} < required {gate['min_jobs']}")
        if agg["verified_success_rate"] < gate["min_verified_rate"]:
            reasons.append(
                f"verified rate {agg['verified_success_rate']} < "
                f"{gate['min_verified_rate']}")
        if agg["tool_denials_total"] > (gate["max_tool_denials"] or 0):
            reasons.append(
                f"tool denials {agg['tool_denials_total']} > "
                f"{gate['max_tool_denials']}")
        me = gate.get("max_escalations")
        if me is not None and agg["escalations"] > me:
            reasons.append(
                f"escalations {agg['escalations']} > {me}")
        if not reasons:
            decision = "promote"
            reasons = [gate["note"]]
    nxt = None
    if decision == "promote" and cur != STAGE_ORDER[-1]:
        nxt = STAGE_ORDER[STAGE_ORDER.index(cur) + 1]
    prev = STAGE_ORDER[STAGE_ORDER.index(cur) - 1] \
        if decision == "rollback" and cur != "S0" else (
            "S0" if decision == "rollback" else None)
    return {"at": now_iso(), "stage": cur, "decision": decision,
            "promote_to": nxt, "rollback_to": prev,
            "reasons": reasons, "aggregate": agg,
            "ledger": recs,     # embedded so a committed review stays
                                # re-derivable after state loss (AUD-0950)
            "gate": gate, "next_review_due":
            (datetime.now(timezone.utc) + timedelta(days=7)).date()
            .isoformat()}


def cmd_review(args):
    st = load_stage()
    r = review(st)
    st["review_due"] = r["next_review_due"]
    st.setdefault("reviews", []).append(
        {"at": r["at"], "stage": r["stage"], "decision": r["decision"]})
    save_stage(st)
    REPORTS.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    (REPORTS / f"{day}-promotion-review.json").write_text(
        json.dumps(r, indent=1))
    md = [f"# OpenCode lane promotion review — {day}", "",
          f"stage: **{r['stage']}**  decision: **{r['decision'].upper()}**",
          ""]
    if r["promote_to"]:
        md.append(f"promote to: **{r['promote_to']}**")
    if r["rollback_to"]:
        md.append(f"rollback to: **{r['rollback_to']}**")
    md += ["", "## reasons"] + [f"- {x}" for x in r["reasons"]]
    a = r["aggregate"]
    md += ["", "## aggregate (current stage ledger)", "",
           f"- jobs: {a['jobs']}  verified: {a['verified']}  "
           f"rate: {a['verified_success_rate']}",
           f"- tokens/verified job: {a['tokens_per_verified_job']}  "
           f"cost/verified: ${a['cost_per_verified_job_usd']}",
           f"- wall median/p95: {a['wall_s_median']}s / {a['wall_s_p95']}s",
           f"- retries: {a['retries_total']}  denials: "
           f"{a['tool_denials_total']}  human-min: "
           f"{a['human_minutes_total']}",
           f"- devin tokens displaced: {a['devin_tokens_displaced']}",
           f"- failure reasons: {a['failure_reasons']}"]
    if r["gate"]:
        md += ["", f"gate note: {r['gate']['note']}"]
    (REPORTS / f"{day}-promotion-review.md").write_text("\n".join(md))
    print(json.dumps({k: r[k] for k in ("stage", "decision",
                                        "promote_to", "rollback_to",
                                        "reasons")}, indent=1))
    return 0


def restore_stage(stage: str, review_path: Path) -> dict:
    """Rebuild stage.json after state-dir loss (AUD-0950). Only accepts
    a committed promotion-review JSON whose decision promotes to the
    requested stage — the restore is evidence-backed, never bare."""
    st = load_stage()
    cur = st.get("current_stage", "S0")
    if stage_file().is_file() and \
            STAGE_ORDER.index(cur) >= STAGE_ORDER.index(stage):
        return {"error": f"lane already at {cur} — use promote/demote"}
    rp = Path(review_path)
    if not rp.is_file():
        return {"error": f"no such review: {rp}"}
    rv = json.loads(rp.read_text())
    if rv.get("decision") != "promote" or rv.get("promote_to") != stage:
        return {"error": f"review {rp.name} does not promote to {stage}",
                "review": {k: rv.get(k) for k in
                           ("decision", "promote_to", "stage")}}
    st.setdefault("history", []).append(
        {"at": now_iso(), "from": cur, "to": stage, "by": "restore",
         "reason": f"stage rebuilt from committed review {rp.name} "
                   "after state-dir loss (AUD-0950); ledger records "
                   "pre-loss are unrecoverable"})
    st["current_stage"] = stage
    save_stage(st)
    return {"restored": stage, "evidence": str(rp),
            "history": st["history"][-1]}


# ----------------------------------------------------------------- s0

def _count_denied(rec: dict, env: dict) -> int:
    """Tool denials visible in a shadow run record: mutating commands,
    verifier peeks, scope violations, plus MCP calls outside the
    envelope allowlist."""
    n = len(rec.get("mutating_commands") or []) + \
        len(rec.get("verifier_peeks") or []) + \
        len(rec.get("scope_violations") or [])
    allow = set(env.get("mcp_allowlist") or [])
    for t in rec.get("tool_calls") or []:
        if str(t).startswith("mcp_") and t not in allow:
            n += 1
    return n


def _artifact_path(env: dict) -> str:
    return str((env.get("artifact") or {}).get("path") or "")


def cmd_s0(args):
    """Admit an S0 envelope, execute its fixture on the requested arms in
    isolated worktrees, held-out verify, then record per-arm metrics."""
    env = load_envelope(Path(args.job))
    fid = env.get("fixture")
    if not fid:
        print(json.dumps({"error": "S0 envelopes need fixture:<id>"}))
        return 2
    arms = env.get("pair_arms") or [env.get("executor", "opencode")]
    if args.arm:
        arms = args.arm.split(",")
    p = shadow_eval.probe("")
    dec = admit(env, probe=p)
    if not dec["admit"]:
        for arm in arms:
            m = new_metric(env, arm)
            m["failure_reason"] = ";".join(dec["reasons"])
            record_metric(m)
        print(json.dumps(dec, indent=1))
        return 2

    run_id = args.run_id or datetime.now().strftime("s0-%Y%m%d-%H%M%S")
    t_queue = time.time()
    results = []
    for arm in arms:
        m = new_metric(env, arm)
        m["queue_s"] = round(time.time() - t_queue, 1)
        budget = int((env.get("escalation") or {}).get("max_retries", 0))
        rec = shadow_eval.run_arm(
            run_id, fid, arm,
            model=env.get("model", "") if arm == "opencode" else "",
            rung="L2" if arm == "opencode" else "",
            retries=budget)
        tok = rec.get("tokens") or {}
        m["input_tokens"] = tok.get("input") or 0
        m["output_tokens"] = tok.get("output") or 0
        m["cache_read_tokens"] = tok.get("cache_read") or 0
        m["cache_write_tokens"] = tok.get("cache_write") or 0
        m["wall_s"] = rec.get("wall_s") or 0
        # run_arm seeds rec["retries"] with the retry BUDGET — actual
        # retries = recorded minus budget
        m["retries"] = max(0, (rec.get("retries") or 0) - budget)
        m["verifier_pass"] = rec.get("verdict") == "pass"
        den = _count_denied(rec, env)
        m["tool_denials"] = den
        art = shadow_eval.run_dir(run_id, arm, fid) / "wt" / \
            _artifact_path(env)
        m["artifact_landed"] = art.is_file()
        m["escalated"] = rec.get("verdict") not in ("pass",) and \
            (env.get("escalation") or {}).get("on_fail") in \
            ("manual", "devin", "retry_then_manual")
        fr = None
        if den:
            fr = "tool_denial"
        elif not m["artifact_landed"]:
            fr = "missing_artifact"
        elif rec.get("exit_code") == -2:
            fr = "timeout"
        elif rec.get("exit_code") not in (0, None) and \
                not m["verifier_pass"]:
            fr = "executor_error"
        elif not m["verifier_pass"]:
            fr = "unverified_exit"
        m["failure_reason"] = fr
        record_metric(m)
        results.append({"arm": arm, "verdict": rec.get("verdict"),
                        "artifact": m["artifact_landed"],
                        "tokens_in": m["input_tokens"],
                        "wall_s": m["wall_s"],
                        "denials": den, "failure": fr})
    st = load_stage()
    st.setdefault("jobs_completed", {})
    st["jobs_completed"]["S0"] = st["jobs_completed"].get("S0", 0) + 1
    save_stage(st)
    print(json.dumps({"run_id": run_id, "fixture": fid,
                      "admit": dec, "results": results}, indent=1))
    return 0 if all(r["verdict"] == "pass" for r in results) else 1


# -------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("lint", "admit"):
        sp = sub.add_parser(name)
        sp.add_argument("job")

    sp = sub.add_parser("s0-run")
    sp.add_argument("job")
    sp.add_argument("--arm", default="")
    sp.add_argument("--run-id", default="")

    sub.add_parser("stage")
    sub.add_parser("review")
    sub.add_parser("promote")
    sp = sub.add_parser("demote")
    sp.add_argument("stage", choices=STAGE_ORDER)
    sp = sub.add_parser("restore")
    sp.add_argument("stage", choices=STAGE_ORDER)
    sp.add_argument("--from-review", required=True,
                    help="committed promotion-review JSON that proves "
                         "the stage (decision=promote, promote_to=S)")

    sp = sub.add_parser("kill")
    sp.add_argument("--reason", default="operator kill")
    sub.add_parser("resume")

    for name in ("begin", "end", "heartbeat"):
        sp = sub.add_parser(name)
        sp.add_argument("job_id")

    sp = sub.add_parser("record")
    sp.add_argument("metric_json")
    sp = sub.add_parser("metrics")
    sp.add_argument("--stage", default="")

    args = ap.parse_args()

    if args.cmd == "lint":
        env = load_envelope(Path(args.job))
        errs = lint_envelope(env)
        print(json.dumps({"ok": not errs, "errors": errs}, indent=1))
        return 0 if not errs else 1
    if args.cmd == "admit":
        env = load_envelope(Path(args.job))
        print(json.dumps(admit(env), indent=1))
        return 0
    if args.cmd == "s0-run":
        return cmd_s0(args)
    if args.cmd == "stage":
        st = load_stage()
        st["killed"] = bool(killed())
        print(json.dumps(st, indent=1))
        return 0
    if args.cmd == "review":
        return cmd_review(args)
    if args.cmd == "promote":
        st = load_stage()
        r = review(st)
        if r["decision"] != "promote":
            print(json.dumps({"error": "review does not recommend "
                              "promotion", "review": r}, indent=1))
            return 1
        st["history"].append({"at": now_iso(), "from": r["stage"],
                              "to": r["promote_to"], "by": "lane_gate",
                              "reason": "; ".join(r["reasons"])})
        st["current_stage"] = r["promote_to"]
        save_stage(st)
        print(json.dumps({"promoted": r["promote_to"],
                          "history": st["history"][-1]}, indent=1))
        return 0
    if args.cmd == "demote":
        st = load_stage()
        cur = st.get("current_stage", "S0")
        if STAGE_ORDER.index(args.stage) >= STAGE_ORDER.index(cur):
            print(json.dumps({"error": f"{args.stage} is not earlier "
                              f"than {cur}"}))
            return 1
        st["history"].append({"at": now_iso(), "from": cur,
                              "to": args.stage, "by": "operator",
                              "reason": "manual rollback"})
        st["current_stage"] = args.stage
        save_stage(st)
        print(json.dumps({"demoted": args.stage}))
        return 0
    if args.cmd == "restore":
        r = restore_stage(args.stage, Path(args.from_review))
        print(json.dumps(r, indent=1))
        return 1 if "error" in r else 0
    if args.cmd == "kill":
        state_dir().mkdir(parents=True, exist_ok=True)
        kill_file().write_text(json.dumps(
            {"at": now_iso(), "reason": args.reason}))
        st = load_stage()
        st["history"].append({"at": now_iso(), "from": st["current_stage"],
                              "to": "KILLED", "by": "operator",
                              "reason": args.reason})
        save_stage(st)
        print(json.dumps({"killed": True, "reason": args.reason}))
        return 0
    if args.cmd == "resume":
        if kill_file().is_file():
            kill_file().unlink()
        st = load_stage()
        st["history"].append({"at": now_iso(), "from": "KILLED",
                              "to": st["current_stage"], "by": "operator",
                              "reason": "resume"})
        save_stage(st)
        print(json.dumps({"killed": False}))
        return 0
    if args.cmd == "begin":
        inflight_dir().mkdir(parents=True, exist_ok=True)
        (inflight_dir() / f"{args.job_id}.json").write_text(json.dumps(
            {"job": args.job_id, "at": now_iso(), "pid": os.getpid()}))
        return 0
    if args.cmd == "end":
        f = inflight_dir() / f"{args.job_id}.json"
        if f.is_file():
            f.unlink()
        return 0
    if args.cmd == "heartbeat":
        state_dir().mkdir(parents=True, exist_ok=True)
        (state_dir() / f"heartbeat-{args.job_id}.json").write_text(
            json.dumps({"job": args.job_id, "at": now_iso()}))
        return 0
    if args.cmd == "record":
        record_metric(json.loads(Path(args.metric_json).read_text()))
        return 0
    if args.cmd == "metrics":
        recs = load_ledger(stage=args.stage)
        print(json.dumps(aggregate(recs), indent=1))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
