#!/usr/bin/env python3
"""Controlled dispatcher for approved video render manifests (OPS-1042).

Sits between an approved dispatch manifest and the two existing pack
queues. It never runs pack code and never writes done/failed markers —
the only writers/runners remain the queue workers (nest-worker on
gdrive:ada-nest for Colab/fleet packs, the gated nest-worker on KK-Mac
for gdrive:ada-nest/kk-mac-video-pilot MLX packs), preserving the
one-writer/one-runner claim protocol.

Manifest schema ``video-dispatch/v1`` (YAML)::

    schema: video-dispatch/v1
    project_id: kk-video-c9f99fee6146
    approved: true                # apply refuses unless true
    approved_by: tony
    stages:
      - id: final-preview-v4-clean
        pack: <pack-dir-name>     # name under the target queue's packs/
        source: scripts/devnest/video-packs/<name>   # repo dir to stage
        lane: mlx                 # mlx | colab | auto
        shots: [shot01, shot02]   # idempotent shot IDs this stage covers
        variant: clean            # review | clean — review-vs-clean kept
        artifacts:                # optional; {shot} expands per shot id
          - packs/<pack>/out/{shot}.mp4

Routing rules (card spec):
  * mlx   -> KK-Mac pilot queue, only when kk_mac_admission gates pass
             (awake/model-ready/load/disk/idle). Gates fail -> deferred;
             MLX packs are never silently rerouted to Colab.
  * colab -> general ada-nest queue, only after complete staging
             (pack.yml present + rclone check of the staged dir).
  * auto  -> mlx when the pack looks MLX-routed and gates pass, else
             colab when staging is complete, else deferred.

Only packs named in ``stages`` are ever touched — historical/support
queue entries are inventory, never dispatch targets.

Subcommands:
    plan     --manifest F     read-only routing plan (default-safe)
    apply    --manifest F     stage approved packs whose plan says stage
    verify   --manifest F     check declared artifacts exist on-queue
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

REMOTE_MLX = "gdrive:ada-nest/kk-mac-video-pilot"
REMOTE_COLAB = "gdrive:ada-nest"
TERMINAL = ("done", "failed", "retired")
ACTIVE = ("queued", "claimed", "running", "stale")

try:
    import yaml
except ImportError:
    yaml = None


def say(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VQS = _load("video_queue_status",
            Path(__file__).resolve().parent / "video_queue_status.py")


def rc(*args: str, timeout: int = 900,
       input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([VQS.RCLONE, *args], input=input_text,
                          capture_output=True, text=True, timeout=timeout)


def queue_states(remote: str, stale_hours: float = 2.0) -> dict:
    """{pack: state} for a whole queue in ONE recursive listing.

    Claim freshness comes from the listing modtime (--format pt), so no
    per-claim lsl calls are needed. done > failed > retired > claims >
    queued — same precedence as video_queue_status."""
    p = rc("lsf", f"{remote}/packs", "--recursive", "--format", "pt",
           timeout=600)
    if p.returncode != 0:
        raise RuntimeError(f"lsf {remote}/packs: {p.stderr.strip()[:200]}")
    packs: dict[str, dict] = {}
    now = time.time()
    for line in p.stdout.splitlines():
        path, _, ts = line.rpartition(";")
        path = path.rstrip("/")
        parts = path.split("/", 1)
        if len(parts) == 1:
            if parts[0]:
                packs.setdefault(parts[0], {"entries": set(),
                                            "claims": []})
            continue
        name, rel = parts
        ent = packs.setdefault(name, {"entries": set(), "claims": []})
        ent["entries"].add(rel)
        if rel.startswith("claim/") and rel[6:]:
            try:
                # rclone pt modtimes are UTC — parse as UTC, not local
                mtime = datetime.datetime.strptime(
                    ts.strip().split(".")[0],
                    "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=datetime.timezone.utc).timestamp()
            except (ValueError, TypeError):
                mtime = None
            ent["claims"].append({"worker": rel.split("/", 1)[1],
                                  "mtime": mtime})
    out = {}
    for name, ent in packs.items():
        top = {e for e in ent["entries"] if "/" not in e}
        state = VQS.marker_state(top)
        if state:
            out[name] = state
            continue
        fresh = any(c["mtime"] is not None
                    and now - c["mtime"] <= stale_hours * 3600
                    for c in ent["claims"])
        out[name] = ("running" if fresh else
                     "stale" if ent["claims"] else "queued")
    return out


def pack_state(remote: str, pack: str) -> dict:
    """Queue-side truth for one pack dir (used by apply's re-check)."""
    p = rc("lsf", f"{remote}/packs/{pack}", "--recursive",
           timeout=120)
    if p.returncode != 0:
        return {"exists": False, "state": "absent"}
    entries = {l.rstrip("/") for l in p.stdout.splitlines() if l.strip()}
    if not entries:
        return {"exists": False, "state": "absent"}
    top = {e for e in entries if "/" not in e}
    state = VQS.marker_state(top)
    if not state:
        claims = [e for e in entries
                  if e.startswith("claim/") and e[6:]]
        state = "claimed" if claims else "queued"
    return {"exists": True, "state": state}


def mlx_gate() -> dict:
    """KK-Mac admission snapshot (heartbeat path); fail-closed."""
    try:
        adm = _load("kk_mac_admission",
                    Path(__file__).resolve().parent
                    / "kk_mac_admission.py")
        return adm.snapshot()
    except Exception as exc:  # gate must fail closed, never open
        return {"eligible": False, "lane": "kk_mac_local",
                "reasons": [f"gate_error:{type(exc).__name__}"],
                "source": "dispatcher"}


def norm_inputs(stage: dict) -> list[dict]:
    """Declared stage inputs: [{from, to, sha256?}] — store paths the
    dispatcher fetches into the pack at staging time (the
    complete-staging gate). `to` must stay inside the pack dir."""
    out = []
    for item in stage.get("inputs") or []:
        if isinstance(item, str):
            item = {"from": item, "to": item}
        src, dst = item.get("from"), item.get("to")
        if not src or not dst:
            raise RuntimeError(f"input missing from/to: {item}")
        if dst.startswith("/") or ".." in dst.split("/"):
            raise RuntimeError(f"input `to` escapes pack dir: {dst}")
        out.append({"from": src, "to": dst,
                    "sha256": item.get("sha256")})
    return out


def staging_check(source: Path, stage: dict | None = None) -> dict:
    """Complete-staging gate: pack.yml must exist and declare a runner +
    artifacts for QC. Declared stage inputs are reported present/missing
    — missing ones do not block `ok` because apply fetches them, but
    every other defect does."""
    out = {"ok": False, "reasons": [], "pack_yml": {}, "inputs": [],
           "fetch_inputs": []}
    if not source.is_dir():
        out["reasons"].append("source_missing")
        return out
    py = source / "pack.yml"
    if not py.is_file():
        out["reasons"].append("pack_yml_missing")
        return out
    try:
        spec = (yaml.safe_load(py.read_text()) if yaml else {}) or {}
    except Exception as exc:
        out["reasons"].append(f"pack_yml_unreadable:{exc}")
        return out
    if not isinstance(spec, dict):
        out["reasons"].append("pack_yml_not_mapping")
        return out
    out["pack_yml"] = spec
    if not (spec.get("run") or spec.get("run_sh") or spec.get("prep")):
        out["reasons"].append("no_runner_declared")
    if not spec.get("artifacts"):
        out["reasons"].append("no_artifacts_declared")
    inputs = source / "inputs"
    if inputs.is_dir() and not any(inputs.iterdir()):
        out["reasons"].append("inputs_empty")
    for item in norm_inputs(stage or {}):
        local = source / item["to"]
        entry = dict(item)
        entry["present"] = local.is_file() and local.stat().st_size > 0
        out["inputs"].append(entry)
        if not entry["present"]:
            out["fetch_inputs"].append(item["to"])
    out["ok"] = not out["reasons"]
    return out


def load_manifest(path: Path) -> dict:
    if yaml is None:
        raise RuntimeError("pyyaml required")
    doc = yaml.safe_load(path.read_text()) or {}
    if doc.get("schema") != "video-dispatch/v1":
        raise RuntimeError(
            f"{path}: schema must be video-dispatch/v1, "
            f"got {doc.get('schema')!r}")
    stages = doc.get("stages") or []
    if not stages:
        raise RuntimeError(f"{path}: no stages")
    ids = [s.get("id") for s in stages]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"{path}: duplicate stage ids")
    for s in stages:
        for k in ("id", "lane"):
            if not s.get(k):
                raise RuntimeError(f"{path}: stage missing {k!r}: {s}")
        if not s.get("pack") and not s.get("state"):
            raise RuntimeError(
                f"{path}: stage needs pack or known state: {s}")
        if s["lane"] not in ("mlx", "colab", "auto"):
            raise RuntimeError(f"{path}: bad lane {s['lane']!r}")
        if s.get("state") and s["state"] not in (
                "queued", "staged", "done", "failed"):
            raise RuntimeError(f"{path}: bad state {s['state']!r}")
    return doc


