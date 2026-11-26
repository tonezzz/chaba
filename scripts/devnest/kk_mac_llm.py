#!/usr/bin/env python3
"""Bounded read-only task adapter for the online KK-Mac LLM lane.

This is intentionally not a shell or code-execution bridge. It admits only
small text tasks, checks the heartbeat gate first, and calls the loopback
Ollama API through SSH (or directly when the lane worker runs on the node).
run_task's default path is generate_guarded — a streamed call that polls
memory through model load AND generation, aborts below the approved floors,
and unloads only a model the task itself loaded (MEM-1043). Callers still
need an independent verifier.
"""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Callable

try:
    from .kk_mac_admission import snapshot
    from . import kk_mac_memory
except ImportError:  # direct script execution
    from kk_mac_admission import snapshot
    import kk_mac_memory

# Admitted task classes — narrowed 2026-11-23 (card
# kk-mac-admitted-classes-narrow) after the 2026-11-19 class eval
# (docs/ssot/jobs/devnest/2026-11-19-kkmac-class-eval.yml): only
# structured_extract proved READY (0.93-1.00 pass under the production
# verifier); operator_brief and safe_route stay verifier-supported for
# re-bench but are unadmitted until a re-eval passes.
ALLOWED_TASKS = {
    "summary",
    "structured_extract",
}
MAX_PROMPT_CHARS = 6000
LOCAL_HOSTS = frozenset({"local", "localhost", "127.0.0.1", "::1"})
OLLAMA_LOCAL_URL = "http://127.0.0.1:11434"


def is_local_host(host: str) -> bool:
    """True when the LLM target is this machine's own Ollama — the
    dedicated lane worker runs on KK-Mac itself, so the same executor
    contract serves both the ssh path (fleet runners) and the local path
    (on-host launchd worker) without a second implementation."""
    return str(host or "").strip().lower() in LOCAL_HOSTS


def validate_task(task_class: str, prompt: str) -> None:
    if task_class not in ALLOWED_TASKS:
        raise ValueError(f"task class not admitted: {task_class}")
    if not prompt.strip():
        raise ValueError("prompt is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("prompt exceeds read-only lane limit")


def _generate_payload(model: str, prompt: str, format: str | None,
                      think: bool | None, stream: bool = False) -> bytes:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": bool(stream),
        # bounded lane: no chain-of-thought burn — qwen3 thinking is
        # what stalled the first 2026-10-30 packs
        "think": False if think is None else bool(think),
        "options": {"temperature": 0},
    }
    if format:
        body["format"] = format
    return json.dumps(body).encode()


def _call_local(payload: bytes, url: str,
                urlopen: Callable = urllib.request.urlopen) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate", data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=300) as response:
            return json.loads(response.read())
    except Exception as exc:
        raise RuntimeError(f"local ollama failed:{type(exc).__name__}:"
                           f"{exc}"[:400]) from exc


