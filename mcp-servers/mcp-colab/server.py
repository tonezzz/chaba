#!/usr/bin/env python3
"""mcp-colab — Colab fleet control plane (OPS-0808).

Wraps the Drive-based nest-pack queue (ada-nest/packs) + the Colab tunnel
+ the LiteLLM gateway so agents/Ada/IDE can manage the free GPU lane
without poking Drive manually.

Tools:
  colab_pack_status  — list packs with claim/done state
  colab_pack_submit  — copy a local pack (pack.yml + inputs/) to Drive
  colab_pack_result  — read a pack's out/*.json results
  colab_tunnel_check — probe the Colab tunnel (idc03 loopback / proxy alias)
  colab_model_probe  — 1-token chat through the LiteLLM gateway

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
    """List nest packs with claim/done/result state (read-only)."""
    rc, out = _rclone("lsf", PACKS, "--dirs-only")
    if rc != 0:
        return f"ERROR listing packs: {out.strip()}"
    names = [l.strip().strip("/") for l in out.splitlines() if l.strip()]
    lines = []
    for n in sorted(names):
        entries = _rclone("lsf", _pack_dir(n), "--files-only")[1].splitlines()
        has_claim = any("/claim/" in e for e in entries)
        has_done = any(e.strip() == "done" for e in entries)
        has_out = any(e.startswith("out/") for e in entries)
        state = "DONE" if has_done else ("CLAIMED" if has_claim else ("OUT" if has_out else "queued"))
        lines.append(f"{n:<28} {state}")
    return "\n".join(lines) or "(no packs)"


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
    if not (src / "pack.yml").exists():
        return f"ERROR: {src}/pack.yml not found"
    rc, out = _rclone("lsf", _pack_dir(pack_name), "--dirs-only")
    if rc == 0 and out.strip():
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