def expand_artifacts(pack_yml: dict, stage: dict) -> list[str]:
    """Expected artifact globs; {shot} expands over the stage's shots so
    shot-level idempotency is visible in verify output."""
    raw = stage.get("artifacts") or pack_yml.get("artifacts") or []
    shots = stage.get("shots") or []
    out = []
    for pat in raw:
        if "{shot}" in pat and shots:
            out.extend(pat.replace("{shot}", s) for s in shots)
        else:
            out.append(pat)
    return out


def remote_glob(remote: str, pattern: str) -> dict:
    """{name: size} for a store-relative glob like packs/x/out/*.mp4."""
    parent, _, pat = pattern.rpartition("/")
    d = f"{remote}/{parent}" if parent else remote
    base = pat.split("/")[-1]
    p = rc("lsf", d, "--format", "sp", "--include", base,
           "--max-depth", "1", timeout=120)
    if p.returncode != 0:
        return {}
    files = {}
    for line in p.stdout.splitlines():
        sz, _, name = line.rstrip().rpartition(";")
        name = name.strip()
        if name and not name.endswith("/"):
            try:
                files[name] = int(sz)
            except ValueError:
                pass
    return files


def _is_mlx_pack(spec: dict) -> bool:
    blob = json.dumps(spec, default=str)[:8000].lower()
    return "mlx" in blob or "ltx-mlx" in blob


