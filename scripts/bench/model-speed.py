#!/usr/bin/env python3
"""model-speed.py — one harness, fixed prompt set, identical across hosts.

Card: model-fleet-benchmark (docs/kb/model-fleet-benchmark-plan.md)

Per (host x model): N timed runs of a fixed 3-prompt suite
(short QA / ~500-token generation / Thai prompt). Records TTFT, decode
tok/s, peak server RSS (VmHWM delta where readable), warm-vs-cold delta.
Results append as JSON under reports/model-bench/.

Targets:
  ollama       native /api/generate (precise eval_count/eval_duration)
  openai       OpenAI-compat /v1/chat/completions, streamed (llama.cpp,
               vllm, remote ollama /v1 — anything OpenAI-shaped)
  ssh_openai   same call piped over ssh to a remote loopback endpoint
               (ssh prefix from --ssh, e.g. "idc02" or
               "tony-dell ssh -o BatchMode=yes macbook" for a hop)

Usage:
  model-speed.py --provider ollama --base-url http://127.0.0.1:11434 \
      --model llama3.2:1b --host-tag tony-omen
  model-speed.py --provider ssh_openai --ssh idc02 --remote-port 8114 \
      --model bench --host-tag idc02
  model-speed.py --targets scripts/bench/targets.example.yml
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SUITE = [
    {"id": "short_qa", "max_tokens": 32,
     "prompt": "What is the capital of Thailand? Answer in one sentence."},
    {"id": "gen500", "max_tokens": 600,
     "prompt": "Write a detailed 500-word explanation of how a transformer "
               "neural network works."},
    {"id": "thai", "max_tokens": 200,
     "prompt": "อธิบายวิธีทำต้มยำกุ้งแบบสั้น ๆ"},
]

REPO_REPORTS = Path(__file__).resolve().parents[2] / "reports" / "model-bench"


# ---------- transports ----------

def _post(url, payload, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _post_stream(url, payload, timeout):
    """Yield parsed SSE/JSONL objects with monotonic timestamps."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line or line == "data: [DONE]":
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                yield time.monotonic(), json.loads(line)
            except json.JSONDecodeError:
                continue


def ollama_generate(base_url, model, prompt, max_tokens, timeout):
    """Native ollama generate — precise eval counts/durations."""
    t0 = time.monotonic()
    ttft = None
    last = None
    for ts, obj in _post_stream(
            base_url.rstrip("/") + "/api/generate",
            {"model": model, "prompt": prompt, "stream": True,
             "options": {"num_predict": max_tokens, "temperature": 0}},
            timeout):
        if ttft is None and obj.get("response"):
            ttft = ts - t0
        last = obj
        if obj.get("done"):
            break
    wall = time.monotonic() - t0
    last = last or {}
    eval_count = last.get("eval_count") or 0
    eval_ns = last.get("eval_duration") or 0
    return {
        "ttft_ms": round((ttft or wall) * 1000),
        "wall_ms": round(wall * 1000),
        "completion_tokens": eval_count,
        "decode_toks": round(eval_count / (eval_ns / 1e9), 2) if eval_ns else None,
        "prefill_toks": round((last.get("prompt_eval_count") or 0) /
                            ((last.get("prompt_eval_duration") or 1) / 1e9), 2),
        "load_ms": round((last.get("load_duration") or 0) / 1e6),
        "text_tail": (last.get("response") or "")[-40:],
    }


def openai_chat(base_url, model, prompt, max_tokens, timeout, ssh=None):
    """OpenAI-compat streamed chat; ssh pipes the same call to a remote
    loopback endpoint (payload over stdin, curl on the far side)."""
    payload = json.dumps({
        "model": model, "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "stream": True,
        "stream_options": {"include_usage": True}})
    url = base_url.rstrip("/") + "/v1/chat/completions"
    t0 = time.monotonic()
    ttft = None
    chunks = 0
    usage = {}
    first_t = last_t = None

    if ssh:
        cmd = (f"ssh -o BatchMode=yes {ssh} curl -sS --max-time {int(timeout)}"
               f" -N -X POST {url} -H Content-Type:application/json"
               " --data-binary @-")
        proc = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)
        proc.stdin.write(payload)
        proc.stdin.close()
        lines = proc.stdout
    else:
        lines = _post_stream(url, json.loads(payload), timeout)

    def _iter():
        for item in lines:
            if isinstance(item, tuple):          # _post_stream yields (ts, obj)
                yield item
            else:                                # ssh stdout yields raw lines
                line = item.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                try:
                    yield time.monotonic(), json.loads(line)
                except json.JSONDecodeError:
                    continue

    for ts, obj in _iter():
        delta = ((obj.get("choices") or [{}])[0].get("delta") or {})
        if delta.get("content"):
            chunks += 1
            last_t = ts
            if ttft is None:
                ttft = ts - t0
                first_t = ts
        if obj.get("usage"):
            usage = obj["usage"]
    wall = time.monotonic() - t0
    if ssh:
        proc.wait(timeout=10)

    comp = usage.get("completion_tokens") or chunks
    decode_s = (last_t - first_t) if (first_t and last_t and last_t > first_t) else None
    return {
        "ttft_ms": round((ttft or wall) * 1000),
        "wall_ms": round(wall * 1000),
        "completion_tokens": comp,
        "decode_toks": round(comp / decode_s, 2) if decode_s else None,
        "prefill_toks": None,
        "load_ms": None,
        "token_source": "usage" if usage else "chunks",
    }


