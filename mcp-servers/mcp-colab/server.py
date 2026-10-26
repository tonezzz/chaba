#!/usr/bin/env python3
"""mcp-colab — Colab fleet control plane (OPS-0808).

Wraps the Drive-based nest-pack queue (ada-nest/packs) + the Colab tunnel
+ the LiteLLM gateway so agents/Ada/IDE can manage the free GPU lane
without poking Drive manually.

Tools:
  colab_pack_status    — list packs with claim/done state
  colab_session_status — managed-runtime registry + queue liveness
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
    return r.returncode, r.stdout


def _pack_dir(name: str) -> str:
    return f"{PACKS}/{name}"


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


@mcp.tool()
def colab_pack_status() -> str:
    """List nest packs with claim/done/result state (read-only).
    A dir only counts as a pack when it contains pack.yml — stray report
    dirs under packs/ are listed separately instead of showing 'queued'.
    CLAIMED requires a non-empty claim/ dir (the dir can linger empty
    after a worker released its claim)."""
    rc, out = _rclone("lsf", PACKS, "--dirs-only")
    if rc != 0:
        return f"ERROR listing packs: {out.strip()}"
    names = [l.strip().strip("/") for l in out.splitlines() if l.strip()]
    lines, not_packs = [], []
    for n in sorted(names):
        # default lsf lists files AND dirs (dirs end "/"); --files-only would
        # hide claim/ and out/ so CLAIMED/OUT could never display.
        entries = _rclone("lsf", _pack_dir(n))[1].splitlines()
        entries = [e.strip() for e in entries]
        if "pack.yml" not in entries:
            not_packs.append(n)
            continue
        has_done = "done" in entries
        has_out = "out/" in entries
        claimed = False
        if "claim/" in entries:
            claims = _rclone("lsf", f"{_pack_dir(n)}/claim", "--files-only")[1]
            claimed = any(l.strip() for l in claims.splitlines())
        state = "DONE" if has_done else ("CLAIMED" if claimed else ("OUT" if has_out else "queued"))
        lines.append(f"{n:<28} {state}")
    if not_packs:
        lines.append("")
        lines.append("not packs (no pack.yml): " + ", ".join(not_packs))
    return "\n".join(lines) or "(no packs)"


@mcp.tool()
def colab_session_status() -> str:
    """Managed-runtime registry + queue liveness (read-only).

    Reports every record under queue/runtime-sessions/ (boot_id, GPU, RAM, record
    age) with fresh/stale marking, plus queue/heartbeat, queue/lease and
    queue/runner.id — the same state the console notebook's session guard
    reads. Cannot see uninstrumented Colab sessions; Google Runtime >
    Manage Sessions remains authoritative for those."""
    import time
    lines = []
    rc, out = _rclone("lsf", f"{NEST}/queue/runtime-sessions", "--files-only")
    recs = []
    if rc == 0:
        for f in sorted(out.splitlines()):
            f = f.strip()
            if not f.endswith(".json"):
                continue
            _, data = _rclone("cat", f"{NEST}/queue/runtime-sessions/{f}")
            try:
                recs.append(json.loads(data))
            except Exception:
                recs.append({"boot_id": f, "unparseable": True})
    now = time.time()
    if recs:
        lines.append("managed runtimes (ttl 300s):")
        for r in recs:
            if r.get("unparseable"):
                lines.append(f"  {r['boot_id']}  UNPARSEABLE record")
                continue
            age = now - float(r.get("ts") or 0)
            mark = "fresh" if age <= 300 else f"STALE {age/60:.0f}min"
            runner = r.get("runner") or {}
            rbit = f" runner={runner.get('worker')}" if runner.get("worker") else ""
            lines.append(
                f"  {str(r.get('boot_id'))[:8]}  {r.get('gpu') or 'cpu'} "
                f"{r.get('gpu_gb') or 0}GB  ram {r.get('ram_gb')}GB  "
                f"{mark}{rbit}")
    else:
        lines.append("managed runtimes: none registered")
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
                     f"{str(d.get('boot_id'))[:8]} {d.get('worker')}")
    except Exception:
        lines.append("runner.id: absent")
    return "\n".join(lines)


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
    Refuses to overwrite an existing pack."""
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