def plan(manifest: dict, args) -> dict:
    remotes = {"mlx": args.remote_mlx, "colab": args.remote_colab}
    all_known = all(s.get("state") for s in manifest["stages"])
    need_mlx = not all_known and any(
        s["lane"] in ("mlx", "auto") for s in manifest["stages"])
    gate = mlx_gate() if need_mlx else None
    queues = {}
    if not all_known:
        for lane, remote in remotes.items():
            try:
                queues[remote] = queue_states(remote)
            except Exception as exc:
                queues[remote] = {"__error__": str(exc)[:200]}
    stages_out = []
    for st in manifest["stages"]:
        lane = st["lane"]
        row = {"id": st["id"], "pack": st.get("pack"), "lane": lane,
               "variant": st.get("variant"), "shots": st.get("shots") or []}
        source = Path(st["source"]) if st.get("source") else None
        if source and not source.is_absolute():
            source = REPO / source
        pack_yml = {}
        if source:
            chk = staging_check(source, st)
            pack_yml = chk["pack_yml"]
            row["staging"] = {"ok": chk["ok"], "reasons": chk["reasons"],
                              "source": str(source),
                              "inputs": chk["inputs"],
                              "fetch_inputs": chk["fetch_inputs"]}
        else:
            row["staging"] = {"ok": None,
                              "reasons": ["no_source_declared"],
                              "note": "pack expected already on-queue"}
        eff = lane
        if lane == "auto":
            eff = "mlx" if pack_yml and _is_mlx_pack(pack_yml) else "colab"
            row["lane_resolved"] = eff
        target = remotes[eff]
        row["target_remote"] = target
        known = st.get("state")
        if known:
            # manifest-declared state (e.g. a completed canonical
            # deliverable recorded for QC, not re-dispatch)
            row["queue_state"] = known
            row["decision"] = (f"skip-{known}" if known in TERMINAL
                               else "skip-queued")
            row["reasons"] = ["manifest declares state — never rerun"]
            row["artifacts_expected"] = expand_artifacts(pack_yml, st)
            stages_out.append(row)
            continue
        q = queues.get(target) or {}
        if "__error__" in q:
            row["decision"] = "blocked"
            row["reasons"] = [f"queue_probe_failed:{q['__error__']}"]
            stages_out.append(row)
            continue
        pstate = q.get(st["pack"])
        row["queue_state"] = pstate or "absent"
        other = remotes["colab" if eff == "mlx" else "mlx"]
        oq = queues.get(other) or {}
        if st["pack"] in oq:
            row.setdefault("warnings", []).append(
                f"pack also present on other queue as {oq[st['pack']]}")
        if pstate in TERMINAL:
            row["decision"] = f"skip-{pstate}"
            row["reasons"] = ["terminal marker on queue — never rerun"]
        elif pstate in ACTIVE:
            row["decision"] = "skip-queued"
            row["reasons"] = [f"already on queue ({pstate})"]
        elif eff == "mlx":
            if gate is None or not gate.get("eligible"):
                row["decision"] = "deferred"
                row["gate"] = {k: gate.get(k) for k in (
                    "eligible", "reasons", "heartbeat_age_s",
                    "disk_free_gb", "load_1m", "node_busy",
                    "source")} if gate else None
                row["reasons"] = ["kk_mac_gates",
                                  *((gate or {}).get("reasons") or [])]
            elif row["staging"].get("ok") is False:
                row["decision"] = "blocked"
                row["reasons"] = ["staging_incomplete",
                                  *row["staging"]["reasons"]]
            else:
                row["decision"] = "stage"
                row["reasons"] = ["mlx gates pass; approved stage"]
        else:  # colab
            if row["staging"].get("ok") is False:
                row["decision"] = "blocked"
                row["reasons"] = ["staging_incomplete",
                                  *row["staging"]["reasons"]]
            elif not row["staging"].get("ok"):
                row["decision"] = "deferred"
                row["reasons"] = ["staging_not_verified"]
            else:
                row["decision"] = "stage"
                row["reasons"] = ["staging complete; finite GPU batch"]
        row["artifacts_expected"] = expand_artifacts(pack_yml, st)
        stages_out.append(row)
    return {
        "manifest": manifest.get("manifest") or manifest.get("project_id"),
        "project_id": manifest["project_id"],
        "approved": bool(manifest.get("approved")),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mlx_gate": ({k: gate.get(k) for k in (
            "eligible", "reasons", "heartbeat_age_s", "disk_free_gb",
            "load_1m", "node_busy", "source")} if gate else None),
        "stages": stages_out,
    }


