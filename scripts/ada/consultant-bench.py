#!/usr/bin/env python3
import argparse
import json
import os
import time
import urllib.request
import urllib.error
import statistics

def ask_litellm(model, task, timeout=10):
    url = os.environ.get("LITELLM_URL", "http://100.102.134.91:4000").rstrip("/")
    url = f"{url}/v1/chat/completions"
    key = os.environ.get("LITELLM_KEY") or os.environ.get("LITELLM_KEY_BENCH", "")

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    prompt = (
        "You are an AI consultant. Your job is to decide whether to 'answer' the user's task directly "
        "or 'escalate' it to a human. Reply with exactly one word: either 'answer' or 'escalate'.\n\n"
        f"Task: {task}"
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8,
        "temperature": 0.0
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    t0 = time.time()
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        ans = r.get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()
        return {"decision": ans}, round((time.time() - t0) * 1000)
    except Exception as e:
        return {"_err": str(e)[:80]}, round((time.time() - t0) * 1000)

def parse_fixture(filepath):
    tasks = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))
    return tasks

def write_reports(model, records, summary):
    os.makedirs("reports", exist_ok=True)
    json_path = f"reports/consultant-bench-{model}.json"
    md_path = f"reports/consultant-bench-{model}.md"

    with open(json_path, 'w') as f:
        json.dump({"summary": summary, "verdicts": records}, f, indent=2)

    md_content = f"""# Consultant Bench Report: {model}

## Summary
- **Accuracy**: {summary['accuracy']:.2f}
- **p50 Latency**: {summary['lat_p50_ms']:.1f} ms
- **Escalation Rate**: {summary['escalation_rate']:.2f}
- **Total Cases**: {summary['total']}
- **Correct Verdicts**: {summary['correct']}

## Verdicts
| ID | Expected | Got | Ok | Time (ms) |
|---|---|---|---|---|
"""
    for r in records:
        md_content += f"| {r['id']} | {r['expected']} | {r['got']} | {'Yes' if r['ok'] else 'No'} | {r['ms']} |\n"

    with open(md_path, 'w') as f:
        f.write(md_content)

def main():
    parser = argparse.ArgumentParser(description="Consultant Bench Harness")
    parser.add_argument("--model", required=True, help="LiteLLM model name")
    parser.add_argument("--fixture", required=True, help="Path to tasks.jsonl fixture")
    args = parser.parse_args()

    tasks = parse_fixture(args.fixture)

    records = []
    latencies = []
    correct_count = 0
    escalation_count = 0
    total_count = len(tasks)

    for task in tasks:
        ans, ms = ask_litellm(args.model, task["task"])
        got = ans.get("decision", ans.get("_err", "error"))
        expected = task["expected"].lower()

        # Exact strict matching
        ok = (got == expected)

        if ok:
            correct_count += 1

        if got == "escalate":
            escalation_count += 1

        record = {
            "id": task["id"],
            "expected": expected,
            "got": got,
            "ok": ok,
            "ms": ms
        }
        if "_err" in ans:
            record["err"] = ans["_err"]

        records.append(record)
        latencies.append(ms)

    accuracy = correct_count / total_count if total_count > 0 else 0
    lat_p50_ms = statistics.median(latencies) if latencies else 0
    escalation_rate = escalation_count / total_count if total_count > 0 else 0

    summary = {
        "accuracy": accuracy,
        "lat_p50_ms": lat_p50_ms,
        "escalation_rate": escalation_rate,
        "total": total_count,
        "correct": correct_count
    }

    write_reports(args.model, records, summary)

    print(f"Benchmarked {args.model} on {args.fixture}")
    print(f"Accuracy: {accuracy:.2f}, Latency p50: {lat_p50_ms:.1f}ms")
    print(f"Reports written to reports/consultant-bench-{args.model}.{{json,md}}")

if __name__ == "__main__":
    main()
