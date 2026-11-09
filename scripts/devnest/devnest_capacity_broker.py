#!/usr/bin/env python3
"""Route explicit DevNest task specs to eligible worker inboxes.

This is deliberately a broker, not a task generator. Upstream producers place
normalized JSON specs in the shared inbox. The broker routes KK-Mac work when
its admission gate is green and stages complete Colab packs without launching
or stopping a runtime.

Normalized spec envelope (all fields the capacity loop promises):
  task_id     safe slug, matches the inbox filename stem
  task_class  bounded class; kk_mac_local admits summary/operator_brief/
              structured_extract/safe_route only
  evidence    source the task is grounded on (path/ref) — evidence or
              prompt is required, preferably both
  lane        kk_mac_local | colab
  model       executor model (default qwen3:8b for kk_mac_local)
  expect      verifier contract {required_keys,enums,facts} (default {})
  artifact    durable repo-relative artifact path (allowed roots only)
  timeout_s   execution bound, clamped to (0, 3600], default 600
  fallback    where the task goes when this lane can't serve it
              (default: hold for JevTeam)

Each cycle also OBSERVES both lanes — KK admission snapshot, KK queue
depth, Colab queue heartbeat/runtime-sessions/pending packs/JOBS.py
drift — and appends one record to the capacity ledger at
<devnest>/capacity/<utc-ts>-<rand>.json. Recording is best-effort and
never blocks routing; routing is never synthetic.

Colab staging is sealed: pack_source is validated against the
nest-pack-submit contract, copied, verified with `rclone check`, and
closed with a manifest-hash `ready` marker so a runtime snapshotting
inventory mid-copy never claims a partial pack. The broker never
launches a runtime and never duplicates a runner.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .kk_mac_admission import snapshot
else:
    from kk_mac_admission import snapshot

_REPO = Path(__file__).resolve().parents[2]


def _load_file_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


npr = _load_file_module(
    "nest_pack_ready", _REPO / "scripts" / "ada" / "nest_pack_ready.py")
_pack_submit = _load_file_module(
    "nest_pack_submit", _REPO / "scripts" / "ada" / "nest-pack-submit.py")

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
LANES = {"kk_mac_local", "colab"}
KK_CLASSES = {"summary", "operator_brief", "structured_extract", "safe_route"}
KK_DEFAULT_MODEL = "qwen3:8b"
# artifact roots the kk lane may durably write — mirrors
# kk_mac_executor.ARTIFACT_ROOTS (no scripts/, secrets, executables)
ARTIFACT_ROOTS = ("evals/kk-mac-lane/out/", "reports/", "docs/reports/")
DEVNEST_REMOTE = "gdrive:ada-nest/devnest"
KK_LLM_REMOTE = "gdrive:ada-nest/kk-llm"
COLAB_REMOTE = "gdrive:ada-nest"
MAX_ROUTE_PER_CYCLE = 10
RUNTIME_TTL_S = 300


def rc(*args: str, input_text: str | None = None) -> str:
    p = subprocess.run(
        ["rclone", *args], input=input_text, text=True,
        capture_output=True, timeout=90,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:300] or "rclone failed")
    return p.stdout


def inbox(remote: str) -> list[str]:
    return sorted(
        x for x in rc("lsf", f"{remote}/inbox", "--files-only").splitlines()
        if x.endswith(".json")
    )


def queue_depth(remote: str) -> int:
    # One recursive listing avoids one remote API call per historical pack.
    entries = rc("lsf", f"{remote}/packs", "--recursive").splitlines()
    packs = {line.split("/", 1)[0] for line in entries if line.strip()}
    terminal = {
        line.split("/", 1)[0]
        for line in entries
        if line.endswith("/done") or line.endswith("/failed")
    }
    return len(packs - terminal)


def _artifact_allowed(path: str) -> bool:
    p = (path or "").strip().lstrip("/")
    if not p or ".." in p.split("/") or p.startswith("/"):
        return False
    return any(p == r.rstrip("/") or p.startswith(r)
               for r in ARTIFACT_ROOTS)


def normalize_spec(spec: dict, filename: str) -> dict:
    """Validate + fill the full normalized envelope. Raises ValueError on
    any contract violation — malformed specs are rejected, never repaired
    silently."""
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    task_id = str(spec.get("task_id", ""))
    if not SLUG.fullmatch(task_id):
        raise ValueError("task_id must be a safe slug")
    # filename stem is the routing identity — a spec claiming a different
    # task_id than its file is ambiguous (dedupe/markers key on stem)
    stem = filename[:-5] if filename.endswith(".json") else filename
    if stem != task_id:
        raise ValueError(f"task_id {task_id!r} != filename stem {stem!r}")
    lane = spec.get("lane")
    if lane not in LANES:
        raise ValueError("lane must be kk_mac_local or colab")
    task_class = str(spec.get("task_class") or "")
    if not task_class:
        raise ValueError("task_class is required")
    if lane == "kk_mac_local" and task_class not in KK_CLASSES:
        raise ValueError(f"KK task class not admitted: {task_class}")
    prompt = str(spec.get("prompt") or "")
    evidence = str(spec.get("evidence") or spec.get("source") or "")
    if not prompt.strip() and not evidence.strip():
        raise ValueError("evidence or prompt is required")
    if lane == "kk_mac_local":
        if not prompt.strip():
            raise ValueError("KK task requires prompt")
        if len(prompt) > 6000:
            raise ValueError("prompt exceeds 6000 characters")
    expect = spec.get("expect") or {}
    if not isinstance(expect, dict):
        raise ValueError("expect must be an object")
    artifact = spec.get("artifact")
    if artifact is not None and not _artifact_allowed(str(artifact)):
        raise ValueError(f"artifact outside allowed roots: {artifact}")
    try:
        raw_timeout = spec.get("timeout_s")
        if raw_timeout is None:
            raw_timeout = spec.get("timeout")
        timeout_s = int(600 if raw_timeout is None else raw_timeout)
    except (TypeError, ValueError):
        raise ValueError("timeout_s must be int seconds")
    if not 0 < timeout_s <= 3600:
        raise ValueError("timeout_s out of bounds (0, 3600]")
    fallback = spec.get("fallback")
    if fallback is not None and not isinstance(fallback, (str, dict)):
        raise ValueError("fallback must be a string or object")
    out = dict(spec)
    out.update({
        "task_id": task_id, "lane": lane, "task_class": task_class,
        "prompt": prompt, "evidence": evidence or None,
        "model": str(spec.get("model") or
                     (KK_DEFAULT_MODEL if lane == "kk_mac_local" else "")) or None,
        "expect": expect, "artifact": artifact,
        "timeout_s": timeout_s,
        "fallback": fallback if fallback is not None
                    else {"lane": "jevteam_hold"},
    })
    return out


def mark_routed(remote: str, filename: str, destination: str) -> None:
    rc(
        "rcat", f"{remote}/inbox/{filename}.routed",
        input_text=json.dumps({"destination": destination}) + "\n",
    )


def route_kk(
    spec: dict, source: str, filename: str, destination: str
) -> str:
    target = f"{destination}/inbox/{spec['task_id']}.json"
    # the destination gets the NORMALIZED envelope, not the raw spec —
    # the kk producer's <task_id>.json filename contract is preserved
    rc("rcat", target,
       input_text=json.dumps(spec, ensure_ascii=False) + "\n")
    return target


def route_colab(spec: dict, source: str, destination: str) -> str:
    pack_source = Path(str(spec.get("pack_source", ""))).resolve()
    allowed = (_REPO / "scripts" / "colab" / "packs").resolve()
    if not str(pack_source).startswith(str(allowed) + "/"):
        raise ValueError("pack_source must be under scripts/colab/packs")
    pack_name = str(spec.get("pack_name") or pack_source.name)
    if not SLUG.fullmatch(pack_name):
        raise ValueError("pack_name must be a safe slug")
    pack_yml = pack_source / "pack.yml"
    if not pack_yml.is_file():
        raise ValueError(f"pack_source has no pack.yml: {pack_source}")
    # stage only packs that pass the submit contract — a pack that would
    # fail pack-preflight/nest-pack-submit must not reach the queue
    errs = _pack_submit.validate(
        _pack_submit.load_yml(str(pack_yml)), pack_source.name)
    if errs:
        raise ValueError(f"pack invalid: {'; '.join(errs[:3])}")
    remote_dir = f"{destination}/packs/{pack_name}"
    # Staging is intentional; runtime launch remains an explicit Colab
    # gate. Seal the copy so a runtime snapshotting inventory mid-stage
    # sees the pack only when complete.
    rc("copy", str(pack_source), remote_dir,
       "--exclude", "claim/**", "--exclude", "done",
       "--exclude", "failed", "--exclude", npr.READY_FILE)
    npr.verify_and_mark(pack_source, remote_dir,
                        staged_by="devnest_capacity_broker", rclone=rc)
    return remote_dir


def colab_state(remote: str) -> dict:
    """Read-only observation of the Colab lane: queue heartbeat age,
    fresh managed runtimes (duplicate-runner signal), pending pack
    depth, and whether the deployed queue/JOBS.py matches the canonical
    repo copy. Every probe degrades to an error field — observation
    failure never fails the routing cycle."""
    state: dict = {"queue_heartbeat_age_s": None, "runtime_fresh": 0,
                   "runtime_records": 0, "pending_packs": None,
                   "jobs_manifest": "unknown", "errors": []}
    try:
        hb = rc("cat", f"{remote}/queue/heartbeat").split()
        state["queue_heartbeat_age_s"] = round(time.time() - float(hb[0]), 1)
    except Exception as exc:
        state["errors"].append(f"heartbeat:{type(exc).__name__}")
    try:
        names = [
            x for x in rc(
                "lsf", f"{remote}/queue/runtime-sessions", "--files-only"
            ).splitlines() if x.endswith(".json")
        ]
        state["runtime_records"] = len(names)
        for name in names[:10]:
            try:
                rec = json.loads(
                    rc("cat", f"{remote}/queue/runtime-sessions/{name}"))
                if time.time() - float(rec.get("ts") or 0) <= RUNTIME_TTL_S:
                    state["runtime_fresh"] += 1
            except Exception:
                state["errors"].append(f"session:{name}:unreadable")
    except Exception as exc:
        state["errors"].append(f"sessions:{type(exc).__name__}")
    try:
        state["pending_packs"] = queue_depth(remote)
    except Exception as exc:
        state["errors"].append(f"packs:{type(exc).__name__}")
    try:
        remote_sha = rc(
            "hashsum", "SHA-256", f"{remote}/queue/JOBS.py"
        ).split()[0].strip()
        local_sha = hashlib.sha256(
            (_REPO / "scripts" / "colab" / "JOBS.py").read_bytes()
        ).hexdigest()
        state["jobs_manifest"] = (
            "in_sync" if remote_sha == local_sha else "drift")
    except Exception as exc:
        state["errors"].append(f"jobs:{type(exc).__name__}")
    return state


def record_cycle(source: str, body: dict) -> str | None:
    """Append one capacity-ledger object under devnest/capacity/.
    Unique per-cycle filename — no read-modify-write race between
    broker timers. Best-effort: returns the remote path or None."""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        tag = hashlib.sha256(
            f"{time.monotonic_ns()}".encode()).hexdigest()[:6]
        path = f"{source}/capacity/{ts}-{tag}.json"
        rc("rcat", path, input_text=json.dumps(
            {"kind": "capacity-cycle", **body}, sort_keys=True) + "\n")
        return path
    except Exception:
        return None


def produce(
    source: str = DEVNEST_REMOTE,
    kk_remote: str = KK_LLM_REMOTE,
    colab_remote: str = COLAB_REMOTE,
    max_depth: int = 3,
    budget_s: float = 240.0,
) -> dict:
    started = time.monotonic()

    def expired() -> bool:
        return time.monotonic() - started >= budget_s
    result = {"source": source, "routed": [], "held": [], "rejected": []}
    gate = snapshot()
    kk_enabled = os.environ.get("DEVNEST_KK_MAC_ENABLED", "true").lower() == "true"
    observation = {"kk": {"eligible": bool(gate.get("eligible")),
                          "enabled": kk_enabled,
                          "queue_depth": None,
                          "reasons": gate.get("reasons") or []},
                   "colab": colab_state(colab_remote)}
    try:
        observation["kk"]["queue_depth"] = queue_depth(kk_remote)
    except Exception:
        pass
    result["observed"] = observation
    # The KK producer owns the execution queue watermark. The broker only
    # routes a bounded number of new specs per pass.
    source_entries = set(rc(
        "lsf", f"{source}/inbox", "--files-only"
    ).splitlines())
    for filename in inbox(source):
        if expired():
            result["held"].append("budget_exhausted")
            break
        try:
            if len(result["routed"]) >= MAX_ROUTE_PER_CYCLE:
                break
            if f"{filename}.routed" in source_entries:
                continue
            spec = normalize_spec(
                json.loads(rc("cat", f"{source}/inbox/{filename}")),
                filename)
            if f"{spec['task_id']}.routed" in source_entries:
                continue
            if spec["lane"] == "kk_mac_local":
                if not kk_enabled:
                    result["held"].append(f"{filename}:kk_disabled")
                    continue
                if not gate.get("eligible"):
                    result["held"].append(f"{filename}:kk_admission")
                    continue
                destination = route_kk(
                    spec, source, filename, kk_remote
                )
            else:
                destination = route_colab(spec, source, colab_remote)
            mark_routed(source, filename, destination)
            result["routed"].append({
                "task_id": spec["task_id"],
                "lane": spec["lane"],
                "destination": destination,
            })
        except Exception as exc:
            result["rejected"].append(f"{filename}:{type(exc).__name__}")
    result["kk_gate"] = gate
    result["ledger"] = record_cycle(source, {
        "at": datetime.now(timezone.utc).isoformat(),
        "observed": observation,
        "routed": result["routed"],
        "held": result["held"],
        "rejected": result["rejected"],
        "elapsed_s": round(time.monotonic() - started, 1),
    })
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEVNEST_REMOTE)
    ap.add_argument("--kk-remote", default=KK_LLM_REMOTE)
    ap.add_argument("--colab-remote", default=COLAB_REMOTE)
    ap.add_argument("--max-depth", type=int, default=3)
    ap.add_argument("--budget-s", type=float, default=240.0)
    args = ap.parse_args()
    print(json.dumps(produce(
        args.source, args.kk_remote, args.colab_remote, args.max_depth,
        args.budget_s,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
