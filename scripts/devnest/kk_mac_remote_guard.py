#!/usr/bin/env python3
"""Remote-side memory guard + single-shot Ollama call for kk_mac_llm.

This file is NOT executed on the fleet runner — scripts/devnest/
kk_mac_llm.call_remote pipes it to `ssh <kk-mac> python3 -` with the
request payload base64-encoded in argv[1]. It runs ON KK-Mac, next to
the loopback Ollama API, because that is where memory pressure lives.

Approved envelope (card kk-mac-live-memory-guard / MEM-1043, Board
answer allow-once-60-50):

  pre-flight   >= entry_floor_pct free memory before model load
               (default 60%) — below that the task never starts
  during       abort the generate stream when free memory drops below
               abort_floor_pct (default 50%) or cannot be measured
  post         record post-run free memory; when THIS task loaded the
               model (it was absent from /api/ps beforehand) unload it
               with keep_alive=0 — never touch a model the owner had
               already resident

Output contract: exactly one JSON object on stdout —
  {ok, verdict, reason, response, eval_count, eval_duration,
   load_duration, total_duration, memory{...}, guard}
verdict ∈ ok | preflight_abort | memory_abort | memory_unmeasurable |
          ollama_error | bad_request
Exit codes: 0 ok, 2 guard/policy decline, 1 transport/unexpected error.
A decline still prints its JSON verdict — callers must parse stdout
before trusting the exit code.
"""
from __future__ import annotations

import base64
import json
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request

GUARD_ID = "kk_mac_remote_guard/1"
OLLAMA = "http://127.0.0.1:11434"
ENTRY_FLOOR_PCT = 60.0
ABORT_FLOOR_PCT = 50.0
POLL_S = 1.0
HTTP_TIMEOUT_S = 110

_PCT_RE = re.compile(r"memory free percentage:\s*(\d+(?:\.\d+)?)\s*%")
_VM_PAGES_RE = re.compile(r"^Pages\s+(\w+):\s+([\d,]+)\.", re.M)


def _sh(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout)


def _int_list_total(text):
    return sum(int(v.replace(",", ""))
               for _k, v in _VM_PAGES_RE.findall(text or ""))


def free_pct(runner=None):
    """System-wide memory free percentage (0-100), or None when no
    probe can measure it — callers fail closed on None.

    Primary: `memory_pressure` "System-wide memory free percentage" —
    the same metric the 2026-11-06 smoke recorded (72% -> 34% -> 55%).
    Fallback: vm_stat page counts over hw.memsize (approximation —
    free+inactive+speculative+purgeable)."""
    runner = runner or _sh
    try:
        out = runner(["memory_pressure"], timeout=10).stdout or ""
        m = _PCT_RE.search(out)
        if m:
            return float(m.group(1)), "memory_pressure"
    except Exception:
        pass
    try:
        stat = runner(["vm_stat"], timeout=10).stdout or ""
        pages = {k.lower(): int(v.replace(",", ""))
                 for k, v in _VM_PAGES_RE.findall(stat)}
        if not pages:
            return None, "unmeasurable"
        try:
            psize = int(runner(["getconf", "PAGESIZE"],
                               timeout=5).stdout.strip())
        except Exception:
            psize = 16384  # Apple Silicon default; vm_stat fallback only
        try:
            memsize = int(runner(["sysctl", "-n", "hw.memsize"],
                                 timeout=5).stdout.strip())
        except Exception:
            return None, "unmeasurable"
        avail = sum(pages.get(k, 0) for k in
                    ("free", "inactive", "speculative", "purgeable"))
        return round(100.0 * avail * psize / memsize, 1), "vm_stat"
    except Exception:
        return None, "unmeasurable"


def ollama_json(path, payload=None, timeout=15):
    """GET (payload None) or POST JSON against loopback Ollama."""
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA + path, data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def resident_models():
    try:
        ps = ollama_json("/api/ps", timeout=10)
        names = set()
        for m in ps.get("models") or []:
            names.add(str(m.get("name") or m.get("model") or ""))
        return names
    except Exception:
        return set()


def unload_model(model):
    """keep_alive=0 drops the model from memory — same call the smoke
    used manually. Only ever invoked for a model this task loaded."""
    try:
        ollama_json("/api/generate",
                    {"model": model, "keep_alive": 0,
                     "prompt": "", "stream": False}, timeout=15)
        return True
    except Exception:
        return False


