#!/usr/bin/env python3
"""mcp-colab — Colab fleet control plane (OPS-0808).

Wraps the Drive-based nest-pack queue (ada-nest/packs) + the Colab tunnel
+ the LiteLLM gateway so agents/Ada/IDE can manage the free GPU lane
without poking Drive manually.

Tools:
  colab_pack_status    — list packs with claim/done state
  colab_session_status — managed-runtime registry + queue liveness
  colab_queue_start    — request queue start on one confirmed managed runtime
  colab_queue_request_status — read a queue-start request acknowledgement
  colab_pack_submit    — copy a local pack (pack.yml + inputs/) to Drive
  colab_pack_result    — read a pack's out/*.json results
  colab_tunnel_check   — probe the Colab tunnel (idc03 loopback / proxy alias)
  colab_model_probe    — 1-token chat through the LiteLLM gateway

Env:
  GDRIVE_REMOTE   rclone remote+path for the nest root (default gdrive:ada-nest)
  COLAB_TUNNEL_PROBE  host:port to probe for the tunnel (default 100.102.134.91:4000
                      with a chat against the colab-qwen3 alias)
  LITELLM_KEY     gateway key (sourced from ~/.config/secrets/litellm-chaba.env
                  when not set)
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-colab")

NEST = os.environ.get("GDRIVE_REMOTE", "gdrive:ada-nest").rstrip("/")
PACKS = f"{NEST}/packs"
PROXY = os.environ.get("COLAB_PROXY", "http://100.102.134.91:4000/v1")
MODEL = os.environ.get("COLAB_MODEL", "colab-qwen3")

_SECRETS = Path.home() / ".config/secrets/litellm-chaba.env"


def _api_key() -> str:
    if os.environ.get("LITELLM_KEY"):
        return os.environ["LITELLM_KEY"]
    if _SECRETS.exists():
        for line in _SECRETS.read_text().splitlines():
            if line.startswith("LITELLM_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _rclone(*args: str, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(["rclone", *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout if r.returncode == 0 else (r.stderr or r.stdout)


def _pack_dir(name: str) -> str:
    return f"{PACKS}/{name}"


def _active_release() -> tuple[dict, dict]:
    """-> (pointer, manifest). Under release pinning the pack CODE lives at
    releases/<id>/packs/; ada-nest/packs/<name>/ is state-only workspace."""
    rc, data = _rclone("cat", f"{NEST}/queue/ACTIVE_RELEASE.json")
    try:
        ptr = json.loads(data) if rc == 0 else None
    except Exception:
        ptr = None
    if not ptr or not ptr.get("release_id"):
        return {}, {}
    rc, data = _rclone(
        "cat", f"{NEST}/releases/{ptr['release_id']}/release.json")
    try:
        manifest = json.loads(data) if rc == 0 else {}
    except Exception:
        manifest = {}
    return ptr, manifest


def _runtime_records() -> tuple[list[dict], str]:
    """Read only runtime records written by our managed notebook preflight."""
    root = f"{NEST}/queue/runtime-sessions"
    rc, out = _rclone("lsf", root, "--files-only")
    if rc != 0:
        return [], out.strip() or "runtime registry unavailable"
    records = []
    for name in sorted(out.splitlines()):
        name = name.strip()
        if not name.endswith(".json"):
            continue
        rc, data = _rclone("cat", f"{root}/{name}")
        if rc != 0:
            records.append({"boot_id": name, "unparseable": True})
            continue
        try:
            records.append(json.loads(data))
        except Exception:
            records.append({"boot_id": name, "unparseable": True})
    return records, ""


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


@mcp.tool()
def colab_pack_status() -> str:
    """List nest packs with claim/done/result state (read-only).
    Pack names come from the pinned release manifest
    (queue/ACTIVE_RELEASE.json -> releases/<id>/release.json packs{} —
    the verified code set). ada-nest/packs/<name>/ is the state workspace:
    done/claim/out. Without a pointer the legacy workspace listing is
    used and flagged unpinned."""
    ptr, manifest = _active_release()
    names = sorted((manifest.get("packs") or {}).keys())
    pinned = bool(names)
    if not pinned:
        rc, out = _rclone("lsf", PACKS, "--dirs-only")
        if rc != 0:
            return f"ERROR listing packs: {out.strip()}"
        names = [l.strip().strip("/") for l in out.splitlines() if l.strip()]
    lines = []
    if ptr.get("release_id"):
        lines.append(f"release: {ptr['release_id']} "
                     f"commit {str(ptr.get('commit'))[:12]}"
                     + ("" if pinned else " (no packs in manifest)"))
    else:
        lines.append("release: UNPINNED — workspace listing, not "
                     "verified code")
    for n in names:
        entries = _rclone("lsf", _pack_dir(n))[1].splitlines()
        entries = [e.strip() for e in entries]
        has_done = "done" in entries
        has_out = "out/" in entries
        claimed = False
        if "claim/" in entries:
            claims = _rclone("lsf", f"{_pack_dir(n)}/claim", "--files-only")[1]
            claimed = any(l.strip() for l in claims.splitlines())
        state = "DONE" if has_done else ("CLAIMED" if claimed else ("OUT" if has_out else "queued"))
        lines.append(f"{n:<28} {state}")
    return "\n".join(lines) or "(no packs)"


@mcp.tool()
def colab_session_status() -> str:
    """Managed-runtime registry + queue liveness (read-only).

    Reports every record under queue/runtime-sessions/ (boot_id, GPU, RAM, record
    age) with fresh/stale marking, plus queue/heartbeat, queue/lease and
    queue/runner.id — the same state the console notebook's session guard
    reads. Cannot see uninstrumented Colab sessions; Google Runtime >
    Manage Sessions remains authoritative for those."""
    lines = []
    recs, registry_error = _runtime_records()
    now = time.time()
    if recs:
        lines.append("managed runtimes (ttl 300s):")
        for r in recs:
            if r.get("unparseable"):
                lines.append(f"  {r['boot_id']}  UNPARSEABLE record")
                continue
            try:
                stamp = float(r.get("ts") or r.get("last_seen"))
                age = now - stamp
                mark = ("fresh" if age <= 300 else f"STALE {age/60:.0f}min")
            except (TypeError, ValueError):
                age = None
                mark = "age unknown"
            gpu = r.get("gpu") or "cpu"
            gpu_gb = r.get("gpu_gb")
            if isinstance(gpu, dict):
                gpu_gb = gpu_gb or (
                    float(gpu.get("memory_mib") or 0) / 1024)
                gpu = gpu.get("name") or "gpu"
            gpu_size = f"{float(gpu_gb):.1f}GB" if gpu_gb else "VRAM unknown"
            ram = f"{r['ram_gb']}GB" if r.get("ram_gb") is not None else "RAM unknown"
            drive = ("Drive mounted" if r.get("drive_mounted") else
                     "Drive not mounted" if r.get("drive_mounted") is False
                     else "Drive state unknown")
            runner = r.get("runner") or {}
            rbit = f" runner={runner.get('worker')}" if runner.get("worker") else ""
            lines.append(
                f"  {r.get('boot_id')}  {gpu} {gpu_size}, "
                f"{ram}, {drive}, {mark}{rbit}")
    else:
        lines.append("managed runtimes: " + (
            f"unavailable ({registry_error})" if registry_error
            else "none registered"))
    _, hb = _rclone("cat", f"{NEST}/queue/heartbeat")
    try:
        ts, job, phase = hb.split()
        lines.append(f"queue heartbeat: {job}/{phase} "
                     f"{now - float(ts):.0f}s ago")
    except Exception:
        lines.append("queue heartbeat: absent")
    _, lease = _rclone("cat", f"{NEST}/queue/lease")
    try:
        d = json.loads(lease)
        lines.append(f"queue lease: {d.get('worker')} epoch {d.get('epoch')} "
                     f"({now - float(d.get('ts') or 0):.0f}s ago)")
    except Exception:
        lines.append("queue lease: absent")
    _, rid = _rclone("cat", f"{NEST}/queue/runner.id")
    try:
        d = json.loads(rid)
        lines.append(f"runner.id: pid {d.get('pid')} boot "
                     f"{str(d.get('boot_id'))[:8]} {d.get('worker')} "
                     f"rel {d.get('release') or '?'}")
    except Exception:
        lines.append("runner.id: absent")
    ptr, _manifest = _active_release()
    if ptr.get("release_id"):
        lines.append(f"active release: {ptr['release_id']} "
                     f"commit {str(ptr.get('commit'))[:12]}")
    else:
        lines.append("active release: UNPINNED (no ACTIVE_RELEASE.json)")
    return "\n".join(lines)


@mcp.tool()
def colab_queue_start(boot_id: str, confirm: bool) -> str:
    """Request the shared queue to start on one already-running managed runtime.

    This does not create or stop a Colab runtime. The target runtime must have
    mounted Drive and run console cell 1; `confirm=True` is required because
    starting the queue consumes that runtime's compute quota and may write
    cache/artifact files to Drive.
    """
    if not confirm:
        return "REFUSED: set confirm=true only when you intend to start the shared queue."
    try:
        target = str(uuid.UUID(boot_id))
    except (ValueError, TypeError, AttributeError):
        return "ERROR: boot_id must be the full UUID printed by console cell 1."

    records, error = _runtime_records()
    if error:
        return f"ERROR reading managed runtime registry: {error}"
    now = time.time()
    runtime = next((r for r in records
                    if not r.get("unparseable")
                    and str(r.get("boot_id")) == target), None)
    if not runtime:
        return f"REFUSED: managed runtime {target[:8]} is not registered."
    if runtime.get("kind") != "managed-notebook":
        return f"REFUSED: runtime {target[:8]} is not a console-managed notebook."
    age = now - float(runtime.get("ts") or runtime.get("last_seen") or 0)
    ttl = float(os.environ.get("NEST_RUNTIME_TTL_S", "300"))
    if age > ttl:
        return f"REFUSED: runtime {target[:8]} is stale ({age:.0f}s; ttl {ttl:.0f}s)."
    if not runtime.get("drive_mounted"):
        return f"REFUSED: runtime {target[:8]} reports Drive not mounted."
    if not runtime.get("gpu") or float(runtime.get("gpu_gb") or 0) <= 0:
        return f"REFUSED: runtime {target[:8]} has no GPU."

    rc, runner_id = _rclone("cat", f"{NEST}/queue/runner.id")
    if rc == 0 and runner_id.strip():
        return ("REFUSED: queue/runner.id is present; inspect "
                "colab_session_status before launching another runner.")

    rc, heartbeat = _rclone("cat", f"{NEST}/queue/heartbeat")
    try:
        heartbeat_age = now - float(heartbeat.split()[0])
    except (ValueError, IndexError):
        heartbeat_age = float("inf")
    if heartbeat_age <= 90:
        return (f"REFUSED: queue heartbeat is fresh ({heartbeat_age:.0f}s); "
                "the shared queue appears to be running.")
    rc, lease = _rclone("cat", f"{NEST}/queue/lease")
    try:
        lease_data = json.loads(lease)
        lease_age = now - float(lease_data.get("ts") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        lease_age = float("inf")
    if lease_age <= 90:
        return (f"REFUSED: queue lease is fresh ({lease_age:.0f}s); "
                "the shared queue may be running.")

    request_id = uuid.uuid4().hex
    request = {
        "request_id": request_id,
        "command": "start_queue",
        "confirmed": True,
        "target_boot_id": target,
        "created_at": now,
    }
    for directory in (
            f"{NEST}/queue/control/requests",
            f"{NEST}/queue/control/acks"):
        rc, out = _rclone("mkdir", directory)
        if rc != 0:
            return f"ERROR preparing control queue: {out.strip()[:240]}"
    request_path = ""
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", delete=False) as f:
            json.dump(request, f)
            f.write("\n")
            request_path = f.name
        remote = f"{NEST}/queue/control/requests/{request_id}.json"
        rc, out = _rclone("copyto", request_path, remote)
        if rc != 0:
            return f"ERROR publishing queue request: {out.strip()[:240]}"
    finally:
        if request_path:
            try:
                os.unlink(request_path)
            except OSError:
                pass

    ack_path = f"{NEST}/queue/control/acks/{request_id}.json"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        rc, data = _rclone("cat", ack_path)
        if rc == 0 and data:
            try:
                ack = json.loads(data)
                status = ack.get("status", "unknown")
                message = str(ack.get("message") or "").strip()
                return (f"{status}: boot {target[:8]}, request {request_id}"
                        + (f" — {message}" if message else ""))
            except Exception:
                pass
        time.sleep(2)
    return (f"QUEUED: request {request_id} targets boot {target[:8]}, "
            "but no notebook watcher acknowledged it within 45s. "
            "Ensure cell 1 is active and check colab_session_status.")


@mcp.tool()
def colab_queue_request_status(request_id: str) -> str:
    """Read status for a prior colab_queue_start request; does not change Drive."""
    try:
        request_id = uuid.UUID(hex=request_id).hex
    except (ValueError, TypeError, AttributeError):
        return "ERROR: request_id must be the hex id returned by colab_queue_start."
    ack_path = f"{NEST}/queue/control/acks/{request_id}.json"
    rc, data = _rclone("cat", ack_path)
    if rc == 0:
        try:
            ack = json.loads(data)
            return (f"{ack.get('status', 'unknown')}: "
                    f"boot {str(ack.get('target_boot_id') or '')[:8]} "
                    f"{str(ack.get('message') or '')[:500]}")
        except Exception:
            return "ERROR: control acknowledgement is unreadable."
    req_path = f"{NEST}/queue/control/requests/{request_id}.json"
    rc, data = _rclone("cat", req_path)
    if rc == 0:
        try:
            req = json.loads(data)
            age = time.time() - float(req.get("created_at") or 0)
            return (f"PENDING: {req.get('command')} for boot "
                    f"{str(req.get('target_boot_id') or '')[:8]} "
                    f"({age:.0f}s old)")
        except Exception:
            return "ERROR: control request is unreadable."
    return "NOT FOUND: no request or acknowledgement exists."


@mcp.tool()
def colab_pack_result(pack: str) -> str:
    """Read a pack's result JSON(s) from Drive (out/*.json)."""
    rc, out = _rclone("lsf", f"{_pack_dir(pack)}/out", "--files-only")
    if rc != 0:
        return f"ERROR: no out/ dir (rc={rc}): {out.strip()}"
    files = [l.strip() for l in out.splitlines() if l.strip().endswith(".json")]
    if not files:
        return f"(pack {pack}: no result json yet — queued or running)"
    results = []
    for f in files:
        _, data = _rclone("cat", f"{_pack_dir(pack)}/out/{f}")
        try:
            parsed = json.loads(data)
            results.append(f"{f}: {json.dumps(parsed, indent=1)}")
        except Exception:
            results.append(f"{f}: (non-json) {data[:300]}")
    return "\n\n".join(results)