def call_remote(
    prompt: str,
    *,
    host: str = "kk-mac",
    model: str = "qwen2.5:32b",
    format: str | None = None,
    think: bool | None = None,
    local_url: str = OLLAMA_LOCAL_URL,
    ssh_run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    urlopen: Callable = urllib.request.urlopen,
) -> dict:
    payload = _generate_payload(model, prompt, format, think)
    if is_local_host(host):
        return _call_local(payload, local_url, urlopen=urlopen)
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host,
        "curl -fsS http://127.0.0.1:11434/api/generate "
        "-H 'Content-Type: application/json' --data-binary @-",
    ]
    result = ssh_run(command, input=payload, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError((result.stderr or b"ssh/ollama failed").decode(
            errors="replace"
        )[:500])
    try:
        return json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("KK-Mac returned non-JSON Ollama output") from exc


# --- live memory guard (card kk-mac-live-memory-guard, MEM-1043) ---
#
# The 2026-11-23 lane soak showed detection-only monitoring is too late:
# verdicts flipped to fallback only after generation ran to completion
# under real pressure. generate_guarded therefore polls memory IN-BIND
# while the NDJSON stream is consumed — the queue timeout is the poll
# tick, so the silent model-LOAD window (Ollama emits nothing until
# weights are resident) is covered, and a breach closes the response /
# kills the ssh client, which makes Ollama drop the generation.
#
# Unload policy: after the call, a model is unloaded (keep_alive=0)
# ONLY when /api/ps proved it absent before this task ran. An
# owner-resident model — or an unknown residency probe — is never
# touched.

GUARD_POLL_LOCAL_S = 1.0
GUARD_POLL_REMOTE_S = 2.0
GUARD_MAX_UNMEASURABLE = 3
_USAGE_KEYS = ("prompt_eval_count", "eval_count", "eval_duration",
               "load_duration", "total_duration", "done",
               "done_reason")


def _open_local_stream(payload: bytes, url: str,
                       urlopen: Callable = urllib.request.urlopen
                       ) -> tuple:
    """-> (line_queue, abort, box). abort() closes the HTTP response,
    which unblocks the reader and makes Ollama drop the generation."""
    q = queue.Queue()
    box = {"resp": None, "error": None}
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate", data=payload,
        headers={"Content-Type": "application/json"})

    def worker():
        try:
            resp = urlopen(req, timeout=300)
            box["resp"] = resp
            for raw in resp:
                q.put(raw)
        except Exception as exc:
            box["error"] = exc
        finally:
            q.put(None)  # None marks end-of-stream

    threading.Thread(target=worker, daemon=True).start()

    def abort():
        resp = box.get("resp")
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    return q, abort, box


