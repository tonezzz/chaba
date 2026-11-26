#!/usr/bin/env python3
"""Extract metrics from an arm's opencode/cline event jsonl.

Usage: extract_metrics.py <events.jsonl> [more.jsonl ...]
Prints JSON: {steps, tool_calls, tokens:{in,out,reasoning,total},
errors, text_bytes, files_touched?}
"""
import json
import sys


def main():
    tot = {"input": 0, "output": 0, "reasoning": 0, "total": 0}
    steps = tool_calls = errors = text_bytes = 0
    tools = {}
    for path in sys.argv[1:]:
        try:
            fh = open(path)
        except OSError:
            continue
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            # opencode events
            if d.get("type") == "step_finish":
                steps += 1
                tk = d.get("part", {}).get("tokens") or {}
                for k in ("input", "output", "reasoning", "total"):
                    tot[k] += int(tk.get(k) or 0)
            elif d.get("type") == "tool_use":
                tool_calls += 1
                t = d.get("part", {}).get("tool", "?")
                tools[t] = tools.get(t, 0) + 1
            elif d.get("type") == "text":
                text_bytes += len(d.get("part", {}).get("text", ""))
            # cline events
            ev = d.get("event") or {}
            et = ev.get("type", "")
            if et == "tool_call" or et == "tool_use":
                tool_calls += 1
            if et in ("error", "mistake"):
                errors += 1
            if d.get("type") == "result" or et == "run_result":
                u = ev.get("usage") or d.get("usage") or {}
                for k in ("input", "output", "reasoning", "total"):
                    tot[k] += int(u.get(k) or u.get("input_tokens" if k == "input"
                              else "output_tokens" if k == "output" else k) or 0)
    print(json.dumps({
        "steps": steps, "tool_calls": tool_calls, "tools": tools,
        "errors": errors, "text_bytes": text_bytes, "tokens": tot,
    }, indent=2))


if __name__ == "__main__":
    main()
