#!/usr/bin/env python3
"""nest-train-loop.py — Nest micro-model evolution loop owner.

Closes the corpus -> candidate -> bench -> gate -> promotion-question
cycle for the confirm-gate specialist (card nest-micro-training;
spec: docs/ssot/infrastructure/ssot.nest-training.yml). All stages are
T1-safe: the loop never deploys, never restarts prod, never edits the
model registry. When the gate passes it posts a board request — the
shadow deploy is a human decision (same posture as the CAM++ speaker
shadow and the client_noul edge lane).

Stages:

  harvest   pull corpus rows over ssh into the workdir —
              idc03:~/.local/share/ada/jev-corpus.jsonl   (live, post-
                                                          migration)
              idc01:~/.local/share/ada/jev-corpus{,-mined,-reviewed}.jsonl
                                              (pre-migration archive)
            concat'd so ada-pi merge-corpus.py dedupes across hosts.
            Diverged/unlabeled rows are counted and reported as the
            pending-label queue (merge policy drops them from training).
  merge     ada-pi scripts/jev/merge-corpus.py + augment-corpus.py
            -> workdir/corpus.json   [{text,label}] trainer input
  train     JEV_CORPUS=corpus.json JEV_OUT=<ckpt> $VENV python
            ada-pi/scripts/train-jev-student.py on the GTX1650 lane
  serve     candidate on 127.0.0.1:PORT via JEV_CKPT env + uvicorn
            (serve-jev-student.py), killed on exit — OR on a --lane:
            runtime onnx-cpu/openvino -> serve-jev-student-onnx.py on
            the lane host (local subprocess, or rsync+ssh when the lane
            is remote); the torch/uvicorn path is the GTX1650 default
            and stays untouched
  bench     ada-pi orch-bench.py --sets <suite tiers> --structure student
            vs champ endpoint AND candidate endpoint, --json-out both;
            with --lane the candidate endpoint is the lane's, and the
            bench doc carries the lane tag + a latency block
  gate      candidate_ok >= champ_ok on EVERY tier set (golden, hard,
            adversarial) — suites.yml 'gate' block
  publish   bench/train-<ts> doc -> mddb ada-ha-scenario-reports
            (kind:benchmark), the same shape jev-bench writes
  queue     POST board-api /request on the owning card when the gate
            passes, with the per-tier diff and the proposed registry
            entry (status: shadow)

Env overrides:
  ADA_PI      ada-pi checkout containing tests/bench + scripts/jev
              (default ~/CascadeProjects/ada-pi — needs the
              nest-micro-training branch merged for suites.yml/adv sets)
  VENV_PY     python with torch/transformers (default
              ~/CascadeProjects/open-jev/.venv/bin/python)
  CHAMP       incumbent endpoint (default http://idc03.taila0626a.ts.net:8778)
  CORPUS_LIVE / CORPUS_ARCHIVE   ssh hosts (default idc03 / idc01)
  MDDB        mddb base (default http://100.102.134.91:11023/v1)
  BOARD_API   board api base (default https://tony-dell.../apps/board-api)
  CARD        owning card id (default nest-micro-training)
  CAND_HOME   candidate ckpt dir root (default ~/jev-student-candidates)
  STATE       loop state file (default ~/.local/share/nest/train-loop-state.json)

Usage:
  nest-train-loop.py                     # full loop
  nest-train-loop.py --harvest-only      # harvest + merge, stop
  nest-train-loop.py --ckpt DIR          # skip train, bench existing ckpt
  nest-train-loop.py --no-publish        # skip mddb doc + board request
  nest-train-loop.py --suite NAME        # default confirm-gate
  nest-train-loop.py --lane NAME         # serve+bench candidate on a
                                         # topologies.yml lanes: entry
  nest-train-loop.py lanes               # list the lane registry
  nest-train-loop.py lane-bench --lane NAME --model DIR
      # serve an existing ONNX export on the lane, run the suite tiers
      # + a --probe N latency probe, publish bench/lane-<ts> — the
      # acceptance path for new lanes (card nest-lane-tony-dell)

Lane entries live in ada-pi tests/bench/topologies.yml `lanes:`. Serve-
capable lanes add: runtime (onnx-cpu|openvino|torch-local), ssh (how a
remote loop host reaches it — omit/absent when same-host), tailnet,
serve_port, python, models_dir.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

HOME = Path.home()
ADA_PI = Path(os.environ.get("ADA_PI", HOME / "CascadeProjects/ada-pi"))
VENV_PY = os.environ.get(
    "VENV_PY", str(HOME / "CascadeProjects/open-jev/.venv/bin/python"))
CHAMP = os.environ.get(
    "CHAMP", "http://idc03.taila0626a.ts.net:8778").rstrip("/")
CORPUS_LIVE = os.environ.get("CORPUS_LIVE", "idc03")
CORPUS_ARCHIVE = os.environ.get("CORPUS_ARCHIVE", "idc01")
MDDB = os.environ.get("MDDB", "http://100.102.134.91:11023/v1").rstrip("/")
BOARD_API = os.environ.get(
    "BOARD_API",
    "https://tony-dell.taila0626a.ts.net/apps/board-api").rstrip("/")
CARD = os.environ.get("CARD", "nest-micro-training")
CAND_HOME = Path(os.environ.get("CAND_HOME", HOME / "jev-student-candidates"))
STATE = Path(os.environ.get(
    "STATE", HOME / ".local/share/nest/train-loop-state.json"))
SERVE_PORT = int(os.environ.get("SERVE_PORT", "8878"))
ADA_CORPUS_DIR = "~/.local/share/ada"
# suite tier fallback when suites.yml isn't on the ada-pi checkout yet
SUITE_SETS_FALLBACK = {"confirm-gate": ["golden", "hard", "adv-confirm"]}


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ssh_cat(host: str, path: str) -> str:
    r = sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            host, f"cat {path} 2>/dev/null"])
    return r.stdout if r.returncode == 0 else ""


def post(url: str, payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2) + "\n")


def suite_sets(suite: str) -> list[str]:
    """Tier set names for a specialist — suites.yml on the ada-pi
    checkout, falling back to the built-in confirm-gate list."""
    path = ADA_PI / "tests/bench/suites.yml"
    try:
        data = yaml.safe_load(path.read_text()) or {}
        tiers = ((data.get("suites") or {}).get(suite) or {}).get("tiers") or {}
        sets = [c["set"] for c in tiers.values()
                if isinstance(c, dict) and c.get("set")]
        if sets:
            return sets
    except Exception:
        pass
    return SUITE_SETS_FALLBACK.get(suite, [])


# ---------- lanes ----------------------------------------------------------
# Serve-capable lane entries live in ada-pi tests/bench/topologies.yml
# `lanes:` — a lane is where a candidate gets SERVED for benching, not
# trained. Extra fields beyond host/good_for/watch/cadence:
#   runtime     onnx-cpu | openvino:<dev> | llamacpp | torch-local
#   ssh         ssh target a remote loop host uses (omit for same-host)
#   tailnet     tailscale ip/name the served endpoint binds remotely
#   serve_port  port for the lane server (default SERVE_PORT)
#   python      interpreter with the lane runtime on the lane host
#   models_dir  where model dirs are rsync'd on the lane host
THIS_HOST = socket.gethostname().split(".")[0]


def lanes_registry() -> dict:
    try:
        data = yaml.safe_load(
            (ADA_PI / "tests/bench/topologies.yml").read_text()) or {}
        return data.get("lanes") or {}
    except Exception:
        return {}


def lane_def(name: str) -> dict:
    lanes = lanes_registry()
    if name not in lanes:
        raise SystemExit(
            f"unknown lane '{name}' — registry: {sorted(lanes)} "
            f"({ADA_PI}/tests/bench/topologies.yml)")
    d = dict(lanes[name] or {})
    d.setdefault("runtime", "torch-local")
    d.setdefault("serve_port", SERVE_PORT)
    return d


def lane_is_local(lane: dict) -> bool:
    """A lane is local when it has no ssh target or names this host."""
    if not lane.get("ssh"):
        return True
    return str(lane.get("host", "")).split(".")[0] == THIS_HOST


def _wait_health(url: str, proc=None, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError("lane server exited before health")
        try:
            urllib.request.urlopen(f"{url}/health", timeout=2).read()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"lane server never became healthy: {url}")


def serve_onnx_lane(model_dir: Path, lane: dict, lane_name: str):
    """Serve an ONNX export on a lane -> (endpoint, stop_fn).

    Local lane: subprocess of serve-jev-student-onnx.py bound loopback.
    Remote lane: rsync model + script to lane.models_dir, spawn via ssh
    bound to the lane's tailnet IP (never LAN), endpoint over tailnet.
    """
    runtime = str(lane.get("runtime", "onnx-cpu"))
    port = int(lane.get("serve_port", SERVE_PORT))
    script = ADA_PI / "scripts/serve-jev-student-onnx.py"
    provider = ("cpu" if runtime == "onnx-cpu" else
                runtime if runtime.startswith("openvino") else "cpu")
    if runtime == "llamacpp":
        raise SystemExit(
            "llamacpp lanes serve gemma-class models via llama.cpp-server "
            "(see topologies.yml lane notes) — not wired for seq-cls ONNX; "
            "use an onnx-cpu lane for jev-student-class checkpoints")

    if lane_is_local(lane):
        py = os.path.expanduser(str(lane.get("python") or sys.executable))
        proc = subprocess.Popen(
            [py, str(script), "--model", str(model_dir),
             "--host", "127.0.0.1", "--port", str(port),
             "--provider", provider],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        endpoint = f"http://127.0.0.1:{port}"
        try:
            _wait_health(endpoint, proc)
        except Exception:
            proc.kill()
            raise
        print(f"[serve] {lane_name} local onnx on :{port} "
              f"({runtime})")

        def stop():
            proc.terminate()
        return endpoint, stop

    ssh = str(lane["ssh"])
    tail = str(lane.get("tailnet") or lane.get("host"))
    models_dir = str(lane.get("models_dir") or "~/nest-lane/models")
    py = str(lane.get("python") or "python3")
    remote_model = f"{models_dir}/{model_dir.name}"
    for cmd in (
        ["ssh", "-o", "BatchMode=yes", ssh,
         f"mkdir -p {models_dir} ~/nest-lane/bin"],
        ["rsync", "-a", "--delete", f"{model_dir}/",
         f"{ssh}:{remote_model}/"],
        ["scp", "-q", str(script), f"{ssh}:~/nest-lane/bin/"],
    ):
        r = sh(cmd)
        if r.returncode != 0:
            raise RuntimeError(f"{cmd[0]} to {ssh} failed: "
                               f"{r.stderr[-300:]}")
    # kill any stale server on the port, then spawn detached
    sh(["ssh", "-o", "BatchMode=yes", ssh,
        f"pkill -f 'serve-jev-student-onnx.*--port {port}' 2>/dev/null; "])
    r = sh(["ssh", "-o", "BatchMode=yes", ssh,
            f"nohup {py} ~/nest-lane/bin/serve-jev-student-onnx.py "
            f"--model {remote_model} --host {tail} --port {port} "
            f"--provider {provider} "
            f"> ~/nest-lane/serve-{port}.log 2>&1 < /dev/null & "
            "echo spawned"])
    if r.returncode != 0:
        raise RuntimeError(f"ssh spawn on {ssh} failed: {r.stderr[-300:]}")
    endpoint = f"http://{tail}:{port}"
    _wait_health(endpoint)
    print(f"[serve] {lane_name} remote onnx on {endpoint} ({runtime})")

    def stop():
        sh(["ssh", "-o", "BatchMode=yes", ssh,
            f"pkill -f 'serve-jev-student-onnx.*--port {port}'"])
    return endpoint, stop


def export_onnx(ckpt: Path, out: Path) -> Path:
    """HF ckpt -> ONNX dir via the torch venv's transformers.onnx.
    Needed when a lane serves a trained candidate (torch ckpt) — lane
    hosts have no torch, so the export happens on the loop host."""
    if (out / "model.onnx").exists():
        return out
    out.mkdir(parents=True, exist_ok=True)
    r = sh([VENV_PY, "-m", "transformers.onnx",
            f"--model={ckpt}", "--feature=sequence-classification",
            str(out)], timeout=900)
    if r.returncode != 0 or not (out / "model.onnx").exists():
        raise RuntimeError(
            "onnx export failed — provide a dir with model.onnx + "
            f"tokenizer.json via --model instead:\n"
            f"{(r.stdout + r.stderr)[-600:]}")
    for f in ("tokenizer.json", "tokenizer_config.json", "config.json"):
        src = ckpt / f
        if src.exists() and not (out / f).exists():
            (out / f).write_bytes(src.read_bytes())
    print(f"[export] {ckpt.name} -> {out}")
    return out


def probe(endpoint: str, n: int, out: Path) -> dict:
    r = sh([sys.executable, str(ADA_PI / "tests/bench/lane-probe.py"),
            "--url", endpoint, "--n", str(n), "--json-out", str(out)],
           timeout=600)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"lane-probe failed on {endpoint}:\n"
                           f"{(r.stdout + r.stderr)[-400:]}")
    res = json.loads(out.read_text())
    print(f"[probe] {endpoint}: p50={res['p50_ms']}ms "
          f"p95={res['p95_ms']}ms n={res['n']} errors={res['errors']}")
    return res


# ---------- stages ---------------------------------------------------------

def harvest(work: Path) -> dict:
    live_new = ssh_cat(CORPUS_LIVE, f"{ADA_CORPUS_DIR}/jev-corpus.jsonl")
    live_old = ssh_cat(CORPUS_ARCHIVE, f"{ADA_CORPUS_DIR}/jev-corpus.jsonl")
    mined = ssh_cat(CORPUS_ARCHIVE, f"{ADA_CORPUS_DIR}/jev-corpus-mined.jsonl")
    reviewed = ssh_cat(
        CORPUS_ARCHIVE, f"{ADA_CORPUS_DIR}/jev-corpus-reviewed.jsonl")

    live_rows = [l for l in (live_new + live_old).splitlines() if l.strip()]
    (work / "jev-corpus.jsonl").write_text("\n".join(live_rows) + "\n")
    (work / "jev-corpus-mined.jsonl").write_text(mined)
    (work / "jev-corpus-reviewed.jsonl").write_text(reviewed)

    seen, ded = set(), []
    diverged = 0
    for l in live_rows:
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        k = " ".join(r.get("text", "").lower().split())
        if k and k not in seen:
            seen.add(k)
            ded.append(r)
        if r.get("diverged"):
            diverged += 1
    st = load_state()
    prev = int(st.get("corpus_rows", 0))
    info = {"live_rows_raw": len(live_rows), "live_rows_dedup": len(ded),
            "live_rows_new_since_last_run": max(0, len(live_rows) - prev),
            "diverged_pending_label": diverged,
            "mined_rows": len([l for l in mined.splitlines() if l.strip()]),
            "reviewed_rows": len([l for l in reviewed.splitlines() if l.strip()])}
    st["corpus_rows"] = len(live_rows)
    save_state(st)
    print(f"[harvest] {info}")
    return info


def merge(work: Path) -> dict:
    jevdir = ADA_PI / "scripts/jev"
    for script, arg in ((jevdir / "merge-corpus.py", str(work)),
                        (jevdir / "augment-corpus.py",
                         str(work / "augment.jsonl"))):
        r = sh([sys.executable, str(script), arg])
        if r.returncode != 0:
            raise RuntimeError(f"{script.name} failed: {r.stderr[-400:]}")
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
    rows = [json.loads(l) for l in
            (work / "corpus-merged.jsonl").read_text().splitlines()
            if l.strip()]
    rows += [json.loads(l) for l in
             (work / "augment.jsonl").read_text().splitlines() if l.strip()]
    out = [{"text": r["text"], "label": bool(r["label"])} for r in rows]
    (work / "corpus.json").write_text(json.dumps(out, ensure_ascii=False))
    stats = json.loads((work / "corpus-stats.json").read_text())
    stats["train_rows_total"] = len(out)
    print(f"[merge] train corpus {len(out)} rows "
          f"({stats.get('pos', stats.get('train_pos', '?'))} pos)")
    return stats


def train(work: Path, ckpt: Path) -> dict:
    env = dict(os.environ, JEV_CORPUS=str(work / "corpus.json"),
               JEV_OUT=str(ckpt))
    r = sh([VENV_PY, str(ADA_PI / "scripts/train-jev-student.py")],
           env=env, timeout=3600)
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-12:])
    print(f"[train] rc={r.returncode}\n{tail}")
    if r.returncode != 0 or not (ckpt / "config.json").exists():
        raise RuntimeError("training failed — see output above")
    m = re.search(r"val: n=(\d+) acc=([\d.]+) thr=([\d.]+) "
                  r"prec=([\d.]+) rec=([\d.]+)", r.stdout)
    g = re.search(r"golden confirm: (\d+)/(\d+)", r.stdout)
    return {"val_acc": float(m.group(2)) if m else None,
            "thr": float(m.group(3)) if m else None,
            "golden_sanity": g.group(0) if g else None}


def serve(ckpt: Path, port: int) -> subprocess.Popen:
    launcher = (
        "import importlib.util, os, uvicorn\n"
        f"os.environ['JEV_CKPT'] = {str(ckpt)!r}\n"
        "spec = importlib.util.spec_from_file_location("
        f" 'serve_jev_student', {str(ADA_PI / 'scripts/serve-jev-student.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"uvicorn.run(m.app, host='127.0.0.1', port={port}, log_level='error')\n")
    proc = subprocess.Popen([VENV_PY, "-c", launcher],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("candidate server exited before health")
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2).read()
            print(f"[serve] candidate live on :{port}")
            return proc
        except Exception:
            time.sleep(2)
    proc.kill()
    raise RuntimeError("candidate server never became healthy")


def bench(endpoint: str, sets: list[str], out: Path) -> dict:
    r = sh([sys.executable, str(ADA_PI / "tests/bench/orch-bench.py"),
            "--structure", "student", "--sets", ",".join(sets),
            "--student", endpoint, "--json-out", str(out)],
           timeout=1200)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"orch-bench failed on {endpoint}:\n"
                           f"{(r.stdout + r.stderr)[-800:]}")
    res = json.loads(out.read_text())["results"][0]
    print(f"[bench] {endpoint}: {res['score']} {res['per_set']} "
          f"p50={res['p50_s']}s ece={res['ece']}")
    return res


def gate(champ: dict, cand: dict, sets: list[str]) -> tuple[bool, dict]:
    """candidate_ok >= champ_ok on every tier set (suites.yml gate)."""
    def ok(res, s):
        a, b = (res["per_set"].get(s) or "0/0").split("/")
        return int(a), int(b)
    diff = {s: {"champ": ok(champ, s)[0], "cand": ok(cand, s)[0],
                "n": ok(champ, s)[1]} for s in sets}
    passed = all(d["cand"] >= d["champ"] for d in diff.values())
    # regressions: cases champ got right that the candidate now misses
    champ_ok = {r["text"] for r in champ["rows"] if r["ok"]}
    regressions = [r["text"] for r in cand["rows"]
                   if not r["ok"] and r["text"] in champ_ok]
    if regressions:
        passed = False
    diff["_regressions"] = regressions
    return passed, diff


def publish(work: Path, suite: str, cand_name: str, stats: dict,
            champ: dict, cand: dict, passed: bool, diff: dict,
            train_info: dict, lane: str = "", lat: dict = None) -> str:
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d-%H%M%S")
    tiers = "\n".join(
        f"| {s} | {d['champ']}/{d['n']} | {d['cand']}/{d['n']} | "
        f"{'pass' if d['cand'] >= d['champ'] else 'REGRESSED'} |"
        for s, d in diff.items() if not s.startswith("_"))
    regs = diff.get("_regressions") or []
    reg_lines = "".join(f"\n- `{t[:90]}`" for t in regs[:15])
    md = f"""# Train-loop run — {cand_name} vs champ ({now:%Y-%m-%d %H:%M})

