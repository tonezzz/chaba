#!/usr/bin/env python3
"""Deterministic tool-level A/B for info-find vs bounded direct grep.

Offline and read-only: no live writes, no agent-tool sources. Run from the
repo root: python3 evals/info-find-efficiency/run.py
"""
from __future__ import annotations

import json
import statistics
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TASKS = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))
ADOPT_RATIO = 0.70  # info-find must use <=70% of baseline tokens to be adopted


def run_arm_a(task: dict) -> dict:
    cmd = ["python3", "scripts/devnest/info_find.py", "run",
           "--query", task["query"], "--offline", "--max-results", "5",
           "--session", f"bench-{task['id']}-a", "--root", str(REPO)]
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          timeout=180)
    elapsed = int((time.perf_counter() - start) * 1000)
    hydrated = 0
    try:
        payload = json.loads(proc.stdout)
        text = json.dumps(payload, ensure_ascii=False)
        sources = {k: v.get("status") for k, v in
                   (payload.get("sources") or {}).items()}
        results = payload.get("results") or []
        # An agent follows citations: hydrate the top local paths so the
        # comparison is not biased against the ranked-result format.
        seen = set()
        for item in results[:8]:
            path = str(item.get("path") or "")
            if path in seen:
                continue
            seen.add(path)
            target = REPO / path
            if not path or not target.is_file():
                continue
            excerpt = "\n".join(target.read_text(encoding="utf-8",
                                                 errors="replace").splitlines()[:80])
            text += f"\n--- {path} ---\n{excerpt}"
            hydrated += 1
        result_count = len(results)
    except (ValueError, AttributeError, OSError):
        text, sources, result_count = proc.stdout, {}, 0
    return {"bytes": len(text.encode()), "tokens_est": round(len(text) / 4),
            "duration_ms": elapsed, "tool_calls": 1 + hydrated,
            "results": result_count, "sources": sources, "text": text,
            "error": proc.stderr.strip()[:300]}


def run_arm_b(task: dict) -> dict:
    chunks, start = [], time.perf_counter()
    for command in task["direct_commands"]:
        proc = subprocess.run(command, shell=True, cwd=REPO,
                              capture_output=True, text=True, timeout=120)
        chunks.append(proc.stdout)
    elapsed = int((time.perf_counter() - start) * 1000)
    text = "\n".join(chunks)
    return {"bytes": len(text.encode()), "tokens_est": round(len(text) / 4),
            "duration_ms": elapsed, "tool_calls": len(task["direct_commands"]),
            "text": text, "error": ""}


def grade(text: str, facts: list[str]) -> dict:
    low = text.lower()
    missing = [fact for fact in facts if fact.lower() not in low]
    return {"correct": not missing, "missing": missing,
            "found": [f for f in facts if f not in missing]}


def median(values: list) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def decide(summary: dict) -> dict:
    cross, narrow = summary["cross"], summary["narrow"]
    cross_win = (cross["a"]["tokens_est"] <= ADOPT_RATIO * cross["b"]["tokens_est"]
                 and cross["a"]["correct_rate"] >= cross["b"]["correct_rate"])
    narrow_win = (narrow["b"]["tokens_est"] < narrow["a"]["tokens_est"]
                  and narrow["b"]["correct_rate"] >= narrow["a"]["correct_rate"])
    if cross_win and narrow_win:
        rec = "adopt info-find for cross-source questions only; keep direct tools for narrow lookups"
    elif cross_win:
        rec = "adopt info-find for cross-source questions; narrow tasks need more data"
    elif narrow_win:
        rec = "keep direct tools for narrow lookups; no evidence for cross-source adoption"
    else:
        rec = "no significant efficiency gain; leave info-find optional and document the trigger boundary"
    return {"cross_source_adopt": cross_win, "narrow_direct_better": narrow_win,
            "recommendation": rec, "adopt_ratio": ADOPT_RATIO}


def main() -> None:
    rows = []
    for task in TASKS["tasks"]:
        a, b = run_arm_a(task), run_arm_b(task)
        ga, gb = grade(a["text"], task["required_facts"]), grade(b["text"], task["required_facts"])
        rows.append({"id": task["id"], "kind": task["kind"], "query": task["query"],
                     "a": {k: v for k, v in a.items() if k != "text"},
                     "b": {k: v for k, v in b.items() if k != "text"},
                     "grade_a": ga, "grade_b": gb})
        print(f"{task['id']:10} A {a['tokens_est']:>5} tok/{a['duration_ms']:>5}ms "
              f"correct={ga['correct']}  B {b['tokens_est']:>5} tok/"
              f"{b['duration_ms']:>5}ms correct={gb['correct']}")

    summary = {}
    for kind in ("narrow", "cross"):
        subset = [r for r in rows if r["kind"] == kind]
        summary[kind] = {}
        for arm in ("a", "b"):
            summary[kind][arm] = {
                "tokens_est": median([r[arm]["tokens_est"] for r in subset]),
                "duration_ms": median([r[arm]["duration_ms"] for r in subset]),
                "tool_calls": median([r[arm]["tool_calls"] for r in subset]),
                "correct_rate": round(sum(r[f"grade_{arm}"]["correct"] for r in subset) / len(subset), 2),
            }
    decision = decide(summary)
    (HERE / "results.json").write_text(json.dumps(
        {"tasks": rows, "summary": summary, "decision": decision},
        indent=2, ensure_ascii=False))

    lines = ["# info-find efficiency — tool-level A/B", "",
             "Offline, deterministic, read-only. `tokens_est` = bytes/4.",
             "", "| Task | Kind | A tokens | B tokens | A correct | B correct |",
             "| --- | --- | ---: | ---: | :---: | :---: |"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['kind']} | {r['a']['tokens_est']} | "
                     f"{r['b']['tokens_est']} | {r['grade_a']['correct']} | "
                     f"{r['grade_b']['correct']} |")
    lines += ["", "## Medians", "", "| Kind | Arm | tokens | ms | tool calls | correct |",
              "| --- | --- | ---: | ---: | ---: | ---: |"]
    for kind in ("narrow", "cross"):
        for arm, label in (("a", "info-find"), ("b", "direct")):
            s = summary[kind][arm]
            lines.append(f"| {kind} | {label} | {s['tokens_est']} | "
                         f"{s['duration_ms']} | {s['tool_calls']} | {s['correct_rate']} |")
    lines += ["", "## Decision", "", f"**{decision['recommendation']}**", "",
              f"Adopt threshold: cross-source info-find tokens ≤ {int(ADOPT_RATIO*100)}% "
              "of direct tokens with equal-or-better correctness.", "",
              "Caveats: tool-level only (no LLM decision overhead), 8 tasks, "
              "offline sources, rough token proxy — directional evidence, not conclusive."]
    (HERE / "report.md").write_text("\n".join(lines) + "\n")
    print("recommendation:", decision["recommendation"])


if __name__ == "__main__":
    main()
