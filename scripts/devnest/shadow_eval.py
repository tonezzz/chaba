#!/usr/bin/env python3
"""DevNest shadow/evaluation mode + rainy-day fallback ladder.

Shadow mode runs frozen identical fixtures through independent executor
arms (L0 deterministic scripts, OpenCode, Devin) in isolated git
worktrees, then verifies the artifacts with held-out verifiers and emits
a benchmark report. Nothing in shadow mode merges, pushes, or mutates
production state.

The rainy-day ladder routes a task to the cheapest rung that can still
pass given a live connectivity/model probe:

    L0  deterministic local scripts            (no LLM, no network)
    L1  local OpenCode + local Ollama          (loopback only, small prompts)
    L2  LAN/tailnet LiteLLM gateway            (idc03 :4000)
    L3  remote LiteLLM / OpenCode Zen          (WAN)
    L4  Devin cloud                            (paid, full surface)
    MANUAL  Tony's hands — terminal gate

Subcommands:
    probe      environment capability snapshot (connectivity/tools/models)
    route      pick a ladder rung for a fixture or freeform task
    matrix     capability matrix PASS/DEGRADED/BLOCKED per rung
    simulate   offline/air-gap routing simulation + proof of no net/secrets
    prestage   stage models/config/fixture manifest for offline use
    run        execute a fixture on an arm in an isolated worktree + verify
               (--arm l0,opencode,devin runs the full paired set)
    verify     re-run a held-out verifier on an existing run dir
    report     aggregate runs -> benchmark report (md + json)
    clean      remove shadow worktrees/branches for a run (keeps artifacts)

Safety invariants enforced here:
  * every arm gets its own worktree+branch (shadow/<run>-<arm>-<fixture>)
  * fixtures dir is sparse-checkout-excluded -> verifiers stay held-out
  * event logs are audited for reads of verify.py and mutating commands
  * rungs that need network or secrets are never selected when the probe
    says they are unavailable, and load_arm_env() refuses to load secrets
    when SHADOW_OFFLINE=1.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- consts

REPO = Path(__file__).resolve().parents[2]
SHADOW = REPO / "evals" / "shadow"
FIXTURES = SHADOW / "fixtures"
RUNS = SHADOW / "runs"
REPORTS = SHADOW / "reports"
STAGED = SHADOW / "staged"
TASK_SUBDIR = Path("evals") / "shadow" / "task"

LITELLM_BASE = os.environ.get("SHADOW_LITELLM", "http://100.102.134.91:4000")
OLLAMA_IDC02 = os.environ.get("SHADOW_OLLAMA_IDC02",
                              "http://100.123.163.11:11434")
OLLAMA_IDC03 = os.environ.get("SHADOW_OLLAMA_IDC03",
                              "http://100.102.134.91:11434")
OLLAMA_LOCAL = os.environ.get("SHADOW_OLLAMA_LOCAL",
                              "http://127.0.0.1:11434")
BOARD_API = "https://idc03.taila0626a.ts.net:10000"
WAN_PROBES = ["https://openrouter.ai", "https://api.opencode.ai",
              "https://github.com"]
DEVIN_PROBE = "https://api.devin.ai"

L1_MAX_PROMPT_CHARS = 4000      # local small-model lane: small prompts only
PROBE_TIMEOUT = 4
DEFAULT_OC_MODEL = "litellm/gemini-3.5-flash-lite"
ZEN_FREE_MODEL = "opencode/deepseek-v4.1-flash-free"
LOCAL_OLLAMA_MODEL = "ollama/qwen2.5:7b-instruct"

MANUAL_KW = ["hardware", "buy", "physical", "spend", "purchase",
             "order the", "rekey", "rotation", "blocked on tony",
             "sudo-gated", "irreversible", "production deploy",
             "delete prod", "payment"]

MUTATING_RE = re.compile(
    r"(^|[^a-z])(rm |mv |dd |mkfs|git\s+(push|commit|merge|checkout|"
    r"reset|worktree\s+(add|remove|prune)|rebase)|systemctl\s+(start|stop|"
    r"restart|enable|disable|mask)|kill |pkill|sudo\b|apt(-get)?\s+(install|"
    r"remove)|pip\s+install|npm\s+install|launchctl|shutdown|reboot)",
    re.I)
VERIFIER_PEEK_RE = re.compile(r"verify\.py|shadow/fixtures", re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _load_yaml_min(path: Path) -> dict:
    """Tiny YAML reader for our own task.yaml shape (key: value, nested
    lists only where we control them). Falls back to pyyaml if present."""
    try:
        import yaml  # type: ignore
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception:
        out = {}
        for line in path.read_text().splitlines():
            m = re.match(r"^([a-z_]+):\s*(.+)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        return out


def fixture_dir(fid: str) -> Path:
    d = FIXTURES / fid
    if not d.is_dir():
        raise SystemExit(f"unknown fixture {fid} — have: "
                         f"{[p.name for p in FIXTURES.iterdir()]}")
    return d


def list_fixtures() -> list:
    return sorted(p.name for p in FIXTURES.iterdir()
                  if p.is_dir() and (p / "task.yaml").exists())


def fixture_meta(fid: str) -> dict:
    return _load_yaml_min(fixture_dir(fid) / "task.yaml")


# ------------------------------------------------------------------ probe

def _http_ok(url: str, timeout: int = PROBE_TIMEOUT, key: str = "",
             want_2xx: bool = False) -> bool:
    """Reachable = any HTTP response at all (even 4xx); want_2xx=True
    additionally requires a non-error status (auth/liveness checks)."""
    try:
        req = urllib.request.Request(url)
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        urllib.request.urlopen(req, timeout=timeout).read(512)
        return True
    except urllib.error.HTTPError:
        return not want_2xx
    except Exception:
        return False


def _secret_exists(name: str) -> bool:
    """Existence only — never reads secret contents."""
    return (Path.home() / ".config" / "secrets" / name).is_file()


def bench_key() -> str:
    """LITELLM_KEY_BENCH (fallback LITELLM_KEY_CHABA) for probe/run use."""
    for var in ("LITELLM_KEY_BENCH", "LITELLM_KEY_CHABA"):
        if os.environ.get(var):
            return os.environ[var]
    env = Path.home() / ".config" / "secrets" / "litellm-keys.env"
    if env.is_file():
        for line in env.read_text().splitlines():
            for var in ("LITELLM_KEY_BENCH", "LITELLM_KEY_CHABA"):
                if line.startswith(var + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def probe(offline: str = "") -> dict:
    """Live environment probe. offline='offline' forces tailnet+WAN down
    (loopback still probed); 'airgap' forces everything down."""
    force_off = offline in ("offline", "airgap")
    tools = {t: shutil.which(t) for t in
             ("opencode", "devin", "ollama", "git", "python3")}
    net = {}
    if force_off:
        for k in ("litellm", "ollama_idc02", "ollama_idc03", "tailnet",
                  "wan", "devin_cloud"):
            net[k] = False
        net["ollama_local"] = (offline == "offline"
                               and _http_ok(OLLAMA_LOCAL + "/api/version"))
        if offline == "airgap":
            net["ollama_local"] = False
    else:
        key = bench_key()
        net = {
            "litellm": _http_ok(LITELLM_BASE + "/health/liveliness",
                                want_2xx=True),
            "litellm_authed": bool(key) and _http_ok(
                LITELLM_BASE + "/v1/models", key=key, want_2xx=True),
            "ollama_idc02": _http_ok(OLLAMA_IDC02 + "/api/version"),
            "ollama_idc03": _http_ok(OLLAMA_IDC03 + "/api/version"),
            "ollama_local": _http_ok(OLLAMA_LOCAL + "/api/version",
                                     timeout=2),
            "tailnet": _http_ok(BOARD_API + "/", timeout=4),
            "wan": any(_http_ok(u, timeout=4) for u in WAN_PROBES),
            "devin_cloud": _http_ok(DEVIN_PROBE, timeout=4),
        }
    models = {}
    if net.get("litellm") and net.get("litellm_authed"):
        try:
            req = urllib.request.Request(LITELLM_BASE + "/v1/models")
            req.add_header("Authorization", f"Bearer {bench_key()}")
            data = json.loads(urllib.request.urlopen(
                req, timeout=PROBE_TIMEOUT).read())
            models["litellm"] = sorted(
                m.get("id", "?") for m in data.get("data", []))[:80]
        except Exception:
            models["litellm"] = []
    if net.get("ollama_local") or net.get("ollama_idc02"):
        base = OLLAMA_LOCAL if net.get("ollama_local") else OLLAMA_IDC02
        try:
            data = json.loads(urllib.request.urlopen(
                base + "/api/tags", timeout=PROBE_TIMEOUT).read())
            models["ollama"] = sorted(m.get("name", "?")
                                      for m in data.get("models", []))
        except Exception:
            models["ollama"] = []
    return {
        "host": os.uname().nodename,
        "at": now_iso(),
        "simulated": offline or None,
        "tools": {k: bool(v) for k, v in tools.items()},
        "net": net,
        "secrets": {"litellm_keys_env": _secret_exists("litellm-keys.env"),
                    "litellm_chaba_env": _secret_exists("litellm-chaba.env")},
        "models": models,
    }


# ----------------------------------------------------------------- ladder

RUNGS = [
    {"id": "L0", "label": "deterministic local scripts",
     "arm": "l0", "net": [], "tools": ["python3", "git"],
     "secrets": False},
    {"id": "L1", "label": "local OpenCode + local Ollama (small prompts)",
     "arm": "opencode", "model": LOCAL_OLLAMA_MODEL,
     "net": ["ollama_local"], "tools": ["opencode"], "secrets": False,
     "max_prompt_chars": L1_MAX_PROMPT_CHARS},
    {"id": "L2", "label": "LAN/tailnet LiteLLM gateway",
     "arm": "opencode", "model": DEFAULT_OC_MODEL,
     "net": ["litellm"], "tools": ["opencode"],
     "secrets": True},
    {"id": "L3", "label": "remote LiteLLM / OpenCode Zen (WAN)",
     "arm": "opencode", "model": ZEN_FREE_MODEL,
     "net": ["wan"], "tools": ["opencode"], "secrets": False},
    {"id": "L4", "label": "Devin cloud",
     "arm": "devin", "net": ["wan", "devin_cloud"], "tools": ["devin"],
     "secrets": True},
    {"id": "MANUAL", "label": "Tony / manual gate", "arm": "manual",
     "net": [], "tools": [], "secrets": False},
]


def evaluate_rungs(p: dict, prompt_chars: int = 0,
                   needs_llm: bool = False) -> list:
    """PASS / DEGRADED / BLOCKED per rung given a probe dict."""
    out = []
    for r in RUNGS:
        rid = r["id"]
        status, why = "PASS", []
        if rid == "MANUAL":
            out.append({"rung": rid, "label": r["label"],
                        "status": "PASS", "why": ["always available"]})
            continue
        missing_net = [n for n in r.get("net", [])
                       if not p["net"].get(n)]
        missing_tools = [t for t in r.get("tools", [])
                         if not p["tools"].get(t)]
        if rid == "L1" and prompt_chars > r.get(
                "max_prompt_chars", L1_MAX_PROMPT_CHARS):
            missing_net.append(f"prompt>{r['max_prompt_chars']}c")
        if missing_tools:
            status = "BLOCKED"
            why += [f"tool missing: {t}" for t in missing_tools]
        if missing_net:
            status = "BLOCKED"
            why += [f"unreachable: {n}" for n in missing_net]
        if rid == "L0" and needs_llm:
            status = "BLOCKED"
            why.append("task needs an LLM — L0 has no model")
        if status == "PASS":
            if rid == "L2" and not p["net"].get("litellm_authed"):
                status, why = "DEGRADED", ["gateway up but auth unproven"]
            elif rid == "L2" and not p["secrets"].get("litellm_keys_env"):
                status, why = "DEGRADED", [
                    "gateway+auth ok but no litellm-keys.env staged"]
        out.append({"rung": rid, "label": r["label"], "status": status,
                    "why": why or ["ok"]})
    return out


def is_manual_task(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in MANUAL_KW)


def route(task_text: str, p: dict, needs_llm: bool = False,
          prompt_chars: int = 0, failed: list = None) -> dict:
    """Cheapest rung expected to pass; `failed` rungs are skipped
    (escalation). Returns rung id + full ladder evaluation."""
    failed = set(failed or [])
    if is_manual_task(task_text):
        return {"rung": "MANUAL", "executor": None,
                "why": ["task matches manual-gate keywords"],
                "ladder": evaluate_rungs(p, prompt_chars, needs_llm)}
    ladder = evaluate_rungs(p, prompt_chars, needs_llm)
    for r in RUNGS:
        rid = r["id"]
        if rid in failed or rid == "MANUAL":
            continue
        ev = next(e for e in ladder if e["rung"] == rid)
        if ev["status"] in ("PASS", "DEGRADED"):
            return {"rung": rid, "executor": r.get("arm"),
                    "model": r.get("model"),
                    "why": ev["why"], "degraded": ev["status"] == "DEGRADED",
                    "ladder": ladder}
    return {"rung": "MANUAL", "executor": None,
            "why": ["every executor rung blocked"], "ladder": ladder}


def route_fixture(fid: str, p: dict, failed: list = None) -> dict:
    meta = fixture_meta(fid)
    prompt = (fixture_dir(fid) / "prompt.md").read_text()
    needs_llm = str(meta.get("needs_llm", "false")).lower() == "true"
    has_l0 = (fixture_dir(fid) / "l0.py").exists()
    if needs_llm or not has_l0:
        return route(prompt, p, needs_llm=True,
                     prompt_chars=len(prompt), failed=failed)
    # deterministic-solvable fixture -> L0 is always the entry rung,
    # unless L0 already failed (then climb the ladder for a re-attempt).
    if failed and "L0" in failed:
        return route(prompt, p, needs_llm=True,
                     prompt_chars=len(prompt), failed=failed)
    r = route(prompt, p, needs_llm=False, prompt_chars=len(prompt),
              failed=failed)
    return r


def load_arm_env(rung: str, model: str = "") -> dict:
    """Env additions for an arm. Refuses to touch secrets when the caller
    declared offline mode — L0/L1/MANUAL never reach this anyway."""
    if os.environ.get("SHADOW_OFFLINE") == "1":
        raise RuntimeError(
            f"load_arm_env({rung}) called while SHADOW_OFFLINE=1 — "
            "offline rungs must never load secrets")
    env = {}
    if rung in ("L2",) or (model or "").startswith("litellm/"):
        key = bench_key()
        if not key:
            raise RuntimeError("litellm model requested but no "
                               "LITELLM_KEY_BENCH/CHABA available")
        env["LITELLM_KEY"] = key
    return env


# ------------------------------------------------------------------- runs

def run_dir(run_id: str, arm: str, fid: str) -> Path:
    return RUNS / run_id / f"{arm}-{fid}"


def _git(cwd, *args, timeout=60):
    return subprocess.run(["git", "-C", str(cwd)] + list(args),
                          capture_output=True, text=True, timeout=timeout)


def _top_dirs_minus_excluded():
    r = _git(REPO, "ls-tree", "-d", "--name-only", "HEAD")
    dirs = [l.strip() for l in r.stdout.splitlines()
            if l.strip() and not l.strip().startswith("evals")]
    return dirs


def make_worktree(wt: Path, branch: str, base: str = "HEAD") -> str:
    """Create an isolated worktree with fixtures held out via sparse
    checkout. Returns '' or error string."""
    if wt.exists():
        return f"worktree path exists: {wt}"
    r = _git(REPO, "worktree", "add", "-b", branch, str(wt), base,
             timeout=180)
    if r.returncode:
        return (r.stderr or r.stdout).strip()[:300]
    # held-out: keep evals/ (and so fixtures/verify.py) out of the arm's
    # materialized tree. Root files always materialize in cone mode.
    try:
        dirs = _top_dirs_minus_excluded()
        r1 = _git(wt, "sparse-checkout", "init", "--cone")
        if r1.returncode == 0:
            r2 = _git(wt, "sparse-checkout", "set", *dirs)
            if r2.returncode:
                return f"sparse set failed: {r2.stderr[:200]}"
    except Exception as e:
        return f"sparse-checkout failed: {e}"
    return ""


def materialize_fixture(wt: Path, fid: str):
    task = wt / TASK_SUBDIR
    fdir = fixture_dir(fid)
    (task / "inputs").mkdir(parents=True, exist_ok=True)
    (task / "artifacts").mkdir(parents=True, exist_ok=True)
    for name in ("task.yaml", "prompt.md"):
        shutil.copy2(fdir / name, task / name)
    src_inputs = fdir / "inputs"
    if src_inputs.is_dir():
        for f in src_inputs.iterdir():
            if f.is_file():
                shutil.copy2(f, task / "inputs" / f.name)


def parse_opencode_events(log_path: Path) -> dict:
    tokens = {"total": 0, "input": 0, "output": 0, "reasoning": 0,
              "cache_read": 0, "cache_write": 0}
    tools, mutating, peeks = [], [], []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        part = ev.get("part") or ev
        tok = part.get("tokens") or (part.get("usage") or {}).get("tokens")
        if isinstance(tok, dict):
            tokens["total"] += int(tok.get("total") or 0)
            tokens["input"] += int(tok.get("input") or 0)
            tokens["output"] += int(tok.get("output") or 0)
            tokens["reasoning"] += int(tok.get("reasoning") or 0)
            c = tok.get("cache") or {}
            tokens["cache_read"] += int(c.get("read") or 0)
            tokens["cache_write"] += int(c.get("write") or 0)
        name = part.get("tool") or (
            part.get("call") or {}).get("name")
        if name:
            tools.append(name)
            # inspect only the call's INPUT params — a state/output dump
            # would false-positive on spec text the agent legitimately read
            inp = (part.get("state") or {}).get("input") \
                or part.get("input") or part.get("args") or {}
            args = json.dumps(inp)
            cmd = inp.get("command") or ""
            if cmd and MUTATING_RE.search(cmd):
                mutating.append(cmd[:200])
            fpath = inp.get("filePath") or inp.get("path") or ""
            peek_hit = ("verify.py" in fpath) or (
                "shadow/fixtures/" in fpath)
            if not peek_hit and cmd:
                if re.search(r"\bverify\.py\b", cmd):
                    peek_hit = True
                elif re.search(
                        r"(?:cat|head|tail|less|more|sed|grep|find|ls|"
                        r"xxd|od|file)\s+[^\n;&|]*shadow/fixtures/", cmd):
                    peek_hit = True
            if peek_hit:
                peeks.append(f"{name}:{(fpath or cmd)[:160]}")
    return {"tokens": tokens, "tool_calls": tools,
            "mutating_commands": mutating, "verifier_peeks": peeks}


def scope_violations(wt: Path) -> list:
    """Files the arm created/modified outside evals/shadow/task. In sparse
    worktrees, `git status` collapses the untracked evals/ tree into a
    single `evals/` entry — expand it and judge each real file."""
    r = _git(wt, "status", "--porcelain")
    bad = []
    for line in r.stdout.splitlines():
        p = line[3:].strip().strip('"')
        if not p:
            continue
        if p.startswith(str(TASK_SUBDIR)):
            continue
        # untracked dirs collapse to the deepest untracked component
        # (e.g. 'evals/shadow/') — expand and judge each real file
        cand = wt / p.rstrip("/")
        if cand.is_dir():
            for f in cand.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(wt).as_posix()
                    if not rel.startswith(str(TASK_SUBDIR) + "/"):
                        bad.append(rel)
            continue
        bad.append(p)
    return bad


def run_arm(run_id: str, fid: str, arm: str, model: str = "",
            rung: str = "", timeout: int = 0, retries: int = 0) -> dict:
    """One arm of one fixture: worktree -> materialize -> execute -> audit
    -> verify. Returns the run record."""
    meta = fixture_meta(fid)
    timeout = timeout or int(meta.get("timeout_s", 420))
    rd = run_dir(run_id, arm, fid)
    rd.mkdir(parents=True, exist_ok=True)
    wt = rd / "wt"
    branch = f"shadow/{run_id}-{arm}-{fid}"
    rec = {"run_id": run_id, "fixture": fid, "arm": arm, "model": model,
           "rung": rung, "branch": branch, "worktree": str(wt),
           "started": now_iso(), "wall_s": None, "exit_code": None,
           "retries": retries, "interventions": 0, "escalated": False,
           "verdict": None, "error": None}
    t0 = time.time()
    err = make_worktree(wt, branch)
    if err:
        rec.update(error=f"worktree: {err}", wall_s=time.time() - t0,
                   exit_code=-1)
        (rd / "run.json").write_text(json.dumps(rec, indent=1))
        return rec
    try:
        materialize_fixture(wt, fid)
        prompt = (wt / TASK_SUBDIR / "prompt.md").read_text()
        rails = ("\n\n## Shadow-mode rails (enforced)\n"
                 "- This is a sandboxed evaluation run. Write ONLY the "
                 "artifact under evals/shadow/task/artifacts/.\n"
                 "- Do not read files under evals/shadow/fixtures or any "
                 "verify.py — grading is held out.\n"
                 "- No commits, pushes, merges, worktree ops, service "
                 "changes, package installs, or deletions.\n"
                 "- When the artifact is written, stop.")
        if arm == "l0":
            r = subprocess.run(
                [sys.executable, str(fixture_dir(fid) / "l0.py"), str(wt)],
                capture_output=True, text=True, timeout=timeout,
                env={"PATH": os.environ.get("PATH", "")})
            (rd / "stdout.log").write_text(r.stdout or "")
            (rd / "stderr.log").write_text(r.stderr or "")
            rec["exit_code"] = r.returncode
            rec["tokens"] = {"total": 0, "input": 0, "output": 0,
                             "reasoning": 0, "cache_read": 0,
                             "cache_write": 0}
            rec["tool_calls"] = []
            rec["mutating_commands"] = []
            rec["verifier_peeks"] = []
        elif arm == "opencode":
            model = model or DEFAULT_OC_MODEL
            env = dict(os.environ)
            env.update(load_arm_env(rung or "L2", model))
            cmd = ["opencode", "run", "--format", "json",
                   "--dir", str(wt), "--model", model,
                   prompt + rails]
            attempt = 0
            while True:
                attempt += 1
                try:
                    r = subprocess.run(cmd, capture_output=True,
                                       text=True, timeout=timeout,
                                       env=env, cwd=str(wt))
                    break
                except subprocess.TimeoutExpired:
                    rec["interventions"] += 1
                    if attempt > retries:
                        rec["exit_code"] = -2
                        rec["error"] = f"timeout {timeout}s"
                        r = None
                        break
                    rec["retries"] += 1
            if r is not None:
                (rd / "events.jsonl").write_text(r.stdout or "")
                (rd / "stderr.log").write_text(r.stderr or "")
                rec["exit_code"] = r.returncode
                parsed = parse_opencode_events(rd / "events.jsonl")
                rec.update(parsed)
        elif arm == "devin":
            # shadow worktrees aren't in the user's workspace-trust list;
            # print mode can't prompt, so pass the scoped CLI flag — the
            # user config is never touched.
            perm = os.environ.get("SHADOW_DEVIN_PERMISSIONS", "smart")
            rec["permission_mode"] = perm
            cmd = ["devin", "--respect-workspace-trust", "false",
                   "--permission-mode", perm,
                   "-p", prompt + rails]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=timeout, cwd=str(wt))
                (rd / "events.log").write_text(r.stdout or "")
                (rd / "stderr.log").write_text(r.stderr or "")
                rec["exit_code"] = r.returncode
                rec["tokens"] = None  # devin -p does not emit token JSON
                rec["tool_calls"] = []
                rec["mutating_commands"] = [
                    c for c in re.findall(r"(?:^|\n)\s*(.+)",
                                          r.stderr or "")
                    if MUTATING_RE.search(c)][:10]
                rec["verifier_peeks"] = []
            except subprocess.TimeoutExpired:
                rec["exit_code"] = -2
                rec["interventions"] += 1
                rec["error"] = f"timeout {timeout}s — likely waited for input"
        else:
            rec["error"] = f"unknown arm {arm}"
            rec["exit_code"] = -1
        rec["scope_violations"] = scope_violations(wt)
        rec["wall_s"] = round(time.time() - t0, 1)
        verdict = verify_run(run_id, arm, fid)
        rec["verdict"] = verdict.get("verdict")
        rec["checks"] = verdict.get("checks")
    finally:
        pass
    (rd / "run.json").write_text(json.dumps(rec, indent=1))
    return rec


def verify_run(run_id: str, arm: str, fid: str) -> dict:
    wt = run_dir(run_id, arm, fid) / "wt"
    vpath = fixture_dir(fid) / "verify.py"
    spec = importlib.util.spec_from_file_location(
        f"verify_{fid}", vpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.verify(str(wt))
    res["verified_at"] = now_iso()
    res["verifier"] = f"{fid}/verify.py"
    (run_dir(run_id, arm, fid) / "verdict.json").write_text(
        json.dumps(res, indent=1))
    return res


def cmd_run(args):
    fids = list_fixtures() if args.fixture == "all" else [args.fixture]
    arms = args.arm.split(",")
    p = probe(args.offline or "")
    results = []
    jobs = []
    for fid in fids:
        for arm in arms:
            if arm == "opencode" and not args.model:
                rt = route_fixture(fid, p)
                model = DEFAULT_OC_MODEL if rt["rung"] in (
                    "L0", "L2") else (rt.get("model") or DEFAULT_OC_MODEL)
                rung = rt["rung"] if rt["rung"] != "L0" else "L2"
            else:
                model, rung = args.model, ""
            if arm == "devin" and not args.allow_devin:
                results.append({"fixture": fid, "arm": "devin",
                                "verdict": "skipped",
                                "error": "devin arm needs --allow-devin "
                                         "(paid/nested run)"})
                continue
            jobs.append((fid, arm, model, rung))
    with cf.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(run_arm, args.run_id, fid, arm, model, rung,
                          args.timeout, args.retries): (fid, arm)
                for fid, arm, model, rung in jobs}
        for fut in cf.as_completed(futs):
            results.append(fut.result())
    results.sort(key=lambda r: (r["fixture"], r["arm"]))
    print(json.dumps({"run_id": args.run_id, "results": [
        {k: r.get(k) for k in ("fixture", "arm", "verdict", "wall_s",
                               "exit_code", "error")}
        for r in results]}, indent=1))
    return 0


# --------------------------------------------------------------- simulate

def cmd_simulate(args):
    mode = args.offline or "offline"
    os.environ["SHADOW_OFFLINE"] = "1"
    p = probe(mode)
    fids = list_fixtures()
    rows, violations = [], []

    # every fixture routes under the simulated probe
    for fid in fids:
        rt = route_fixture(fid, p)
        rung = rt["rung"]
        rdef = next(r for r in RUNGS if r["id"] == rung)
        needs_net = bool(rdef.get("net"))
        needs_sec = bool(rdef.get("secrets"))
        if needs_net or needs_sec:
            violations.append(
                f"{fid}: routed to {rung} needing net={needs_net} "
                f"secrets={needs_sec} under {mode}")
        rows.append({"task": fid, "rung": rung, "executor":
                     rdef.get("arm"), "needs_network": needs_net,
                     "needs_secrets": needs_sec})

    # synthetic task battery exercising the ladder edges
    battery = [
        ("summarize the kanban backlog", True, 60),
        ("read-only health check of this host", False, 60),
        ("refactor the dispatch pipeline across three repos", True, 9000),
        ("buy a new nvme stick for omen", False, 40),
    ]
    for text, needs_llm, nchars in battery:
        rt = route(text, p, needs_llm=needs_llm, prompt_chars=nchars)
        rdef = next(r for r in RUNGS if r["id"] == rt["rung"])
        needs_net = bool(rdef.get("net"))
        needs_sec = bool(rdef.get("secrets"))
        if (needs_net or needs_sec) and rt["rung"] != "MANUAL":
            violations.append(
                f"battery '{text[:40]}': {rt['rung']} needs "
                f"net={needs_net} secrets={needs_sec}")
        rows.append({"task": f"[synthetic] {text[:50]}",
                     "rung": rt["rung"], "executor": rdef.get("arm"),
                     "needs_network": needs_net,
                     "needs_secrets": needs_sec})

    # prove secret loader is unreachable offline
    try:
        load_arm_env("L2", "litellm/x")
        violations.append("load_arm_env did not refuse under SHADOW_OFFLINE")
    except RuntimeError:
        pass

    rep = {"mode": mode, "at": now_iso(), "host": os.uname().nodename,
           "probe": p, "routing": rows, "violations": violations,
           "verdict": "pass" if not violations else "fail"}
    REPORTS.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    out = REPORTS / f"{day}-offline-simulation-{mode}.json"
    out.write_text(json.dumps(rep, indent=1))
    lines = [f"# Offline simulation — {mode}", "",
             f"at {rep['at']} on {rep['host']}", "",
             "| task | rung | executor | needs_net | needs_secrets |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['task']} | {r['rung']} | "
                     f"{r['executor'] or '-'} | {r['needs_network']} | "
                     f"{r['needs_secrets']} |")
    lines += ["", f"verdict: **{rep['verdict'].upper()}**", ""]
    if violations:
        lines += ["## violations"] + [f"- {v}" for v in violations]
    else:
        lines.append("No rung requiring network or secrets was selected.")
    (REPORTS / f"{day}-offline-simulation-{mode}.md").write_text(
        "\n".join(lines))
    print(json.dumps({k: rep[k] for k in ("mode", "verdict",
                                          "violations")}, indent=1))
    return 0 if not violations else 1


# --------------------------------------------------------------- prestage

def cmd_prestage(args):
    STAGED.mkdir(parents=True, exist_ok=True)
    p = probe("")
    manifest = {}
    for f in sorted(FIXTURES.rglob("*")):
        if f.is_file():
            manifest[str(f.relative_to(FIXTURES))] = hashlib.sha256(
                f.read_bytes()).hexdigest()[:16]
    policy = {"offline_allowed_rungs": ["L0", "L1", "MANUAL"],
              "offline_banned": ["litellm", "wan fetches", "devin cloud",
                                 "board-api writes", "secrets loading"],
              "note": "L1 still requires a reachable loopback ollama and "
                      "a model that was pulled before going offline."}
    (STAGED / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (STAGED / "probe.json").write_text(json.dumps(p, indent=1))
    (STAGED / "models.json").write_text(json.dumps(p.get("models", {}),
                                                 indent=1))
    (STAGED / "offline-policy.json").write_text(json.dumps(policy,
                                                         indent=1))
    print(json.dumps({"staged": str(STAGED), "fixtures": len(manifest),
                      "models": p.get("models", {})}, indent=1))
    return 0


# ----------------------------------------------------------------- matrix

def cmd_matrix(args):
    p = probe(args.offline or "")
    ladder = evaluate_rungs(p)
    print(f"capability matrix — {p['host']} @ {p['at']}"
          + (f" [SIMULATED {p['simulated']}]" if p["simulated"] else ""))
    for e in ladder:
        print(f"  {e['rung']:>6}  {e['status']:<9} {e['label']}"
              f"   ({'; '.join(e['why'])})")
    (REPORTS).mkdir(exist_ok=True, parents=True)
    out = {"at": p["at"], "host": p["host"], "probe": p,
           "matrix": ladder}
    (REPORTS / "capability-matrix.json").write_text(json.dumps(out,
                                                               indent=1))
    return 0


# ----------------------------------------------------------------- report

def _load_runs(run_id: str = "") -> list:
    recs = []
    roots = [RUNS / run_id] if run_id else sorted(
        d for d in RUNS.iterdir() if d.is_dir()) if RUNS.is_dir() else []
    for root in roots:
        if not root.is_dir():
            continue
        for rd in sorted(root.iterdir()):
            rj = rd / "run.json"
            vj = rd / "verdict.json"
            if rj.is_file():
                r = json.loads(rj.read_text())
                if vj.is_file():
                    r["verdict_detail"] = json.loads(vj.read_text())
                recs.append(r)
    return recs


def cmd_report(args):
    recs = _load_runs(args.run_id)
    # recompute audits with the CURRENT code — run.json fields may have
    # been written by an older audit implementation
    for r in recs:
        rd = run_dir(r["run_id"], r["arm"], r["fixture"])
        ev = rd / "events.jsonl"
        if r["arm"] == "opencode" and ev.is_file():
            parsed = parse_opencode_events(ev)
            r.update(parsed)
        wt = rd / "wt"
        if wt.is_dir():
            r["scope_violations"] = scope_violations(wt)
    day = datetime.now().strftime("%Y-%m-%d")
    p = probe("")
    ladder = evaluate_rungs(p)
    fixtures = sorted({r["fixture"] for r in recs})
    arms = sorted({r["arm"] for r in recs})

    # impossible-without list
    impossible = []
    for e in ladder:
        if e["status"] == "BLOCKED" and e["rung"] != "MANUAL":
            impossible.append({"rung": e["rung"], "label": e["label"],
                               "why": e["why"]})
    not_run = [{"fixture": f, "arm": a}
               for f in fixtures for a in ("l0", "opencode", "devin")
               if not any(r["fixture"] == f and r["arm"] == a
                          for r in recs)]

    md = [f"# DevNest shadow benchmark — {day}", "",
          f"host: {p['host']}  runs: {len(recs)}  "
          f"fixtures: {len(fixtures)}  arms: {', '.join(arms) or '-'}",
          "", "## Fixture × arm verdicts", "",
          "| fixture | arm | verdict | wall_s | tokens | retries | "
          "interventions | scope_viol | mutating | peek |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in recs:
        tok = r.get("tokens") or {}
        md.append(
            f"| {r['fixture']} | {r['arm']} | {r.get('verdict')} | "
            f"{r.get('wall_s')} | {tok.get('total') if tok else '-'} | "
            f"{r.get('retries', 0)} | {r.get('interventions', 0)} | "
            f"{len(r.get('scope_violations') or [])} | "
            f"{len(r.get('mutating_commands') or [])} | "
            f"{len(r.get('verifier_peeks') or [])} |")
    md += ["", "## Capability matrix (live probe)", "",
           "| rung | status | label | detail |", "|---|---|---|---|"]
    for e in ladder:
        md.append(f"| {e['rung']} | {e['status']} | {e['label']} | "
                  f"{'; '.join(e['why'])} |")
    md += ["", "## Impossible without network / Devin", ""]
    for i in impossible:
        md.append(f"- {i['rung']} {i['label']}: {'; '.join(i['why'])}")
    if not_run:
        md += ["", "## Arms not yet run (fixtures × arms)", ""]
        for n in not_run:
            md.append(f"- {n['fixture']} × {n['arm']}")
    md.append("")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{day}-shadow-benchmark.md").write_text("\n".join(md))
    blob = {"at": now_iso(), "host": p["host"], "runs": recs,
            "capability_matrix": ladder, "impossible": impossible,
            "not_run": not_run}
    (REPORTS / f"{day}-shadow-benchmark.json").write_text(
        json.dumps(blob, indent=1))
    print(json.dumps({"report": str(REPORTS / f"{day}-shadow-benchmark.md"),
                      "runs": len(recs),
                      "pass": sum(1 for r in recs
                                  if r.get("verdict") == "pass")},
                     indent=1))
    return 0


# ------------------------------------------------------------------ clean

def cmd_clean(args):
    run_root = RUNS / args.run_id
    if not run_root.is_dir():
        print(f"no such run {args.run_id}")
        return 1
    removed = []
    for rd in run_root.iterdir():
        wt = rd / "wt"
        branch = f"shadow/{args.run_id}-{rd.name}"
        if wt.is_dir():
            # keep artifacts: copy task artifacts out before removing
            arts = wt / TASK_SUBDIR / "artifacts"
            if arts.is_dir():
                shutil.copytree(arts, rd / "artifacts",
                                dirs_exist_ok=True)
            _git(REPO, "worktree", "remove", "--force", str(wt))
            removed.append(str(wt))
        _git(REPO, "branch", "-D", branch)
    print(json.dumps({"removed_worktrees": removed}, indent=1))
    return 0


# -------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=
                                 argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("probe")
    sp.add_argument("--offline", choices=["offline", "airgap"], default="")

    sp = sub.add_parser("route")
    sp.add_argument("task", nargs="?", default="")
    sp.add_argument("--fixture")
    sp.add_argument("--needs-llm", action="store_true")
    sp.add_argument("--prompt-chars", type=int, default=0)
    sp.add_argument("--offline", choices=["offline", "airgap"], default="")
    sp.add_argument("--failed", default="")

    sp = sub.add_parser("matrix")
    sp.add_argument("--offline", choices=["offline", "airgap"], default="")

    sp = sub.add_parser("simulate")
    sp.add_argument("--offline", choices=["offline", "airgap"],
                    default="offline")

    sub.add_parser("prestage")

    sp = sub.add_parser("run")
    sp.add_argument("--fixture", required=True,
                    help="fixture id or 'all'")
    sp.add_argument("--arm", required=True,
                    help="l0 | opencode | devin | comma list")
    sp.add_argument("--model", default="")
    sp.add_argument("--run-id", default=datetime.now().strftime(
        "%Y%m%d-%H%M%S"))
    sp.add_argument("--timeout", type=int, default=0)
    sp.add_argument("--retries", type=int, default=0)
    sp.add_argument("--parallel", type=int, default=1)
    sp.add_argument("--allow-devin", action="store_true")
    sp.add_argument("--offline", choices=["offline", "airgap"], default="")

    sp = sub.add_parser("verify")
    sp.add_argument("--run-id", required=True)
    sp.add_argument("--arm", required=True)
    sp.add_argument("--fixture", required=True)

    sp = sub.add_parser("report")
    sp.add_argument("--run-id", default="")

    sp = sub.add_parser("clean")
    sp.add_argument("--run-id", required=True)

    args = ap.parse_args()
    if args.cmd == "probe":
        print(json.dumps(probe(args.offline), indent=1))
    elif args.cmd == "route":
        p = probe(args.offline)
        failed = [x for x in args.failed.split(",") if x]
        if args.fixture:
            print(json.dumps(route_fixture(args.fixture, p, failed),
                             indent=1))
        else:
            print(json.dumps(
                route(args.task, p, needs_llm=args.needs_llm,
                      prompt_chars=args.prompt_chars or len(args.task),
                      failed=failed), indent=1))
    elif args.cmd == "matrix":
        return cmd_matrix(args)
    elif args.cmd == "simulate":
        return cmd_simulate(args)
    elif args.cmd == "prestage":
        return cmd_prestage(args)
    elif args.cmd == "run":
        return cmd_run(args)
    elif args.cmd == "verify":
        print(json.dumps(verify_run(args.run_id, args.arm, args.fixture),
                         indent=1))
    elif args.cmd == "report":
        return cmd_report(args)
    elif args.cmd == "clean":
        return cmd_clean(args)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