**Gate: {'PASS — shadow-pending' if passed else 'FAIL'}** (suites.yml
promotion rule: candidate >= champ on every tier, zero regressions)

| tier set | champ | candidate | verdict |
|---|---|---|---|
{tiers}

- candidate: `{cand_name}` corpus `{stats.get('total')} merged + aug`
  (train rows {stats.get('train_rows_total')})
- champ: `{CHAMP}` · candidate val: {train_info.get('val_acc')} acc @
  thr {train_info.get('thr')}
- latency p50: champ {champ['p50_s']}s / cand {cand['p50_s']}s
  {f"(lane `{lane}` — probe p50 {lat['p50_ms']}ms p95 {lat['p95_ms']}ms n={lat['n']})" if lat else ""}
- ECE: champ {champ['ece']} / cand {cand['ece']}
- corpus delta: {stats.get('_harvest', {})}
- regressions (cases the champ wins that the candidate loses):{reg_lines or ' none'}

Next: {'board request queued — shadow deploy needs a human yes'
       if passed else 'candidate archived; corpus keeps growing'}.
"""
    key = f"bench/train-{ts}"
    if ARGS.no_publish:
        print(f"[publish] skipped (--no-publish) — would write {key}")
        (work / "report.md").write_text(md)
        return key
    post(f"{MDDB}/add", {
        "collection": "ada-ha-scenario-reports", "key": key, "lang": "en",
        "contentMd": md,
        "meta": {"kind": ["benchmark"], "suite": ["nest-train-loop"],
                 "engine": ["jev-student"], "candidate": [cand_name],
                 "lane": [lane] if lane else [],
                 "gate": ["pass" if passed else "fail"],
                 "score": [f"{cand['acc']:.4f}"],
                 "champ_score": [f"{champ['acc']:.4f}"],
                 "ts": [now.isoformat(timespec="seconds")]}})
    print(f"[publish] {key}")
    return key


def publish_lane(suite: str, lane_name: str, lane: dict,
                 model_name: str, endpoint: str, res: dict,
                 lat: dict) -> str:
    """bench/lane-<ts> doc — a lane's serve+bench baseline.
    Same MDDB collection + kind:benchmark as train docs; the json fence
    is what bench-edge-cms.py parses for the lanes table."""
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d-%H%M%S")
    tiers = "\n".join(
        f"| {s} | {res['per_set'].get(s, '—')} |"
        for s in sorted(res.get("per_set") or {}))
    payload = {
        "lane": lane_name, "host": lane.get("host"), "runtime": lane.get("runtime"),
        "model": model_name, "endpoint": endpoint, "suite": suite,
        "ts": now.isoformat(timespec="seconds"),
        "acc": res.get("acc"), "score": res.get("score"),
        "per_set": res.get("per_set"), "ece": res.get("ece"),
        "bench_p50_s": res.get("p50_s"), "bench_p95_s": res.get("p95_s"),
        "bench_cpu_per_call_s": res.get("cpu_per_call"),
        "probe": lat,
    }
    md = f"""# Lane bench — {lane_name} · {model_name} ({now:%Y-%m-%d %H:%M})

