#!/usr/bin/env python3
"""lane-arena — matched held-out benchmark for the JevTeam lanes
(card jevteam-omen-or-lane-admission, 2026-11-24).

Runs the SAME labeled corpus through every lane arm and scores accuracy
per question family + latency. Two wire shapes:

  systemone arms — native POST /v1/systemone (omen :8777/:8778/:8779/:8780,
                   jevos idc02:8777). Reuses decision-arena's ask/parse.
  chat arms      — OpenAI-compatible /v1/chat/completions. Each
                   systemone case is rendered as a prompt that demands a
                   strict JSON answer; the reply is parsed back to the
                   same label space, so scores are comparable across
                   wire shapes. Arms: kk-mac ollama, litellm gateway
                   models (the OpenCode free-lane brain, OR :free, OR
                   paid deepseek).

Corpus: the decision-arena v2 corpus (50 labeled cases — confirm noul,
tool choice, pipeline-edge noul, stagnation noul) imported from
scripts/ops/decision-arena.py so the label set stays single-sourced.

Devin arm: NOT callable — Devin sessions are agent runs, not
completions; 50 agent sessions per corpus pass is prohibitive. The devin
lane's decision role today is the safe-default fallback, recorded as a
baseline note, not an arm.

Secrets: litellm keys resolve from env or ~/.config/secrets/
litellm-keys.env; values are never printed or written to artifacts.

Usage:
  lane-arena.py --arms omen-8777,omen-8778,kkmac,or-free   # subset
  lane-arena.py --limit 10 --out evals/results/jev/lane-arena-x.json
  lane-arena.py --selftest                                # corpus only
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_decision_arena():
    spec = importlib.util.spec_from_file_location(
        "decision_arena", REPO / "scripts" / "ops" / "decision-arena.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["decision_arena"] = mod
    spec.loader.exec_module(mod)
    return mod


da = _load_decision_arena()

LITELLM_BASE = os.environ.get("LITELLM_URL",
                              "http://100.102.134.91:4000").rstrip("/")
SECRETS_FILE = Path.home() / ".config" / "secrets" / "litellm-keys.env"


def _env_keys() -> dict:
    keys = {}
    try:
        for line in SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                keys[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return keys


def _litellm_key(alias_pref=("LITELLM_KEY_BENCH", "LITELLM_KEY_CHABA")):
    fk = _env_keys()
    for name in alias_pref:
        k = os.environ.get(name) or fk.get(name)
        if k:
            return k
    return ""


# ------------------------------------------------------------------ arms
# kind=systemone -> POST {base}/v1/systemone (decision-arena wire shape)
# kind=chat       -> POST {base}/v1/chat/completions, JSON-answer prompt

ARMS = {
    # --- decision plane: native /v1/systemone -------------------------
    "omen-8777": {"kind": "systemone", "base": "http://100.75.102.88:8777",
                  "label": "Omen open-jev heavy (gemma-3-4b CPU)",
                  "lane": "omen", "timeout": 180},
    "omen-8778": {"kind": "systemone", "base": "http://100.75.102.88:8778",
                  "label": "Omen open-jev student (gemma-3-1b CPU)",
                  "lane": "omen", "timeout": 120},
    "omen-8779": {"kind": "systemone", "base": "http://100.75.102.88:8779",
                  "label": "Omen student replica (quadlet)",
                  "lane": "omen", "timeout": 120},
    "omen-8780": {"kind": "systemone", "base": "http://100.75.102.88:8780",
                  "label": "Omen jev-student-distilmulti (confirm-gate)",
                  "lane": "omen", "timeout": 60},
    "jevos-idc02": {"kind": "systemone",
                    "base": os.environ.get("JEVOS_URL",
                                           "http://idc02.taila0626a.ts.net:8777"),
                    "label": "jevos heavy (idc02:8777 gemma-3-4b)",
                    "lane": "jev-routing", "timeout": 180},
    # --- work plane chat arms (matched labels via JSON prompt) ---------
    "kkmac-qwen38b": {"kind": "chat",
                      "base": "http://100.108.217.17:11434/v1",
                      "model": "qwen3:8b", "key_env": "",
                      "label": "KK-Mac ollama qwen3:8b",
                      "lane": "kk_mac_local", "timeout": 180,
                      "max_tokens": 2048},
    "oc-free-flashlite": {"kind": "chat", "base": LITELLM_BASE + "/v1",
                          "model": "gemini-3.5-flash-lite",
                          "key_alias": "LITELLM_KEY_CHABA",
                          "label": "OpenCode free-lane brain "
                                   "(litellm/gemini-3.5-flash-lite)",
                          "lane": "openrouter", "timeout": 120,
                          "max_tokens": 512},
    "oc-executor": {"kind": "opencode",
                    "model": "litellm/gemini-3.5-flash-lite",
                    "key_alias": "LITELLM_KEY_CHABA",
                    "label": "OpenCode executor lane (opencode run, "
                             "flash-lite)",
                    "lane": "free-opencode", "timeout": 240},
    "or-free-nemotron": {"kind": "chat", "base": LITELLM_BASE + "/v1",
                         "model": "or-free-nemotron-35",
                         "key_alias": "LITELLM_KEY_BENCH",
                         "label": "OR :free nemotron-3.5-lightning via gw",
                         "lane": "openrouter", "timeout": 180,
                         "max_tokens": 512},
    "or-paid-deepseek": {"kind": "chat", "base": LITELLM_BASE + "/v1",
                         "model": "or-deepseek-v4-flash",
                         "key_alias": "LITELLM_KEY_CHABA",
                         "label": "OR paid deepseek-v4-flash via gw",
                         "lane": "openrouter", "timeout": 180,
                         "max_tokens": 2048},
}

CHAT_SYSTEM = (
    "You are a precise decision engine. Answer the question with STRICT "
    "JSON only — no prose, no markdown fences. Shape: "
    '{"answer": "<label>", "confidence": <0..1>}. The label must be one '
    "of the allowed choices given in the question.")


def chat_prompt(case: dict) -> list[dict]:
    q = case["questions"]["q"]
    crit = q.get("criteria") or {}
    if q["type"] == "noul":
        allowed = '"true" or "false"'
        task = ("Answer true/false: " + q.get("instructions", ""))
    else:
        allowed = ", ".join(f'"{k}"' for k in crit) or '"<label>"'
        task = ("Choose exactly one label. " +
                q.get("instructions", ""))
    user = (
        f"STATE:\n{case['state']}\n\n"
        f"QUESTION TYPE: {q['type']}\nTASK: {task}\n"
        f"ALLOWED LABELS: {allowed}\n"
        + ("CRITERIA:\n" + json.dumps(crit, ensure_ascii=False) + "\n"
           if crit else "")
        + "\nRespond with JSON only: {\"answer\": \"<label>\", "
          "\"confidence\": <0..1>}"
    )
    return [{"role": "system", "content": CHAT_SYSTEM},
            {"role": "user", "content": user}]


def _post_json(url: str, payload: dict, headers: dict,
               timeout: float):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), round((time.time() - t0) * 1000), None
    except Exception as e:
        return None, round((time.time() - t0) * 1000), \
            f"{type(e).__name__}: {e}"[:140]


def run_systemone_arm(arm: dict, case: dict) -> dict:
    payload = {"model": "jev-latest", "state": case["state"],
               "questions": case["questions"]}
    body, ms, err = _post_json(arm["base"].rstrip("/") + "/v1/systemone",
                               payload, {}, arm["timeout"])
    got = da.parse((body or {}).get("answers", {}).get("q"),
                   case["qtype"]) if body else None
    return {"got": got, "ms": ms, "err": err,
            "raw": (body or {}).get("answers", {}).get("q")}


def run_chat_arm(arm: dict, case: dict, key: str) -> dict:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    payload = {"model": arm["model"], "messages": chat_prompt(case),
               "temperature": 0,
               "max_tokens": arm.get("max_tokens", 512)}
    body, ms, err = _post_json(arm["base"].rstrip("/") + "/chat/completions",
                               payload, headers, arm["timeout"])
    got = None
    content = ""
    usage = {}
    if body:
        try:
            ch = body["choices"][0]["message"]
            content = ch.get("content") or ""
            usage = body.get("usage") or {}
        except Exception:
            pass
        # strict JSON first; fall back to first "answer": "..." match
        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            got = json.loads(content[start:end]).get("answer")
        except Exception:
            import re
            m = re.search(r'"answer"\s*:\s*"([^"]+)"', content)
            got = m.group(1) if m else None
    # normalize label forms (true/True/TRUE -> true etc.)
    if isinstance(got, str):
        low = got.strip().strip('"').lower()
        if low in ("true", "yes"):
            got = "true"
        elif low in ("false", "no"):
            got = "false"
        else:
            got = low
    rec = {"got": got, "ms": ms, "err": err,
           "raw": {"content": content[:300],
                   "tokens": usage.get("total_tokens")}}
    return rec


def run_opencode_arm(arm: dict, case: dict, key: str) -> dict:
    """Literal OpenCode executor arm — `opencode run` per case, same
    prompt the chat arms get. Parses the final agent text for the JSON
    answer. Slow (agent boot per call) — kept at low worker counts."""
    import re
    import subprocess
    q = case["questions"]["q"]
    crit = q.get("criteria") or {}
    if q["type"] == "noul":
        allowed = '"true" or "false"'
        task = "Answer true/false: " + q.get("instructions", "")
    else:
        allowed = ", ".join(f'"{k}"' for k in crit) or '"<label>"'
        task = "Choose exactly one label. " + q.get("instructions", "")
    prompt = (
        CHAT_SYSTEM + "\n\nSTATE:\n" + case["state"] +
        "\n\nQUESTION TYPE: " + q["type"] + "\nTASK: " + task +
        "\nALLOWED LABELS: " + allowed + "\n" +
        ("CRITERIA:\n" + json.dumps(crit, ensure_ascii=False) + "\n"
         if crit else "") +
        "\nRespond with JSON only: {\"answer\": \"<label>\", "
        "\"confidence\": <0..1>}")
    env = dict(os.environ)
    env["LITELLM_KEY"] = key
    t0 = time.time()
    try:
        r = subprocess.run(
            ["opencode", "run", "--model", arm["model"], prompt],
            capture_output=True, text=True, timeout=arm["timeout"],
            env=env, cwd="/tmp")
        out = (r.stdout or "") + (r.stderr or "")
        ms = round((time.time() - t0) * 1000)
        if r.returncode != 0 and "answer" not in out.lower():
            return {"got": None, "ms": ms,
                    "err": f"opencode rc={r.returncode}: "
                           f"{out[-160:]}", "raw": out[-300:]}
    except subprocess.TimeoutExpired:
        return {"got": None, "ms": round((time.time() - t0) * 1000),
                "err": "timeout", "raw": ""}
    except FileNotFoundError:
        return {"got": None, "ms": 0, "err": "opencode not on PATH",
                "raw": ""}
    got = None
    m = re.search(r'\{[^{}]*"answer"\s*:\s*"([^"]+)"[^{}]*\}', out)
    if m:
        got = m.group(1).strip().lower()
    if got in ("true", "yes"):
        got = "true"
    elif got in ("false", "no"):
        got = "false"
    return {"got": got, "ms": ms, "err": None, "raw": out[-300:]}


def run_arm(arm_name: str, arm: dict, corpus: list[dict],
            workers: int) -> dict:
    key = ""
    if arm["kind"] in ("chat", "opencode") and arm.get("key_alias"):
        fk = _env_keys()
        key = os.environ.get(arm["key_alias"]) or fk.get(arm["key_alias"], "")
        if not key:
            return {"arm": arm_name, "label": arm["label"],
                    "lane": arm["lane"], "skipped":
                    f"no key for {arm['key_alias']}"}
    # ping first — a dead arm skips fast instead of 50 timeouts
    ping_case = {"id": "ping", "state": "ping",
                 "questions": {"q": {"type": "noul",
                                     "instructions": "ping",
                                     "criteria": {"true": "t",
                                                  "false": "f"}}},
                 "qtype": "noul", "expected": "true"}
    if arm["kind"] == "systemone":
        p = run_systemone_arm(arm, ping_case)
    elif arm["kind"] == "opencode":
        p = run_opencode_arm(arm, ping_case, key)
    else:
        p = run_chat_arm(arm, ping_case, key)
    if p["err"] or p["got"] is None:
        return {"arm": arm_name, "label": arm["label"],
                "lane": arm["lane"], "skipped":
                f"ping failed: {p['err']}"}

    records = []
    lat = []
    correct = total = 0
    per_type: dict[str, list[int]] = {}

    def one(case):
        if arm["kind"] == "systemone":
            r = run_systemone_arm(arm, case)
        elif arm["kind"] == "opencode":
            r = run_opencode_arm(arm, case, key)
        else:
            r = run_chat_arm(arm, case, key)
        return case, r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, c): c for c in corpus}
        for fut in as_completed(futs):
            case, r = fut.result()
            ok = r["got"] == case["expected"]
            lat.append(r["ms"])
            correct += 1 if ok else 0
            total += 1
            per_type.setdefault(case["id"].split("-")[0], [0, 0])
            per_type[case["id"].split("-")[0]][1] += 1
            per_type[case["id"].split("-")[0]][0] += 1 if ok else 0
            records.append({"arm": arm_name, "id": case["id"],
                            "qtype": case["qtype"],
                            "expected": case["expected"],
                            "got": r["got"], "ok": ok, "ms": r["ms"],
                            "err": r["err"], "raw": r.get("raw")})
    return {"arm": arm_name, "label": arm["label"], "lane": arm["lane"],
            "accuracy": round(correct / total, 3) if total else 0,
            "correct": correct, "total": total,
            "per_type": {k: round(v[0] / v[1], 3) if v[1] else 0
                         for k, v in per_type.items()},
            "lat_p50_ms": round(statistics.median(lat), 1) if lat else 0,
            "lat_mean_ms": round(statistics.mean(lat), 1) if lat else 0,
            "errors": sum(1 for r in records if r["err"]),
            "records": records}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arms", default="",
                    help="comma list; default = all ARMS")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    corpus = da.build_corpus()
    rep = da.corpus_report(corpus)
    if rep["errors"]:
        print("corpus invalid:", rep["errors"], file=sys.stderr)
        return 2
    if args.selftest:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    if args.limit:
        # stratified prefix per family keeps the mix matched
        corpus = corpus[:args.limit]

    names = [a.strip() for a in args.arms.split(",") if a.strip()] \
        or list(ARMS)
    results = []
    for name in names:
        arm = ARMS.get(name)
        if not arm:
            print(f"unknown arm {name!r} — choices: {sorted(ARMS)}",
                  file=sys.stderr)
            return 2
        print(f"--- arm {name} ({arm['label']})", file=sys.stderr)
        results.append(run_arm(name, arm, corpus, args.workers))
        r = results[-1]
        if "skipped" in r:
            print(f"    SKIP {r['skipped']}", file=sys.stderr)
        else:
            print(f"    acc={r['accuracy']} n={r['total']} "
                  f"p50={r['lat_p50_ms']}ms err={r['errors']}",
                  file=sys.stderr)

    stamp = time.strftime("%Y%m%d")
    out = Path(args.out) if args.out else \
        REPO / "evals" / "results" / "jev" / f"lane-arena-{stamp}.json"
    payload = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "corpus_version": da.CORPUS_VERSION,
               "corpus_cases": len(corpus),
               "arms": [{k: v for k, v in r.items() if k != "records"}
                        for r in results],
               "records": [rec for r in results for rec in
                           r.get("records", [])]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"wrote {out}")

    md = Path(args.out_md) if args.out_md else out.with_suffix(".md")
    lines = ["# lane-arena — matched held-out decision benchmark",
             "",
             f"corpus v{da.CORPUS_VERSION}, {len(corpus)} cases, "
             f"{payload['at']}", "",
             "| arm | lane | acc | n | confirm | tool | pipe | stag | "
             "p50 ms | err |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if "skipped" in r:
            lines.append(f"| {r['arm']} | {r['lane']} | SKIP | — | — | "
                         f"— | — | — | — | {r['skipped'][:60]} |")
            continue
        pt = r["per_type"]
        lines.append(
            f"| {r['arm']} | {r['lane']} | {r['accuracy']} | {r['total']} "
            f"| {pt.get('noul','-')} | {pt.get('choice','-')} | "
            f"{pt.get('noul','-')} | {pt.get('noul','-')} "
            f"| {r['lat_p50_ms']} | {r['errors']} |")
    # per_type collapses noul families — emit the real breakdown below
    lines += ["", "## per-family accuracy", ""]
    fams = {}
    for r in results:
        if "skipped" in r:
            continue
        for rec in r.get("records", []):
            fam = rec["id"].split("-")[0]
            fams.setdefault(fam, {}).setdefault(r["arm"], [0, 0])
            fams[fam][r["arm"]][1] += 1
            fams[fam][r["arm"]][0] += 1 if rec["ok"] else 0
    arms_order = [r["arm"] for r in results if "skipped" not in r]
    lines.append("| family | " + " | ".join(arms_order) + " |")
    lines.append("|---|" + "---|" * len(arms_order))
    for fam in sorted(fams):
        cells = []
        for a in arms_order:
            c, n = fams[fam].get(a, [0, 0])
            cells.append(f"{c}/{n}={round(c/n,2) if n else '-'}")
        lines.append(f"| {fam} | " + " | ".join(cells) + " |")
    lines += ["", "noul ECE / choice ECE and per-case records live in the "
              "JSON artifact.", ""]
    md.write_text("\n".join(lines))
    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
