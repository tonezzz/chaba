#!/usr/bin/env python3
"""Arm-3 router (P2+P3): retrieve -> codemod | hint | agent.

task prompt -> mddb vector-search over `code-patterns` -> top-k triggers:
  * hit >= thr AND a codemod is registered for the key -> deterministic fix
  * hit >= thr, no codemod -> hint arm: pattern injected into agent prompt
  * no confident hit -> plain agent lane (arm0 equivalent)

Leak-strict mode (--task-id + --guard): hits whose meta.commit is banned
for the task being run are dropped BEFORE the decision — the store may
hold a task's own fix (e.g. the seeded t1 bootstrap pattern) and the
router must not serve it back to that task's bench arm.

Usage:
  python3 router.py <prompt_file> --workspace <repo> \
      --model litellm/gemini-3.5-flash-lite \
      [--registry codemods.json] [--guard leak-guard.json --task-id t1] \
      [--verify score.py task_dir] [--retrieve-only]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MDDB = "http://100.102.134.91:11023/v1"
COLLECTION = "code-patterns"
HINT_BLOCK = """

=== PATTERN LIBRARY MATCH (from code-patterns) ===
Class: {cls}
Trigger: {trigger}
Known fix in this repo: {transform}
Apply this pattern if it matches the reported bug; ignore it if the
symptoms clearly describe a different defect.
"""


def search_patterns(prompt: str, top_k: int = 3, mddb: str = MDDB):
    body = json.dumps({"collection": COLLECTION, "query": prompt,
                       "top_k": top_k, "retrieval_mode": "parent",
                       "include_content": True}).encode()
    req = urllib.request.Request(f"{mddb}/vector-search", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def hit_info(hit):
    doc = (hit or {}).get("document") or {}
    meta = doc.get("meta") or {}
    def first(v):
        return v[0] if isinstance(v, list) and v else v
    return {
        "key": (doc.get("key") or "").replace(f"{COLLECTION}|", ""),
        "score": float(hit.get("score") or 0.0),
        "repo": first(meta.get("repo")) or "",
        "commit": first(meta.get("commit")) or "",
        "cls": first(meta.get("class")) or "",
        "trigger": first(meta.get("trigger")) or "",
        "content": doc.get("contentMd") or doc.get("content_md") or "",
    }


def get_document(key: str, mddb: str = MDDB) -> str:
    """Hydrate a doc body — vector-search returns contentMd empty."""
    body = json.dumps({"collection": COLLECTION, "key": key,
                       "lang": "en"}).encode()
    req = urllib.request.Request(f"{mddb}/get", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        doc = d.get("document") or d
        return doc.get("contentMd") or doc.get("content_md") or ""
    except Exception:
        return ""


def transform_of(content: str) -> str:
    m = re.search(r"## Transform\s*\n(.*?)(\n## |\Z)", content, re.S)
    return m.group(1).strip() if m else ""


def load_guard(path: Path, task_id: str) -> set:
    if not path or not path.exists():
        return set()
    g = json.loads(path.read_text())
    return set(g.get("tasks", {}).get(task_id, {}).get("banned", []))


def run_verify(score_py: str, task_dir: str, workspace: str,
               py: str = None) -> dict:
    t0 = time.time()
    v = subprocess.run([py or sys.executable, score_py, workspace, task_dir],
                       capture_output=True, text=True, timeout=300)
    out = v.stdout + v.stderr
    m = re.search(r"AGENT_COST_BENCH_RESULT: (\{.*\})", out)
    res = json.loads(m.group(1)) if m else {"score": None,
                                            "summary": out[-300:]}
    res["verify_s"] = round(time.time() - t0, 1)
    return res


def run_agent(prompt: str, workspace: str, model: str, timeout: int) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(Path.home() / ".local/bin") + ":" + env.get("PATH", "")
    if "LITELLM_KEY" not in env:
        f = Path.home() / ".config/secrets/litellm-chaba.env"
        if f.exists():
            for line in f.read_text().splitlines():
                if line.startswith("LITELLM_KEY="):
                    env["LITELLM_KEY"] = line.split("=", 1)[1].strip()
    t0 = time.time()
    r = subprocess.run(
        ["opencode", "run", "--format", "json", "--dir", workspace,
         "--model", model, "--auto", prompt],
        cwd=workspace, env=env, capture_output=True, text=True,
        timeout=timeout)
    cost = None
    for line in reversed(r.stdout.splitlines()):
        try:
            j = json.loads(line)
        except Exception:
            continue
        c = (j.get("cost") or (j.get("usage") or {}).get("cost"))
        if c is not None:
            cost = c
            break
    return {"rc": r.returncode, "agent_s": round(time.time() - t0, 1),
            "cost_usd": cost, "tail": r.stdout[-300:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_file")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--model", default="litellm/gemini-3.5-flash-lite")
    ap.add_argument("--thr", type=float, default=0.35)
    ap.add_argument("--registry", type=Path)
    ap.add_argument("--guard", type=Path)
    ap.add_argument("--task-id")
    ap.add_argument("--verify", nargs=2, metavar=("SCORE_PY", "TASK_DIR"))
    ap.add_argument("--verify-python", help="interpreter for score.py "
                    "(e.g. workspace .venv-verify/bin/python)")
    ap.add_argument("--retrieve-only", action="store_true")
    ap.add_argument("--agent-timeout", type=int, default=1500)
    ap.add_argument("--mddb", default=MDDB)
    args = ap.parse_args()

    prompt = Path(args.prompt_file).read_text()
    registry = {}
    if args.registry and args.registry.exists():
        registry = json.loads(args.registry.read_text())

    res = search_patterns(prompt, mddb=args.mddb)
    if res.get("error"):
        print(json.dumps({"router": "error", "detail": res["error"]}))
        return 2

    hits = [hit_info(h) for h in (res.get("results") or [])]
    banned = load_guard(args.guard, args.task_id) if args.task_id else set()

    def leaked(h):
        c = h["commit"]
        return any(b.startswith(c) or c.startswith(b) for b in banned)

    kept = [h for h in hits if not leaked(h)]
    dropped = [h["key"] for h in hits if leaked(h)]

    top = kept[0] if kept else None
    decision = {"router": "retrieved", "task": args.task_id,
                "hits": [{"key": h["key"], "score": round(h["score"], 3)}
                         for h in kept],
                "leak_dropped": dropped,
                "top": top["key"] if top else None,
                "top_score": round(top["score"], 3) if top else None}
    print(json.dumps(decision))
    if args.retrieve_only:
        return 0

    ws = args.workspace
    codemod = registry.get(top["key"]) if top and top["score"] >= args.thr else None
    if codemod:
        script = Path(os.path.expanduser(codemod))
        t0 = time.time()
        r = subprocess.run([sys.executable, str(script), ws],
                           capture_output=True, text=True, timeout=120)
        applied = "PATCHED" in r.stdout
        out = {"router": "codemod", "key": top["key"],
               "score": round(top["score"], 3), "rc": r.returncode,
               "applied": applied,
               "codemod_s": round(time.time() - t0, 1),
               "detail": (r.stdout or r.stderr).strip()[:200]}
        if applied and args.verify:
            out["verify"] = run_verify(*args.verify, ws,
                                       py=args.verify_python)
        if applied:
            print(json.dumps(out))
            return 0
        # codemod did not apply — wrong-defect hit; fall through to
        # hint/agent with the same retrieved pattern
        print(json.dumps({**out, "router": "codemod-skip-fallthrough"}))

    if top and top["score"] >= args.thr:
        content = top["content"] or get_document(top["key"], args.mddb)
        prompt += HINT_BLOCK.format(
            cls=top["cls"], trigger=top["trigger"],
            transform=transform_of(content) or top["trigger"])
        path = "hint"
    else:
        path = "agent"
    out = {"router": path,
           "hint_key": top["key"] if path == "hint" else None,
           "score": round(top["score"], 3) if top else None}
    out.update(run_agent(prompt, ws, args.model, args.agent_timeout))
    if args.verify:
        out["verify"] = run_verify(*args.verify, ws, py=args.verify_python)
    print(json.dumps(out))
    return out["rc"]


if __name__ == "__main__":
    sys.exit(main())