def fetch_stage_inputs(stage: dict, remote: str, pack: str,
                       target: str) -> list[dict]:
    """Fetch declared stage inputs from the store into the just-staged
    pack dir. Skips inputs already present remotely; verifies sha256
    (streamed through `rclone cat`) when the manifest declares one."""
    out = []
    for item in norm_inputs(stage):
        rec = {"to": item["to"], "from": item["from"],
               "sha256": item.get("sha256")}
        dst = f"{target}/{item['to']}"
        parent = dst.rsplit("/", 1)[0]
        rc("mkdir", parent, timeout=120)
        # already staged? (idempotent re-apply)
        ls = rc("lsl", dst, timeout=60)
        if ls.returncode == 0 and ls.stdout.strip():
            rec["action"] = "present"
            out.append(rec)
            continue
        cp = rc("copyto", item["from"], dst, timeout=900)
        if cp.returncode != 0:
            rec["action"] = "failed"
            rec["error"] = cp.stderr.strip()[:200]
            out.append(rec)
            continue
        if item.get("sha256"):
            h = subprocess.run(
                f"{VQS.RCLONE} cat {item['from']} | sha256sum",
                shell=True, capture_output=True, text=True, timeout=600)
            got = h.stdout.split()[0] if h.stdout.split() else ""
            rec["sha256"] = item["sha256"]
            rec["sha256_ok"] = got == item["sha256"]
            if got != item["sha256"]:
                rec["action"] = "failed"
                rec["error"] = f"sha256 mismatch {got[:12]}"
                out.append(rec)
                continue
        rec["action"] = "fetched"
        out.append(rec)
    return out