@mcp.tool()
def colab_pack_submit(local_dir: str, pack_name: str) -> str:
    """Submit a local pack dir (containing pack.yml + optional inputs/) to
    ada-nest/packs/<pack_name>. Local dir is on the host running this MCP.
    Refuses to overwrite an existing pack.

    Under release pinning (queue/ACTIVE_RELEASE.json present) this always
    refuses: pack code ships only through reviewed commits published by
    scripts/colab/publish-release.py — a direct upload is unversioned
    code the pinned runner would never execute anyway."""
    ptr, _manifest = _active_release()
    if ptr.get("release_id"):
        return ("REFUSED: releases are pinned "
                f"({ptr['release_id']}). Commit the pack under "
                "scripts/colab/packs/ in chaba and let the release "
                "publisher ship it — ada-nest/packs/ is a state-only "
                "workspace now.")
    src = Path(local_dir).expanduser()
    yml = src / "pack.yml"
    if not yml.exists():
        return f"ERROR: {yml} not found"
    # runner keys claim/done/PACK_DIR off pack.yml's name: — it must equal
    # the target dir or markers land on a different pack.
    declared = ""
    for line in yml.read_text().splitlines():
        if line.startswith("name:"):
            declared = line.split(":", 1)[1].strip().strip("'\"")
            break
    if declared and declared != pack_name:
        return (f"ERROR: pack.yml name={declared!r} != pack_name={pack_name!r} "
                f"— the runner would write claim/done under packs/{declared}")
    rc, out = _rclone("lsf", _pack_dir(pack_name))
    if rc == 0:
        return f"ERROR: pack {pack_name} already exists on Drive"
    # copy pack.yml then inputs/ (best-effort)
    rc1, out1 = _rclone("copyto", str(src / "pack.yml"), f"{_pack_dir(pack_name)}/pack.yml")
    notes = []
    if rc1 == 0:
        notes.append("pack.yml uploaded")
    else:
        return f"ERROR uploading pack.yml: {out1.strip()}"
    inp = src / "inputs"
    if inp.is_dir():
        rc2, out2 = _rclone("copy", str(inp), f"{_pack_dir(pack_name)}/inputs", "--files-only")
        notes.append("inputs uploaded" if rc2 == 0 else f"inputs failed: {out2.strip()[:120]}")
    return "; ".join(notes)


