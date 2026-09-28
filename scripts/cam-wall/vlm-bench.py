#!/usr/bin/env python3
"""cam-wall VLM bench — describe each camera thumbnail with OpenRouter :free
vision models; report latency + description per model per camera.

Usage: CAMWALL_BASE=https://tony-dell.taila0626a.ts.net/apps/camwall \
       python3 vlm-bench.py [zone ...] [--models m1,m2]
Env: OPENROUTER_API_KEY (or sourced from ~/.config/secrets/openrouter.env)
Output: JSON to stdout + /tmp/vlm-bench.json
"""
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("CAMWALL_BASE",
                      "https://tony-dell.taila0626a.ts.net/apps/camwall")
MODELS = [
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-31b-it:free",
    "dots-studio/dots-3-note-preview:free",
    "thinkingmachines/inkling:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]
PROMPT = ("This is a CCTV frame from a residential estate camera. In 1-2 "
          "sentences: describe what is visible — scene type, any people, "
          "vehicles, or activity, and whether anything looks unusual. "
          "If the image is dark/blank/unusable, say so.")


def _key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k
    try:
        for ln in open(os.path.expanduser("~/.config/secrets/openrouter.env")):
            if ln.startswith("OPENROUTER_API_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raise SystemExit("no OPENROUTER_API_KEY")


def get(url: str, timeout: float = 30) -> bytes:
    return urllib.request.urlopen(url, timeout=timeout).read()


def describe(model: str, b64: str, mime: str, key: str) -> dict:
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "max_tokens": 120,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    t0 = time.time()
    for _attempt in range(3):  # free tier shares a rate limit — back off on 429
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=90).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and _attempt < 2:
                time.sleep(20 * (_attempt + 1))
                continue
            return {"model": model, "ok": False,
                    "latency_s": round(time.time() - t0, 1),
                    "error": f"HTTP {e.code}: {e.read()[:160].decode('utf-8','replace')}"}
        except Exception as e:
            return {"model": model, "ok": False,
                    "latency_s": round(time.time() - t0, 1),
                    "error": str(e)[:200]}
        lat = time.time() - t0
        ch = r.get("choices") or [{}]
        txt = (ch[0].get("message") or {}).get("content") or ""
        if not txt.strip():
            return {"model": model, "ok": False,
                    "latency_s": round(lat, 1), "error": "empty response"}
        return {"model": model, "ok": True, "latency_s": round(lat, 1),
                "text": txt.strip()[:600]}


def main() -> None:
    argv = sys.argv[1:]
    if "--models" in argv:
        i = argv.index("--models")
        MODELS[:] = argv.pop(i + 1).split(",")
        argv.pop(i)
    zones = argv or ["vms-noble-club", "vms-noble-a"]
    key = _key()
    out = {"ts": int(time.time()), "zones": {}}
    for zone in zones:
        man = json.loads(get(f"{BASE}/data/{zone}/manifest-{zone}.json"))
        zcams = []
        for cam in man["cams"]:
            # try the thumb even when the last pull failed — a stale file
            # still shows the camera's typical view
            try:
                raw = get(f"{BASE}/data/{zone}/{cam['key']}.jpg?t={cam.get('ts') or 'x'}", 30)
            except Exception as e:
                zcams.append({"cam": cam["label"], "skipped": str(e)[:80]})
                continue
            if len(raw) < 1000:
                zcams.append({"cam": cam["label"], "skipped": "empty thumb"})
                continue
            mime = "image/png" if raw[:2] == b"\x89P" else "image/jpeg"
            b64 = base64.b64encode(raw).decode()
            entry = {"cam": cam["label"], "bytes": len(raw), "models": []}
            for m in MODELS:
                r = describe(m, b64, mime, key)
                tag = "ok" if r.get("ok") else "ERR"
                print(f"{zone}/{cam['key']} {m} {tag} {r['latency_s']}s",
                      flush=True)
                entry["models"].append(r)
            zcams.append(entry)
        out["zones"][zone] = zcams
    with open("/tmp/vlm-bench.json", "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("wrote /tmp/vlm-bench.json")


if __name__ == "__main__":
    main()
