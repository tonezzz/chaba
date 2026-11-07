#!/usr/bin/env python3
"""Held-out verifier for mcp-safety: every declared tool present,
classification vocabulary correct, unknown never counted as safe."""
import json
import os
import sys

VALID = {"read-only", "write", "delete", "unknown"}


def verify(task_dir):
    path = os.path.join(task_dir,
                        "evals/shadow/task/artifacts/mcp-safety.json")
    cfg_path = os.path.join(task_dir,
                            "evals/shadow/task/inputs/mcp-config.json")
    try:
        with open(path) as f:
            a = json.load(f)
        with open(cfg_path) as f:
            cfg = json.load(f)
    except Exception as e:
        return {"verdict": "fail", "checks": {"artifact readable": False,
                                              "error": str(e)}}
    checks = {}
    checks["required fields"] = all(
        k in a for k in ("host", "collected_at", "servers", "summary",
                         "shadow_safe", "read_only"))
    checks["read_only true"] = a.get("read_only") is True

    # coverage: every declared server/tool appears exactly once
    want = {(s["name"], t) for s in cfg.get("servers", [])
            for t in s.get("tools", [])}
    got = set()
    cls_map = {}
    for s in a.get("servers", []):
        for t in s.get("tools", []):
            got.add((s.get("name"), t.get("name")))
            cls_map[(s.get("name"), t.get("name"))] = t.get("classification")
    checks["all servers covered"] = all(
        w[0] in {s.get("name") for s in a.get("servers", [])} for w in want)
    checks["all tools covered"] = want <= got
    checks["classification vocab valid"] = all(
        c in VALID for c in cls_map.values())

    # conservative rule: nothing classified write/delete/unknown is in shadow_safe
    safe = set(a.get("shadow_safe", []))
    unsafe_in_safe = [f"{sn}.{tn}" for (sn, tn), c in cls_map.items()
                      if c != "read-only" and f"{sn}.{tn}" in safe]
    checks["no unsafe tool marked shadow-safe"] = not unsafe_in_safe

    # declared_mode=unknown servers may not yield read-only without name evidence;
    # verifier enforces the weaker invariant: their tools can't be 'unknown'
    # AND 'read-only' simultaneously — the real rule it enforces:
    # a tool with a mutating name must not be read-only.
    mutating = {"write", "delete", "create", "put", "execute", "set",
                "manage", "post", "remove", "exclude", "include"}
    bad_ro = []
    for (sn, tn), c in cls_map.items():
        low = (tn or "").lower()
        if c == "read-only" and any(m in low for m in
                                    ("delete", "write", "create", "put",
                                     "execute", "remove")):
            bad_ro.append(f"{sn}.{tn}")
    checks["no mutating tool marked read-only"] = not bad_ro

    # summary math
    s = a.get("summary", {})
    tot = len(want)
    sums = all(s.get(k, -1) >= 0 for k in
               ("total_tools", "read_only", "write", "delete", "unknown"))
    checks["summary fields numeric"] = sums
    checks["summary totals consistent"] = (
        s.get("total_tools") == tot
        and s.get("read_only", 0) + s.get("write", 0) + s.get("delete", 0)
        + s.get("unknown", 0) == tot)

    verdict = "pass" if all(v is True for v in checks.values()) else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": "mcp-safety.json",
            "flagged": {"unsafe_in_safe": unsafe_in_safe,
                        "mutating_marked_ro": bad_ro}}


if __name__ == "__main__":
    td = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(json.dumps(verify(td), indent=1))