def _open_remote_stream(payload: bytes, host: str,
                        ssh_popen: Callable = subprocess.Popen
                        ) -> tuple:
    """-> (line_queue, abort, box). abort() kills the ssh client; the
    loopback curl->Ollama connection closes and Ollama drops the
    generation."""
    q = queue.Queue()
    box = {"error": None, "stderr": ""}
    errq = queue.Queue()
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host,
        "curl -fsS --max-time 300 http://127.0.0.1:11434/api/generate "
        "-H 'Content-Type: application/json' --data-binary @-",
    ]
    try:
        proc = ssh_popen(cmd, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as exc:
        box["error"] = exc
        q.put(None)
        return q, lambda: None, box

    def drain():
        chunks = []
        try:
            for line in proc.stderr:
                chunks.append(line)
        except Exception:
            pass
        errq.put(b"".join(chunks).decode(errors="replace")[:400])

    threading.Thread(target=drain, daemon=True).start()

    try:
        proc.stdin.write(payload)
        proc.stdin.close()
    except Exception as exc:
        box["error"] = exc
        q.put(None)
        return q, lambda: None, box

    def worker():
        try:
            for raw in proc.stdout:
                q.put(raw)
            proc.wait(timeout=20)
            if proc.returncode:
                box["error"] = RuntimeError(
                    f"ssh/curl rc={proc.returncode}")
        except Exception as exc:
            box["error"] = exc
        finally:
            try:
                box["stderr"] = errq.get(timeout=5) or ""
            except Exception:
                pass
            q.put(None)  # end-of-stream

    threading.Thread(target=worker, daemon=True).start()

    def abort():
        try:
            proc.kill()
        except Exception:
            pass

    return q, abort, box


def _guarded_read(q: queue.Queue, mem_probe: Callable, *,
                  poll_s: float,
                  max_unmeasurable: int) -> dict:
    """Drain NDJSON events while polling memory at least every poll_s.
    -> {response, usage, min_free_pct, abort_reason}."""
    chunks, usage = [], {}
    min_pct, aborted, unmeas = None, None, 0
    tick = object()
    last = time.monotonic()
    while True:
        wait = max(0.01, poll_s - (time.monotonic() - last))
        try:
            raw = q.get(timeout=wait)
        except queue.Empty:
            raw = tick
        if time.monotonic() - last >= poll_s or raw is tick:
            last = time.monotonic()
            try:
                snap = mem_probe() or {}
            except Exception:
                snap = {}
            reasons = (kk_mac_memory.evaluate(snap, phase="during")
                       if snap.get("ok") else [])
            if snap.get("ok") and snap.get("free_pct") is not None:
                unmeas = 0
                pct = float(snap["free_pct"])
                min_pct = pct if min_pct is None else min(min_pct, pct)
                if reasons:
                    aborted = aborted or reasons[0]
            else:
                unmeas += 1
                if unmeas >= max_unmeasurable:
                    aborted = aborted or "memory_unmeasurable"
        if aborted:
            break
        if raw is None or raw is tick:
            if raw is None:
                break
            continue
        try:
            ev = json.loads(raw.decode("utf-8", "replace").strip())
        except (json.JSONDecodeError, AttributeError):
            continue
        if ev.get("response"):
            chunks.append(ev["response"])
        for k in _USAGE_KEYS:
            if k in ev:
                usage[k] = ev[k]
    return {"response": "".join(chunks), "usage": usage,
            "min_free_pct": min_pct, "abort_reason": aborted}


def generate_guarded(prompt: str, *, host: str = "kk-mac",
                     model: str = "qwen2.5:32b",
                     format: str | None = None,
                     think: bool | None = None,
                     local_url: str = OLLAMA_LOCAL_URL,
                     mem_probe: Callable | None = None,
                     open_stream: Callable | None = None,
                     resident: Callable | None = None,
                     unload: Callable | None = None,
                     urlopen: Callable = urllib.request.urlopen,
                     ssh_popen: Callable = subprocess.Popen,
                     poll_s: float | None = None,
                     max_unmeasurable: int = GUARD_MAX_UNMEASURABLE
                     ) -> dict:
    """Streamed /api/generate under the live memory guard.

    Pre-load: one sample must clear the 60% floor (fail closed when it
    cannot be measured). During: memory is polled at least every poll_s
    — including the silent load window — and a breach below the 50%
    abort floor or a critical kernel pressure level closes the stream.
    Post: a model this task provably loaded (absent from /api/ps
    beforehand) is unloaded with keep_alive=0; owner-resident or
    unknown-residency models are never touched.

    -> {response, usage, min_free_pct, abort_reason, resident_before,
        loaded_by_task, unloaded}
    """
    mem_probe = mem_probe or (lambda: kk_mac_memory.sample(host))
    resident = resident or (
        lambda: kk_mac_memory.resident_models(host))
    unload = unload or (lambda m: kk_mac_memory.unload_model(host, m))
    out = {"response": "", "usage": {}, "min_free_pct": None,
           "abort_reason": None, "resident_before": None,
           "loaded_by_task": False, "unloaded": False}

    # pre-load floor — fail closed before any model work starts
    try:
        pre = mem_probe() or {}
    except Exception:
        pre = {}
    pre_reasons = (kk_mac_memory.evaluate(pre, phase="pre")
                   if pre.get("ok") else ["memory_sample_failed"])
    if pre_reasons:
        out["abort_reason"] = ";".join(pre_reasons)
        return out

    before = resident()
    out["resident_before"] = sorted(before) if before is not None else None
    model_norm = kk_mac_memory._norm_model(model)
    out["loaded_by_task"] = (
        before is not None and model_norm not in before)

    payload = _generate_payload(model, prompt, format, think,
                                stream=True)
    poll = (GUARD_POLL_LOCAL_S if is_local_host(host)
            else GUARD_POLL_REMOTE_S) if poll_s is None else float(poll_s)
    if open_stream is None:
        open_stream = (_open_local_stream if is_local_host(host)
                       else _open_remote_stream)
    try:
        if is_local_host(host):
            q, abort_fn, box = open_stream(payload, local_url, urlopen)
        else:
            q, abort_fn, box = open_stream(payload, host, ssh_popen)
    except Exception as exc:
        out["abort_reason"] = f"stream_open:{type(exc).__name__}"
        return out
    try:
        read = _guarded_read(
            q, mem_probe, poll_s=poll,
            max_unmeasurable=max_unmeasurable)
    finally:
        abort_fn()
    out.update({k: read[k] for k in
                ("response", "usage", "min_free_pct", "abort_reason")})
    err = (box or {}).get("error")
    if out["abort_reason"] is None and err is not None:
        out["abort_reason"] = f"ollama_stream:{type(err).__name__}"
    if out["abort_reason"] is None and not out["response"].strip():
        out["abort_reason"] = "empty_response"
    # unload only what this task provably loaded — never an
    # owner-resident model, never on an unknown residency probe
    if out["loaded_by_task"]:
        try:
            out["unloaded"] = bool(unload(model))
        except Exception:
            out["unloaded"] = False
    return out


def run_task(task_class: str, prompt: str, **kwargs) -> dict:
    validate_task(task_class, prompt)
    gate = snapshot()
    if not gate["eligible"]:
        return {"ok": False, "admission": gate}
    if kwargs.pop("memory_guard", True):
        return _run_task_guarded(task_class, prompt, gate, **kwargs)
    response = call_remote(prompt, **kwargs)
    return {
        "ok": True,
        "admission": gate,
        "model": kwargs.get("model", "qwen2.5:32b"),
        "task_class": task_class,
        "response": response.get("response", ""),
        "usage": {
            "prompt_eval_count": response.get("prompt_eval_count"),
            "eval_count": response.get("eval_count"),
            "eval_duration": response.get("eval_duration"),
            "load_duration": response.get("load_duration"),
        },
    }


def _run_task_guarded(task_class: str, prompt: str, gate: dict,
                      **kwargs) -> dict:
    """run_task under the live memory guard — the default path. The
    streamed generate polls memory through load AND generation, aborts
    below the floors, and unloads only a model this task loaded. The
    raw call_remote() stays available via memory_guard=False for
    callers that need the unguarded shape (bench harness)."""
    host = str(kwargs.get("host", "kk-mac"))
    model = str(kwargs.get("model", "qwen2.5:32b"))
    gen = generate_guarded(
        prompt, host=host, model=model,
        format=kwargs.get("format"), think=kwargs.get("think"),
        local_url=kwargs.get("local_url", OLLAMA_LOCAL_URL),
        mem_probe=kwargs.get("mem_probe"),
        open_stream=kwargs.get("open_stream"),
        resident=kwargs.get("resident"),
        unload=kwargs.get("unload"),
        urlopen=kwargs.get("urlopen", urllib.request.urlopen),
        ssh_popen=kwargs.get("ssh_popen", subprocess.Popen),
        poll_s=kwargs.get("poll_s"),
        max_unmeasurable=kwargs.get(
            "max_unmeasurable", GUARD_MAX_UNMEASURABLE))
    usage = dict(gen.get("usage") or {})
    mem = {"resident_before": gen.get("resident_before"),
           "loaded_by_task": gen.get("loaded_by_task"),
           "min_free_pct": gen.get("min_free_pct"),
           "abort_reason": gen.get("abort_reason"),
           "unloaded": gen.get("unloaded")}
    out = {"admission": gate, "model": model, "task_class": task_class,
           "memory_guard": mem,
           "response": gen.get("response") or "", "usage": usage}
    if gen.get("abort_reason"):
        return dict(out, ok=False,
                    abort_reason=gen["abort_reason"])
    return dict(out, ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_class", choices=sorted(ALLOWED_TASKS))
    parser.add_argument("prompt")
    args = parser.parse_args()
    try:
        result = run_task(args.task_class, args.prompt)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