def generate_guarded(payload, abort_floor_pct, poll_s=POLL_S,
                     free_probe=None):
    """POST /api/generate with stream=True in a worker thread while the
    caller polls free memory every poll_s — this covers model LOAD too,
    where Ollama emits nothing until weights are resident. On breach the
    response is closed, which unblocks the worker's read. Returns
    (result_dict, abort_reason_or_None, min_pct_seen)."""
    free_probe = free_probe or (lambda: free_pct()[0])
    body = dict(payload)
    body["stream"] = True
    req = urllib.request.Request(
        OLLAMA + "/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")

    lines = queue.Queue()
    state = {"resp": None, "error": None}
    DONE = object()

    def worker():
        try:
            resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S)
            state["resp"] = resp
            for raw in resp:
                lines.put(raw)
            lines.put(DONE)
        except Exception as exc:  # surfaced to the poller below
            state["error"] = exc
            lines.put(DONE)

    threading.Thread(target=worker, daemon=True).start()

    chunks, usage = [], {}
    min_pct, aborted = None, None
    last_poll = time.monotonic()
    while True:
        # wake at least every poll_s even when tokens stream continuously
        wait = max(0.01, poll_s - (time.monotonic() - last_poll))
        try:
            raw = lines.get(timeout=wait)
        except queue.Empty:
            raw = "__timeout__"
        if time.monotonic() - last_poll >= poll_s or raw == "__timeout__":
            last_poll = time.monotonic()
            pct = free_probe()
            if pct is None:
                aborted = aborted or "memory_unmeasurable"
            else:
                min_pct = pct if min_pct is None else min(min_pct, pct)
                if pct < abort_floor_pct:
                    aborted = aborted or "memory_floor"
        if aborted:
            resp = state.get("resp")
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
            break
        if raw is DONE:
            break
        try:
            ev = json.loads(raw.decode("utf-8", "replace").strip())
        except (json.JSONDecodeError, AttributeError):
            continue
        if ev.get("response"):
            chunks.append(ev["response"])
        for k in ("eval_count", "eval_duration", "load_duration",
                  "total_duration", "done", "done_reason"):
            if k in ev:
                usage[k] = ev[k]
    if aborted is None and state.get("error"):
        raise state["error"]

    result = {
        "response": "".join(chunks),
        "eval_count": usage.get("eval_count"),
        "eval_duration": usage.get("eval_duration"),
        "load_duration": usage.get("load_duration"),
        "total_duration": usage.get("total_duration"),
        "done": usage.get("done"),
        "done_reason": usage.get("done_reason"),
    }
    return result, aborted, min_pct


def run(payload):
    entry_floor = float(payload.get("entry_floor_pct", ENTRY_FLOOR_PCT))
    abort_floor = float(payload.get("abort_floor_pct", ABORT_FLOOR_PCT))
    unload_after = bool(payload.get("unload_after", True))
    model = str(payload.get("model") or "qwen3:8b")

    out = {"ok": False, "verdict": "error", "reason": "",
           "response": "", "eval_count": None, "eval_duration": None,
           "load_duration": None, "total_duration": None,
           "memory": {"entry_floor_pct": entry_floor,
                      "abort_floor_pct": abort_floor,
                      "source": None},
           "guard": GUARD_ID}

    pre = free_pct()
    out["memory"]["pre_pct"] = pre[0]
    out["memory"]["source"] = pre[1]
    if pre[0] is None:
        out["verdict"] = "memory_unmeasurable"
        out["reason"] = "free memory could not be measured; failing closed"
        return out, 2
    if pre[0] < entry_floor:
        out["verdict"] = "preflight_abort"
        out["reason"] = (f"free memory {pre[0]}% below entry floor "
                         f"{entry_floor}%")
        return out, 2

    resident_before = resident_models()
    out["memory"]["resident_before"] = sorted(resident_before)
    loaded_by_us = model not in resident_before

    gen_payload = {k: v for k, v in payload.items()
                   if k not in ("entry_floor_pct", "abort_floor_pct",
                                "unload_after", "request_timeout_s",
                                "poll_s")}
    try:
        gen, aborted, min_pct = generate_guarded(
            gen_payload, abort_floor,
            poll_s=float(payload.get("poll_s", POLL_S)))
    except Exception as exc:
        out["verdict"] = "ollama_error"
        out["reason"] = f"{type(exc).__name__}: {exc}"[:300]
        out["memory"]["post_pct"] = free_pct()[0]
        return out, 1

    out.update({k: gen.get(k) for k in
                ("response", "eval_count", "eval_duration",
                 "load_duration", "total_duration")})
    out["memory"]["min_during_pct"] = min_pct
    out["memory"]["post_pct"] = free_pct()[0]
    out["memory"]["loaded_by_task"] = loaded_by_us

    if aborted:
        out["verdict"] = ("memory_unmeasurable" if aborted ==
                          "memory_unmeasurable" else "memory_abort")
        out["reason"] = ("free memory unmeasurable mid-run"
                         if aborted == "memory_unmeasurable"
                         else f"free memory fell below abort floor "
                              f"{abort_floor}%")
        out["ok"] = False
    elif not (out["response"] or "").strip():
        out["verdict"] = "ollama_error"
        out["reason"] = "empty model response"
        out["ok"] = False
    else:
        out["verdict"] = "ok"
        out["ok"] = True

    if unload_after and loaded_by_us:
        out["memory"]["unloaded"] = unload_model(model)
    else:
        out["memory"]["unloaded"] = False
    return out, (0 if out["ok"] else 2)


def main():
    try:
        payload = json.loads(base64.b64decode(sys.argv[1]).decode())
    except Exception as exc:
        print(json.dumps({"ok": False, "verdict": "bad_request",
                          "reason": f"payload decode: {exc}",
                          "guard": GUARD_ID}))
        return 1
    result, code = run(payload)
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