def apply(manifest: dict, args, plan_result: dict) -> dict:
    if not manifest.get("approved"):
        raise RuntimeError("manifest not approved — apply refused")
    results = []
    for row in plan_result["stages"]:
        st = next(s for s in manifest["stages"] if s["id"] == row["id"])
        rec = {"id": row["id"], "pack": row["pack"],
               "decision": row["decision"], "action": "none"}
        if row["decision"] != "stage":
            results.append(rec)
            continue
        remote = row["target_remote"]
        target = f"{remote}/packs/{row['pack']}"
        source = Path(st["source"])
        if not source.is_absolute():
            source = REPO / source
        # never overwrite: re-check queue state immediately before write
        now = pack_state(remote, row["pack"])
        if now["exists"]:
            rec["action"] = "skipped_exists"
            rec["queue_state"] = now["state"]
            results.append(rec)
            continue
        cp = rc("copy", str(source), target, timeout=1800)
        if cp.returncode != 0:
            rec["action"] = "copy_failed"
            rec["error"] = cp.stderr.strip()[:300]
            results.append(rec)
            continue
        # complete-staging proof: rclone check local vs remote
        chk = rc("check", str(source), target, "--one-way", timeout=900)
        rec["staging_verified"] = chk.returncode == 0
        if chk.returncode != 0:
            rec["action"] = "staging_mismatch"
            rec["error"] = (chk.stderr or chk.stdout).strip()[:300]
            results.append(rec)
            continue
        # declared inputs: fetch store -> pack dir, verify sha256 when
        # given; on failure roll back the just-created pack dir so a
        # half-staged pack never sits queued
        fetch = fetch_stage_inputs(st, remote, row["pack"], target)
        rec["inputs"] = fetch
        bad = [f for f in fetch if f["action"] == "failed"]
        if bad:
            subprocess.run([VQS.RCLONE, "purge", target],
                           capture_output=True, text=True, timeout=600)
            rec["action"] = "input_fetch_failed"
            rec["error"] = "; ".join(
                f"{f['to']}:{f.get('error', 'failed')}" for f in bad)
            results.append(rec)
            continue
        ev = {
            "ts": time.time(),
            "project_id": manifest["project_id"],
            "stage": row["id"],
            "pack": row["pack"],
            "lane": row.get("lane_resolved") or row["lane"],
            "variant": row.get("variant"),
            "shots": row.get("shots") or [],
            "approved_by": manifest.get("approved_by"),
            "source": str(source),
            "target": target,
            "staging_verified": True,
        }
        r = rc("mkdir", f"{remote}/queue/dispatch-events", timeout=120)
        fn = (f"{int(time.time() * 1000)}-video-dispatch-"
              f"{row['pack']}-staged.json")
        ec = rc("rcat", f"{remote}/queue/dispatch-events/{fn}",
                input_text=json.dumps(ev), timeout=120)
        rec["action"] = ("staged" if ec.returncode == 0
                         else "staged_unlogged")
        rec["event"] = fn if ec.returncode == 0 else None
        results.append(rec)
        say(f"{row['pack']}: staged -> {target}")
    return {"applied": True, "results": results}


def verify(manifest: dict, args, plan_result: dict) -> dict:
    """Final-artifact QC: every declared artifact glob must exist with
    size > 0 on the resolved queue remote."""
    out = []
    for row in plan_result["stages"]:
        remote = row["target_remote"]
        v = {"id": row["id"], "pack": row["pack"], "artifacts": []}
        ok = True
        for pat in row.get("artifacts_expected") or []:
            # patterns are queue-remote-relative, verbatim:
            #   packs/<pack>/out/x.mp4   (pack outputs)
            #   final/x.mp4             (pilot final/ deliverables)
            store_pat = pat
            found = remote_glob(remote, store_pat)
            hit = bool(found) and all(s > 0 for s in found.values())
            ok = ok and hit
            v["artifacts"].append({"pattern": store_pat,
                                   "matches": len(found), "ok": hit})
        v["qc_pass"] = ok if v["artifacts"] else None
        if not v["artifacts"]:
            v["note"] = "no artifacts declared — QC not applicable"
        out.append(v)
    return {"verified": all(v["qc_pass"] is not False for v in out),
            "stages": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", required=True)
        p.add_argument("--remote-mlx", default=REMOTE_MLX)
        p.add_argument("--remote-colab", default=REMOTE_COLAB)
    args = ap.parse_args()
    manifest = load_manifest(Path(args.manifest))
    result = plan(manifest, args)
    if args.cmd == "plan":
        print(json.dumps(result, indent=2))
        return 0
    if args.cmd == "apply":
        result = apply(manifest, args, result)
        print(json.dumps(result, indent=2))
        return 0 if all(r["action"] in (
            "none", "staged", "staged_unlogged", "skipped_exists")
            for r in result["results"]) else 1
    result = verify(manifest, args, result)
    print(json.dumps(result, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