# ---------- memory probes ----------

def _vmhwm_kb(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM"):
                return int(line.split()[1])
    except Exception:
        return None
    return None


def _find_server_pid(base_url):
    """Local server pid bound to the target port; for ollama prefer the
    `ollama runner` child that actually holds the model."""
    port = base_url.rsplit(":", 1)[-1].split("/")[0]
    try:
        out = subprocess.check_output(
            f"ss -tlnp 2>/dev/null | grep ':{port} '", shell=True, text=True)
        m = re.search(r"pid=(\d+)", out)
        if not m:
            return None
        pid = int(m.group(1))
        children = Path(f"/proc/{pid}/task/{pid}/children")
        if children.exists():
            for cpid in children.read_text().split():
                cmdline = Path(f"/proc/{cpid}/cmdline").read_bytes()
                if b"runner" in cmdline or b"llama" in cmdline:
                    return int(cpid)
        return pid
    except Exception:
        return None


def _remote_hwm_kb(ssh, pattern):
    try:
        out = subprocess.check_output(
            f"ssh -o BatchMode=yes {ssh} "
            f"\"pgrep -f '{pattern}' | head -1 | xargs -r grep VmHWM /proc/*/status 2>/dev/null "
            f"| grep -o '[0-9]*' | head -1\"",
            shell=True, text=True, timeout=15)
        return int(out.strip()) if out.strip().isdigit() else None
    except Exception:
        return None


# ---------- runner ----------

def run_target(tcfg, runs, timeout, out_dir):
    provider = tcfg["provider"]
    model = tcfg["model"]
    host_tag = tcfg.get("host_tag", "unknown")
    ssh = tcfg.get("ssh")
    if provider == "ollama":
        base_url = tcfg["base_url"]
    else:
        port = tcfg.get("remote_port", 8114)
        base_url = tcfg.get("base_url") or f"http://127.0.0.1:{port}"

    pid = _find_server_pid(base_url) if not ssh else None
    hwm_before = _vmhwm_kb(pid) if pid else (
        _remote_hwm_kb(ssh, tcfg.get("remote_proc", "llama")) if ssh else None)

    result = {"host": host_tag, "model": model, "provider": provider,
              "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "runs": []}
    for i in range(runs):
        for p in SUITE:
            try:
                if provider == "ollama":
                    r = ollama_generate(base_url, model, p["prompt"],
                                        p["max_tokens"], timeout)
                else:
                    r = openai_chat(base_url, model, p["prompt"],
                                    p["max_tokens"], timeout, ssh=ssh)
                r.update({"run": i, "prompt": p["id"], "ok": True,
                          "warm": i > 0})
            except Exception as e:
                r = {"run": i, "prompt": p["id"], "ok": False,
                     "error": str(e)[:200]}
            result["runs"].append(r)
            print(f"  [{host_tag}/{model}] run{i} {p['id']}: "
                  f"{r.get('decode_toks')} tok/s ttft={r.get('ttft_ms')}ms"
                  f"{'' if r.get('ok') else ' ERR ' + r.get('error','')}",
                  flush=True)

    hwm_after = _vmhwm_kb(pid) if pid else (
        _remote_hwm_kb(ssh, tcfg.get("remote_proc", "llama")) if ssh else None)
    result["peak_rss_mb"] = round((hwm_after or 0) / 1024) if hwm_after else None
    result["rss_grew_mb"] = (round((hwm_after - hwm_before) / 1024)
                             if hwm_after and hwm_before else None)

    ok = [r for r in result["runs"] if r.get("ok") and r.get("decode_toks")]
    if ok:
        cold = [r for r in ok if not r["warm"]]
        warm = [r for r in ok if r["warm"]]
        result["summary"] = {
            "decode_toks_median": sorted(r["decode_toks"] for r in ok)[len(ok) // 2],
            "decode_toks_warm": (round(sum(r["decode_toks"] for r in warm) / len(warm), 2)
                                  if warm else None),
            "decode_toks_cold": (round(sum(r["decode_toks"] for r in cold) / len(cold), 2)
                                  if cold else None),
            "ttft_ms_median": sorted(r["ttft_ms"] for r in ok)[len(ok) // 2],
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", model)
    path = out_dir / f"{host_tag}-{safe}-{ts}.json"
    path.write_text(json.dumps(result, indent=2))
    print(f"  -> {path}")
    _update_meta(out_dir, result, path.name)
    return result


def _update_meta(out_dir, result, filename):
    """L1 meta so system-report can read state without parsing artifacts."""
    meta_path = out_dir / "meta.model-bench.yml"
    meta = {}
    if meta_path.exists():
        try:
            import yaml  # noqa
            meta = yaml.safe_load(meta_path.read_text()) or {}
        except Exception:
            meta = {}
    cell = f"{result['host']}/{result['model']}"
    meta.setdefault("id", "model-bench")
    meta["layer"] = "L1-producer"
    meta["generated_at"] = result["at"]
    meta["status"] = "ok"
    meta["last_run"] = result["at"]
    cells = meta.setdefault("cells", {})
    cells[cell] = {
        "artifact": filename,
        "provider": result["provider"],
        **(result.get("summary") or {}),
        "peak_rss_mb": result.get("peak_rss_mb"),
    }
    meta["summary"] = f"{len(cells)} model cells"
    try:
        import yaml
        meta_path.write_text(yaml.safe_dump(meta, sort_keys=False))
    except ImportError:
        # stdlib fallback — flat dump good enough for the meta reader
        lines = [f"id: model-bench", "layer: L1-producer",
                 f"generated_at: \"{meta['generated_at']}\"",
                 "status: ok", f"last_run: \"{meta['last_run']}\"",
                 f"summary: \"{meta['summary']}\"", "cells:"]
        for k, v in cells.items():
            lines.append(f"  \"{k}\":")
            for kk, vv in v.items():
                lines.append(f"    {kk}: {json.dumps(vv)}")
        meta_path.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", help="yaml file: list of target cfgs")
    ap.add_argument("--provider", choices=["ollama", "openai", "ssh_openai"])
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--ssh")
    ap.add_argument("--remote-port", type=int, default=8114)
    ap.add_argument("--host-tag", default=os.uname().nodename)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", default=str(REPO_REPORTS))
    ap.add_argument("--push-meta",
                    help="scp meta.model-bench.yml to <host>:<dir> after the "
                         "run — remote push-back contract (ssot.reports.yml "
                         "contract.remote_pushback)")
    args = ap.parse_args()

    targets = []
    if args.targets:
        import yaml
        targets = yaml.safe_load(Path(args.targets).read_text())
    elif args.provider and args.model:
        targets = [{"provider": args.provider, "base_url": args.base_url,
                    "model": args.model, "ssh": args.ssh,
                    "remote_port": args.remote_port,
                    "host_tag": args.host_tag}]
    else:
        ap.error("need --targets or --provider + --model")

    failures = 0
    for t in targets:
        try:
            run_target(t, args.runs, args.timeout, Path(args.out))
        except Exception as e:
            print(f"TARGET FAILED {t}: {e}", file=sys.stderr)
            failures += 1

    meta = Path(args.out) / "meta.model-bench.yml"
    if meta.exists():
        try:
            import yaml
            data = yaml.safe_load(meta.read_text()) or {}
            data["status"] = "error" if failures else "ok"
            data["summary"] = (f"{len(data.get('cells', {}))} model cells; "
                               f"{failures} target failure(s)")
            meta.write_text(yaml.safe_dump(data, sort_keys=False))
        except Exception as e:
            print(f"META UPDATE FAILED: {e}", file=sys.stderr)
            failures += 1

    if args.push_meta:
        try:
            if not meta.is_file():
                raise FileNotFoundError(meta)
            subprocess.run(["scp", "-q", str(meta), args.push_meta],
                           check=True, timeout=30)
            print(f"meta pushed -> {args.push_meta}")
        except Exception as e:
            print(f"META PUSH FAILED {args.push_meta}: {e}",
                  file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