Serve-bench of `{model_name}` on lane **{lane_name}**
(host `{lane.get('host')}`, runtime `{lane.get('runtime')}`,
endpoint `{endpoint}`).

## Suite `{suite}` — accuracy

| tier set | ok/n |
|---|---|
{tiers}

- overall: **{res.get('score')}** (acc {res.get('acc'):.3f}), ECE {res.get('ece')}
- bench p50 {res.get('p50_s')}s / p95 {res.get('p95_s')}s
  (server-reported cpu/call {res.get('cpu_per_call')}s)

## Latency — {lat.get('n')}-call probe

| p50 | p95 | mean | min | max | errors | rps |
|---|---|---|---|---|---|---|
| {lat.get('p50_ms')}ms | {lat.get('p95_ms')}ms | {lat.get('mean_ms')}ms | {lat.get('min_ms')}ms | {lat.get('max_ms')}ms | {lat.get('errors')} | {lat.get('throughput_rps')} |

```json
{json.dumps(payload, indent=2)}
```

_Generated by nest-train-loop.py lane-bench — lane registry:
ada-pi tests/bench/topologies.yml `lanes:`._
"""
    key = f"bench/lane-{ts}"
    if ARGS.no_publish:
        print(f"[publish] skipped (--no-publish) — would write {key}")
        return key
    post(f"{MDDB}/add", {
        "collection": "ada-ha-scenario-reports", "key": key, "lang": "en",
        "contentMd": md,
        "meta": {"kind": ["benchmark"], "suite": [suite],
                 "engine": ["jev-student-onnx"], "lane": [lane_name],
                 "host": [str(lane.get("host"))],
                 "runtime": [str(lane.get("runtime"))],
                 "model": [model_name],
                 "score": [f"{res.get('acc'):.4f}"],
                 "p50_ms": [str(lat.get("p50_ms"))],
                 "p95_ms": [str(lat.get("p95_ms"))],
                 "ts": [now.isoformat(timespec="seconds")]}})
    print(f"[publish] {key}")
    return key


def lane_bench() -> int:
    """serve+bench an ONNX model on a registered lane — the lane
    acceptance path (card nest-lane-tony-dell). Publishes
    bench/lane-<ts> unless --no-publish."""
    lane = lane_def(ARGS.lane)
    model_dir = Path(ARGS.model).expanduser() if ARGS.model else None
    if not model_dir or not (model_dir / "model.onnx").exists():
        raise SystemExit("lane-bench needs --model DIR with model.onnx "
                         "(+ tokenizer.json, config.json)")
    model_name = model_dir.name
    sets = suite_sets(ARGS.suite)
    if not sets:
        print(f"no bench sets for suite {ARGS.suite}", file=sys.stderr)
        return 2
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    work = Path(ARGS.work or f"/tmp/nest-lane-{ts}")
    work.mkdir(parents=True, exist_ok=True)

    endpoint, stop = serve_onnx_lane(model_dir, lane, ARGS.lane)
    try:
        res = bench(endpoint, sets, work / "lane.json")
        lat = probe(endpoint, ARGS.probe, work / "probe.json")
    finally:
        stop()
    key = publish_lane(ARGS.suite, ARGS.lane, lane, model_name,
                       endpoint, res, lat)
    print(f"[lane-bench] {ARGS.lane}: {res['score']} acc "
          f"p50={lat['p50_ms']}ms p95={lat['p95_ms']}ms -> {key}")
    return 0


def queue_promotion(cand_name: str, ckpt: Path, doc_key: str,
                    diff: dict) -> None:
    ask = (f"nest-train-loop: candidate {cand_name} meets the promotion "
           f"gate ({doc_key}). Approve shadow deploy? ckpt={ckpt} "
           f"diff={json.dumps({k: v for k, v in diff.items() if not k.startswith('_')})}")
    try:
        post(f"{BOARD_API}/request",
             {"id": CARD, "from": "nest-train-loop", "ask": ask})
        print(f"[queue] promotion request posted on {CARD}")
    except Exception as exc:
        print(f"[queue] board request failed ({exc}) — doc {doc_key} "
              "still carries the gate result", file=sys.stderr)


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("command", nargs="?", default="loop",
                    choices=["loop", "lane-bench", "lanes"],
                    help="loop = full corpus->gate cycle; lane-bench = "
                         "serve+bench an ONNX model on a lane; "
                         "lanes = print the lane registry")
    ap.add_argument("--suite", default="confirm-gate")
    ap.add_argument("--lane", default="",
                    help="topologies.yml lanes: entry to serve+bench the "
                         "candidate on (onnx-cpu/openvino runtimes)")
    ap.add_argument("--model", default="",
                    help="lane-bench: dir with model.onnx + tokenizer.json")
    ap.add_argument("--probe", type=int, default=200,
                    help="lane latency probe calls (lane-bench / --lane)")
    ap.add_argument("--harvest-only", action="store_true")
    ap.add_argument("--ckpt", default="", help="existing ckpt — skips train")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--work", default="")
    ARGS = ap.parse_args()

    if ARGS.command == "lanes":
        for name, d in lanes_registry().items():
            print(f"{name:24s} host={d.get('host', '-')} "
                  f"runtime={d.get('runtime', 'torch-local')} "
                  f"status={d.get('status', 'active')}")
        return 0
    if ARGS.command == "lane-bench":
        if not ARGS.lane:
            raise SystemExit("lane-bench needs --lane NAME")
        return lane_bench()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    work = Path(ARGS.work or f"/tmp/nest-train-{ts}")
    work.mkdir(parents=True, exist_ok=True)
    print(f"workdir: {work}")

    info = harvest(work)
    stats = merge(work)
    stats["_harvest"] = info
    if ARGS.harvest_only:
        return 0

    st = load_state()
    iteration = int(st.get("iteration", 5)) + 1      # champ is v5
    cand_name = f"jev-student-v{iteration}-cand-{ts}"
    ckpt = Path(ARGS.ckpt) if ARGS.ckpt else \
        CAND_HOME / cand_name
    train_info = {}
    if not ARGS.ckpt:
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        train_info = train(work, ckpt)

    sets = suite_sets(ARGS.suite)
    if not sets:
        print(f"no bench sets for suite {ARGS.suite}", file=sys.stderr)
        return 2

    champ = bench(CHAMP, sets, work / "champ.json")
    lat = None
    if ARGS.lane:
        # lane serve+bench: onnx-class runtimes need an onnx export of
        # the candidate — exported on the loop host (torch venv) and
        # shipped to the lane
        lane = lane_def(ARGS.lane)
        model_dir = (ckpt if (ckpt / "model.onnx").exists()
                     else export_onnx(ckpt, work / "onnx"))
        endpoint, stop = serve_onnx_lane(model_dir, lane, ARGS.lane)
        try:
            cand = bench(endpoint, sets, work / "candidate.json")
            lat = probe(endpoint, ARGS.probe, work / "lane-probe.json")
        finally:
            stop()
    else:
        proc = serve(ckpt, SERVE_PORT)
        try:
            cand = bench(f"http://127.0.0.1:{SERVE_PORT}", sets,
                         work / "candidate.json")
        finally:
            proc.terminate()

    passed, diff = gate(champ, cand, sets)
    print(f"[gate] {'PASS' if passed else 'FAIL'} — {diff}")

    doc_key = publish(work, ARGS.suite, cand_name, stats, champ, cand,
                      passed, diff, train_info, lane=ARGS.lane, lat=lat)
    if passed:
        queue_promotion(cand_name, ckpt, doc_key, diff)
    st.update({"iteration": iteration, "last_run": ts,
               "last_gate": "pass" if passed else "fail",
               "last_doc": doc_key})
    save_state(st)
    # a gate FAIL is a normal outcome, not a run failure — the doc and
    # state carry the verdict; non-zero is reserved for actual errors
    return 0


if __name__ == "__main__":
    sys.exit(main())
