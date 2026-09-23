#!/usr/bin/env python3
"""Open Notebook KB benchmark — same 8 questions as the NotebookLM/MDDB
bench (docs/kb/experiments/notebooklm-kb-search-benchmark-2026-09-15.md)
so results are comparable across tiers.

Scoring: pass if every expected keyword appears in the answer text
(case-insensitive). Also records latency and whether citations came back.

Env:
  OPEN_NOTEBOOK_URL      default http://127.0.0.1:5055
  OPEN_NOTEBOOK_PASSWORD bearer token (required unless auth disabled)
  OPEN_NOTEBOOK_MODEL    default fetched from /api/models/defaults chat model
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("OPEN_NOTEBOOK_URL", "http://127.0.0.1:5055")
PW = os.environ.get("OPEN_NOTEBOOK_PASSWORD", "")

CASES = [
    ("What is the Tailscale IP of tony-dell?", ["100.68.142.13"]),
    ("How do I restart the NotebookLM REST auth refresh?",
     ["auth-refresh"]),
    ("Where does Caddy serve the public apps from on tony-dell?",
     ["caddy", "apps"]),
    ("What is the nlm-add workflow for adding SSOT sources to NotebookLM?",
     ["drive"]),
    ("How do I fix devin-desktop after a crash on tony-dell?",
     ["restart"]),
    ("Which Home Assistant token file should I use for michael-ha?",
     ["ha-michael-live.env"]),
    ("How do I deploy a new card bundle to michael-dev?",
     ["deploy-card.sh"]),
    ("How do I add a new app to the public apps page on tony-dell?",
     ["apps"]),
]


def call(path, payload=None, timeout=300):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {PW}"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def main():
    model = os.environ.get("OPEN_NOTEBOOK_MODEL")
    if not model:
        model = call("/api/models/defaults")["default_chat_model"]
    print(f"model: {model}  base: {BASE}")

    results = []
    passed = 0
    for q, expects in CASES:
        t0 = time.time()
        try:
            r = call("/api/search/ask/simple", {
                "question": q,
                "strategy_model": model,
                "answer_model": model,
                "final_answer_model": model,
            })
            answer = r.get("answer", "")
            dt = time.time() - t0
            low = answer.lower()
            ok = all(e.lower() in low for e in expects)
            passed += ok
            print(f"[{'PASS' if ok else 'MISS'}] {q}  ({dt:.0f}s)")
            if not ok:
                print(f"      expected {expects}; got: {answer[:160]}")
            results.append({"q": q, "ok": ok, "seconds": round(dt, 1),
                            "answer": answer})
        except Exception as exc:
            dt = time.time() - t0
            print(f"[ERR ] {q}  ({dt:.0f}s) {exc}")
            results.append({"q": q, "ok": False, "seconds": round(dt, 1),
                            "error": str(exc)})

    total = len(CASES)
    print(f"\n{passed}/{total} pass ({passed / total:.0%})")
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        with open(out, "w") as f:
            json.dump({"mddb": BASE, "model": model, "total": total,
                       "pass": passed, "results": results}, f, indent=1)
        print("wrote", out)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
