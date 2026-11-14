#!/usr/bin/env python3
"""render.py — bounded single-image SDXL render on KK-Mac.

Card adobe-stock-kk-mac-render-poc: the controlled pack that renders one
approved comparison image for the Adobe Stock Nest pipeline. pack.yml's
run_sh execs this file with the dedicated
``~/.local/share/kk-mac-image-renderer`` venv interpreter (torch +
diffusers, MPS). Heavy imports are deferred into ``render_one`` so this
module stays stdlib-importable for repo contract tests.

Gate order is fixed; every check lands in ``out/preflight.json``. Any
failure writes ``out/verdict.json`` (verdict fail) and exits nonzero —
the worker marks the pack failed, no done marker, no retry. On a gate
failure nothing is uploaded back, so failing closed also means no
misleading artifacts on the store.

Safety contract: no Adobe upload, no browser/GUI, no credential reads,
no shell, exactly one image (render.count must be 1), model weights only
from the pinned local snapshot (HF offline flags + local_files_only),
no automatic retry.

Checks (stable ids — keep order):
  request_parses, request_approved, owner_approved, approval_recorded,
  adobe_upload_disabled, single_render, render_bounds, output_name_safe,
  prompt_present, render_window, venv_isolated, manifest_pinned,
  model_pin_match, snapshot_present, disk_floor, load_limit

Request contract: see inputs/render-request.json (disabled template).
Model manifest contract: ``$VENV/model-manifest.json`` carries
model_id + revision (+ optional snapshot_dir / required_files); the
request's model block must equal it and the pinned snapshot must exist
locally — anything else fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import socket
import struct
import sys
import time
import traceback
from datetime import datetime, timezone

PACK_NAME = "kk-mac-image-render-poc"
SCHEMA = 1
VENV_DIR = "~/.local/share/kk-mac-image-renderer"
MANIFEST_NAME = "model-manifest.json"
REQUEST_NAME = os.path.join("inputs", "render-request.json")

OUTPUT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.png")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
DEFAULT_REQUIRED_FILES = ("model_index.json",)
PROMPT_MAX = 4000
SIDE_MIN, SIDE_MAX = 256, 1536
STEPS_MAX = 60
GUIDANCE_MAX = 20.0


def _check(cid, ok, detail):
    return {"id": cid, "status": "pass" if ok else "fail",
            "detail": str(detail)[:300]}


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _iso_to_epoch(value):
    """ISO-8601 -> epoch seconds, or None on anything unparseable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def png_dims(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return int(w), int(h)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_dir_for(manifest):
    """Where the pinned weights must already live. Manifest may name the
    dir explicitly; otherwise the standard HF hub cache layout is derived
    from model_id + revision. Never downloads."""
    if not isinstance(manifest, dict):
        return None
    sd = manifest.get("snapshot_dir")
    if isinstance(sd, str) and sd.strip():
        return os.path.abspath(os.path.expanduser(sd))
    mid, rev = manifest.get("model_id"), manifest.get("revision")
    if isinstance(mid, str) and isinstance(rev, str):
        hf_home = os.environ.get("HF_HOME") or "~/.cache/huggingface"
        return os.path.join(os.path.expanduser(hf_home), "hub",
                            "models--" + mid.replace("/", "--"),
                            "snapshots", rev)
    return None


def gather_facts(pack_dir, venv_dir=None, now=None):
    """Host-side facts the gates evaluate. Kept separate from evaluate()
    so tests can inject synthetic facts instead of touching the host."""
    venv_dir = os.path.abspath(os.path.expanduser(venv_dir or VENV_DIR))
    facts = {
        "now": time.time() if now is None else now,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "venv_dir": venv_dir,
        "venv_python": os.path.join(venv_dir, "bin", "python"),
        "sys_prefix": sys.prefix,
        "sys_executable": sys.executable,
    }
    try:
        st = os.statvfs(pack_dir)
        facts["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 2)
    except OSError as exc:
        facts["disk_free_gb"] = None
        facts["disk_error"] = str(exc)
    try:
        facts["load_1m"] = round(os.getloadavg()[0], 3)
    except OSError:
        facts["load_1m"] = None
    manifest, manifest_error = None, None
    try:
        with open(os.path.join(venv_dir, MANIFEST_NAME),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        if not isinstance(manifest, dict):
            manifest, manifest_error = None, "manifest_not_a_mapping"
    except (OSError, ValueError) as exc:
        manifest_error = f"{type(exc).__name__}: {exc}"
    facts["manifest"] = manifest
    facts["manifest_error"] = manifest_error
    sd = snapshot_dir_for(manifest)
    facts["snapshot_dir"] = sd
    facts["snapshot_missing"] = []
    if sd and isinstance(manifest, dict):
        required = manifest.get("required_files") or DEFAULT_REQUIRED_FILES
        facts["snapshot_missing"] = [
            rel for rel in required
            if not os.path.isfile(os.path.join(sd, rel))]
    return facts


def _as_map(value):
    return value if isinstance(value, dict) else {}


def evaluate(request, facts):
    """Ordered gate list. `request` is either the parsed dict or an error
    string (anything non-dict fails at request_parses)."""
    if not isinstance(request, dict):
        return [_check("request_parses", False,
                       f"render-request.json unreadable: {request}")]
    checks = [_check("request_parses", True, "request is a JSON object")]

    status = request.get("status")
    checks.append(_check(
        "request_approved", status == "approved",
        f"status={status!r} — requires 'approved'"))
    checks.append(_check(
        "owner_approved", request.get("owner_approved") is True,
        f"owner_approved={request.get('owner_approved')!r} — must be true"))
    by = request.get("approved_by")
    checks.append(_check(
        "approval_recorded",
        isinstance(by, str) and bool(by.strip()),
        f"approved_by={by!r} — must name the approver"))
    au = request.get("adobe_upload")
    checks.append(_check(
        "adobe_upload_disabled", au is False,
        f"adobe_upload={au!r} — must be explicitly false"))

    render = _as_map(request.get("render"))
    checks.append(_check(
        "single_render", render.get("count") == 1,
        f"render.count={render.get('count')!r} — exactly one image, "
        "no batch generation"))
    problems = []
    for key in ("width", "height"):
        v = render.get(key)
        if (not isinstance(v, int) or isinstance(v, bool) or v % 8
                or not SIDE_MIN <= v <= SIDE_MAX):
            problems.append(
                f"{key}={v!r} (int, multiple of 8, {SIDE_MIN}-{SIDE_MAX})")
    v = render.get("num_inference_steps")
    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= STEPS_MAX:
        problems.append(f"num_inference_steps={v!r} (int 1-{STEPS_MAX})")
    v = render.get("guidance_scale")
    if (not isinstance(v, (int, float)) or isinstance(v, bool)
            or not 0 <= float(v) <= GUIDANCE_MAX):
        problems.append(f"guidance_scale={v!r} (0-{GUIDANCE_MAX})")
    v = render.get("seed")
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        problems.append(f"seed={v!r} (int >= 0)")
    checks.append(_check(
        "render_bounds", not problems,
        "; ".join(problems) or (
            f"{render.get('width')}x{render.get('height')} "
            f"steps={render.get('num_inference_steps')} "
            f"cfg={render.get('guidance_scale')} "
            f"seed={render.get('seed')}")))
    name = request.get("output_name")
    checks.append(_check(
        "output_name_safe",
        isinstance(name, str) and OUTPUT_NAME_RE.fullmatch(name) is not None,
        f"output_name={name!r} — must be a plain *.png basename"))
    prompt = request.get("prompt")
    checks.append(_check(
        "prompt_present",
        isinstance(prompt, str) and 0 < len(prompt.strip()) <= PROMPT_MAX,
        f"prompt len={len(prompt) if isinstance(prompt, str) else prompt!r} "
        f"(1-{PROMPT_MAX} chars)"))

    window = request.get("render_window")
    if window is None:
        checks.append(_check(
            "render_window", True, "no window declared — approval is the gate"))
    else:
        nb = _iso_to_epoch(_as_map(window).get("not_before_utc"))
        na = _iso_to_epoch(_as_map(window).get("not_after_utc"))
        ok = nb is not None and na is not None and nb <= facts["now"] <= na
        checks.append(_check(
            "render_window", ok,
            f"window={window!r} now={datetime.fromtimestamp(facts['now'], timezone.utc).isoformat()}"))

    vpy = facts["venv_python"]
    in_venv = (os.path.realpath(facts["sys_prefix"])
               == os.path.realpath(facts["venv_dir"]))
    checks.append(_check(
        "venv_isolated", os.path.isfile(vpy) and in_venv,
        f"sys.prefix={facts['sys_prefix']} expected venv "
        f"{facts['venv_dir']} (python {'present' if os.path.isfile(vpy) else 'missing'})"))

    man = facts.get("manifest")
    man_ok = (man is not None
              and isinstance(man.get("model_id"), str)
              and REVISION_RE.fullmatch(str(man.get("revision", ""))))
    checks.append(_check(
        "manifest_pinned", man_ok,
        facts.get("manifest_error")
        or f"model_id={man.get('model_id')!r} revision={man.get('revision')!r}"))
    req_model = _as_map(request.get("model"))
    checks.append(_check(
        "model_pin_match",
        man is not None
        and req_model.get("id") == man.get("model_id")
        and req_model.get("revision") == man.get("revision"),
        f"request model={req_model.get('id')!r}@{req_model.get('revision')!r} "
        f"vs manifest "
        f"{man.get('model_id') if man else None!r}@"
        f"{man.get('revision') if man else None!r}"))

    sd = facts.get("snapshot_dir")
    missing = facts.get("snapshot_missing") or []
    checks.append(_check(
        "snapshot_present",
        bool(sd) and os.path.isdir(sd) and not missing,
        f"snapshot_dir={sd} "
        + (f"missing={missing}" if missing else
           ("present" if sd and os.path.isdir(sd) else "absent"))))

    limits = _as_map(request.get("limits"))
    floor = limits.get("min_disk_free_gb")
    free = facts.get("disk_free_gb")
    checks.append(_check(
        "disk_floor",
        isinstance(floor, (int, float)) and free is not None
        and free >= float(floor),
        f"disk_free_gb={free} vs limits.min_disk_free_gb={floor!r}"))
    cap = limits.get("max_load_1m")
    load = facts.get("load_1m")
    checks.append(_check(
        "load_limit",
        isinstance(cap, (int, float)) and load is not None
        and load <= float(cap),
        f"load_1m={load} vs limits.max_load_1m={cap!r}"))
    return checks


def _request_summary(request):
    if not isinstance(request, dict):
        return {}
    return {"request_id": request.get("request_id"),
            "campaign": request.get("campaign")}


def _fail_verdict(request, checks, started, reasons=None):
    return {
        "schema": SCHEMA,
        "pack": PACK_NAME,
        "verdict": "fail",
        "request_id": request.get("request_id") if isinstance(request, dict) else None,
        "campaign": request.get("campaign") if isinstance(request, dict) else None,
        "reasons": reasons if reasons is not None else [
            c["id"] for c in checks if c["status"] != "pass"],
        "adobe_upload": False,
        "rendered": False,
        "wall_seconds": round(time.time() - started, 2),
        "at": datetime.now(timezone.utc).isoformat(),
    }


def _wall_alarm(signum, frame):
    raise TimeoutError("render exceeded limits.max_wall_seconds")


def render_one(request, facts, out_dir):
    """The only code path that touches torch/diffusers — reached solely
    after every gate passed. One prompt, one seed, one image, local
    weights only, CPU fp32 VAE decode (the proven KK-Mac MPS path: fp16
    VAE on MPS yields black frames and stalls)."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    import torch
    import diffusers
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline

    r = request["render"]
    snapshot = facts["snapshot_dir"]
    t_load = time.time()
    vae = AutoencoderKL.from_pretrained(
        snapshot, subfolder="vae", torch_dtype=torch.float32,
        local_files_only=True)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        snapshot, torch_dtype=torch.float16, variant="fp16", vae=vae,
        use_safetensors=True, local_files_only=True)
    pipe.to("mps")
    vae.to("cpu")          # decode on CPU in fp32 — never on MPS
    pipe.set_progress_bar_config(disable=True)
    load_s = time.time() - t_load

    gen = torch.Generator(device="cpu").manual_seed(int(r["seed"]))
    t_gen = time.time()
    with torch.no_grad():
        latents = pipe(
            prompt=request["prompt"],
            negative_prompt=request.get("negative_prompt") or None,
            width=int(r["width"]), height=int(r["height"]),
            num_inference_steps=int(r["num_inference_steps"]),
            guidance_scale=float(r["guidance_scale"]),
            num_images_per_prompt=1,
            generator=gen,
            output_type="latent",
        ).images.to("cpu", torch.float32)
        decoded = vae.decode(latents / vae.config.scaling_factor).sample
    image = pipe.image_processor.postprocess(decoded, output_type="pil")[0]
    render_s = time.time() - t_gen

    out_path = os.path.join(out_dir, request["output_name"])
    tmp = out_path + ".tmp"
    image.save(tmp, format="PNG")
    os.replace(tmp, out_path)
    return {
        "path": out_path,
        "file": f"out/{request['output_name']}",
        "sha256": sha256_file(out_path),
        "bytes": os.path.getsize(out_path),
        "load_s": round(load_s, 2),
        "render_s": round(render_s, 2),
        "torch": torch.__version__,
        "diffusers": diffusers.__version__,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack-dir",
                    default=os.environ.get("PACK_DIR")
                    or os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--request", default=None,
                    help="default <pack-dir>/inputs/render-request.json")
    ap.add_argument("--out-dir", default=None,
                    help="default <pack-dir>/out")
    ap.add_argument("--preflight-only", action="store_true",
                    help="run gates + write preflight.json, never render")
    args = ap.parse_args(argv)

    pack_dir = os.path.abspath(args.pack_dir)
    out_dir = args.out_dir or os.path.join(pack_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    req_path = args.request or os.path.join(pack_dir, REQUEST_NAME)
    started = time.time()

    request_bytes = b""
    try:
        with open(req_path, "rb") as fh:
            request_bytes = fh.read()
        request = json.loads(request_bytes.decode("utf-8"))
        if not isinstance(request, dict):
            request = "not a JSON object"
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        request = f"{type(exc).__name__}: {exc}"

    facts = gather_facts(pack_dir, now=started)
    checks = evaluate(request, facts)
    verdict = ("pass" if all(c["status"] == "pass" for c in checks)
               else "fail")
    preflight = {
        "schema": SCHEMA,
        "pack": PACK_NAME,
        "verdict": verdict,
        "checks": checks,
        "host": {"hostname": facts["hostname"],
                 "platform": facts["platform"],
                 "load_1m": facts.get("load_1m"),
                 "disk_free_gb": facts.get("disk_free_gb")},
        "at": datetime.now(timezone.utc).isoformat(),
        **_request_summary(request),
    }
    _write_json(os.path.join(out_dir, "preflight.json"), preflight)
    print(f"preflight verdict={verdict} checks="
          f"{sum(c['status'] == 'pass' for c in checks)}/{len(checks)}",
          flush=True)

    if verdict != "pass":
        _write_json(os.path.join(out_dir, "verdict.json"),
                    _fail_verdict(request, checks, started))
        for c in checks:
            if c["status"] != "pass":
                print(f"  FAIL {c['id']}: {c['detail']}", file=sys.stderr)
        return 2
    if args.preflight_only:
        return 0

    # request-declared wall budget: SIGALRM lands between denoise steps
    # (the loop is Python-driven) — an overrun fails closed, no PNG.
    wall_cap = _as_map(request.get("limits")).get("max_wall_seconds")
    armed = isinstance(wall_cap, (int, float)) and not isinstance(
        wall_cap, bool) and wall_cap > 0
    if armed:
        signal.signal(signal.SIGALRM, _wall_alarm)
        signal.alarm(int(wall_cap))
    try:
        result = render_one(request, facts, out_dir)
    except Exception:
        traceback.print_exc()
        for stale in os.listdir(out_dir):
            if stale.endswith(".tmp"):
                try:
                    os.remove(os.path.join(out_dir, stale))
                except OSError:
                    pass
        _write_json(os.path.join(out_dir, "verdict.json"),
                    _fail_verdict(request, checks, started,
                                  reasons=[f"render_error:"
                                           f"{traceback.format_exc().splitlines()[-1][:200]}"]))
        return 1
    finally:
        if armed:
            signal.alarm(0)

    dims = png_dims(open(result["path"], "rb").read()) or (
        request["render"]["width"], request["render"]["height"])
    output = {"file": result["file"], "sha256": result["sha256"],
              "bytes": result["bytes"], "width": dims[0], "height": dims[1]}
    manifest_doc = {
        "schema": SCHEMA,
        "pack": PACK_NAME,
        "request": request,
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "model": {"id": request["model"]["id"],
                  "revision": request["model"]["revision"],
                  "snapshot_dir": facts["snapshot_dir"]},
        "runtime": {"python": platform.python_version(),
                    "executable": facts["sys_executable"],
                    "torch": result["torch"],
                    "diffusers": result["diffusers"],
                    "device": "mps",
                    "vae_decode": "cpu/fp32",
                    "hostname": facts["hostname"]},
        "timing": {"load_s": result["load_s"],
                   "render_s": result["render_s"],
                   "wall_s": round(time.time() - started, 2)},
        "output": output,
        "safety": {"adobe_upload": False, "batch": False,
                   "hf_offline": True, "auto_retry": False},
        "at": datetime.now(timezone.utc).isoformat(),
        **_request_summary(request),
    }
    _write_json(os.path.join(out_dir, "render-manifest.json"), manifest_doc)
    verdict_doc = {
        "schema": SCHEMA,
        "pack": PACK_NAME,
        "verdict": "pass",
        "output": output,
        "model": {"id": request["model"]["id"],
                  "revision": request["model"]["revision"]},
        "adobe_upload": False,
        "rendered": True,
        "wall_seconds": round(time.time() - started, 2),
        "at": datetime.now(timezone.utc).isoformat(),
        **_request_summary(request),
    }
    _write_json(os.path.join(out_dir, "verdict.json"), verdict_doc)
    print(json.dumps({"verdict": "pass", "output": output,
                      "render_s": result["render_s"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
