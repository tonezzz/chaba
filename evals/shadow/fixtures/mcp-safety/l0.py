#!/usr/bin/env python3
"""L0 deterministic solver for mcp-safety: name-heuristic classification
of the frozen MCP tool surface. Writes mcp-safety.json."""
import json
import os
import re
import sys
from datetime import datetime, timezone

READ_PAT = re.compile(
    r"^(get|search|list|collect|read|query|inspect|describe|status|health|"
    r"overview|find|fetch|show|ls|cat|mcp_health|mcp_debug|ha_get|ha_search)",
    re.I)
WRITE_PAT = re.compile(
    r"(write|set|create|add|put|post|update|comment|review|include|execute|"
    r"call_write|call_delete|manage|exclude|delete|remove|drop|insert)",
    re.I)
DELETE_PAT = re.compile(r"(delete|remove|drop|destroy|purge|call_delete)",
                        re.I)


def classify(tool, server_mode):
    if DELETE_PAT.search(tool):
        return "delete"
    if WRITE_PAT.search(tool):
        return "write"
    if READ_PAT.search(tool):
        return "read-only"
    if server_mode == "read-only":
        return "read-only"
    return "unknown"


def main():
    task_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    with open(os.path.join(task_dir,
                           "evals/shadow/task/inputs/mcp-config.json")) as f:
        cfg = json.load(f)
    servers, counts = [], {"read-only": 0, "write": 0, "delete": 0,
                           "unknown": 0}
    safe = []
    for s in cfg.get("servers", []):
        mode = s.get("declared_mode", "unknown")
        tools = []
        for t in s.get("tools", []):
            c = classify(t, mode)
            counts[c] += 1
            tools.append({"name": t, "classification": c})
            if c == "read-only":
                safe.append(f"{s['name']}.{t}")
        sclass = ("read-only" if all(t["classification"] == "read-only"
                                     for t in tools)
                  else "mixed" if any(t["classification"] == "read-only"
                                      for t in tools)
                  else "unknown")
        servers.append({"name": s["name"], "server_class": sclass,
                        "tools": tools})
    counts["total_tools"] = sum(v for k, v in counts.items())
    art = {"host": os.uname().nodename,
           "collected_at": datetime.now(timezone.utc).isoformat(),
           "servers": servers,
           "summary": {"total_tools": counts["total_tools"],
                       "read_only": counts["read-only"],
                       "write": counts["write"],
                       "delete": counts["delete"],
                       "unknown": counts["unknown"]},
           "shadow_safe": sorted(safe),
           "read_only": True}
    out = os.path.join(task_dir, "evals/shadow/task/artifacts")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "mcp-safety.json"), "w") as f:
        json.dump(art, f, indent=1)
    print(json.dumps({"wrote": out + "/mcp-safety.json",
                      "safe": len(safe), "total": counts["total_tools"]}))


if __name__ == "__main__":
    main()