@mcp.tool()
def colab_tunnel_check() -> str:
    """Check whether the Colab worker tunnel is live (probe the gateway's
    colab-qwen3 alias with a 1-token chat)."""
    key = _api_key()
    if not key:
        return "ERROR: LITELLM_KEY not available"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "say ok"}],
        "max_tokens": 5,
    }).encode()
    import urllib.request
    req = urllib.request.Request(
        f"{PROXY}/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
            c = d.get("choices", [{}])[0].get("message", {}).get("content", "")
            return f"TUNNEL UP: {MODEL} replied {c[:40]!r}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        return f"TUNNEL DOWN (HTTP {e.code}): {detail}"
    except Exception as e:
        return f"TUNNEL DOWN: {e}"


@mcp.tool()
def colab_model_probe(model: str = MODEL) -> str:
    """1-token chat through the LiteLLM gateway against any registered model
    (e.g. bench, ollama-qwen3, ollama-hermes8b, colab-qwen3)."""
    key = _api_key()
    if not key:
        return "ERROR: LITELLM_KEY not available"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "reply with just: ok"}],
        "max_tokens": 5,
    }).encode()
    import urllib.request
    req = urllib.request.Request(
        f"{PROXY}/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
            c = d.get("choices", [{}])[0].get("message", {}).get("content", "")
            return f"{model}: ok -> {c[:40]!r}"
    except urllib.error.HTTPError as e:
        return f"{model}: HTTP {e.code} {e.read().decode()[:160]}"
    except Exception as e:
        return f"{model}: {e}"


if __name__ == "__main__":
    mcp.run()