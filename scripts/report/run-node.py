#!/usr/bin/env python3
"""run-node.py <node-id> — standard executor for report-graph nodes.

Reads the node from ssot.reports.yml, runs its `generator` under a
per-node flock with a timeout, then stamps the node's meta:

  inputs_at — {child_id: child generated_at} captured after the run,
    so later refreshes can tell whether a child moved since this render
  pending   — entries whose requested_at <= this run's generated_at are
    resolved (cleared); requests arriving during the run are satisfied
    by it

Not every node is runnable here: generators annotated `via <timer>` run
the script part; `planned`/non-command annotations (e.g. "multiple
producers") exit 3 so the coordinator can keep the parent's
last-known-good instead of blocking on a phantom leaf.

Exit: 0 ran ok | 2 generator failed | 3 not runnable | 4 locked.
"""
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import report  # noqa: E402

LOCK_DIR = Path("/tmp/report-nodes")
DEFAULT_TIMEOUT = 600


def generator_argv(gen: str) -> list[str] | None:
    """Registry `generator` strings are human-readable recipes
    ("scripts/x.py --flag via some.timer"); reduce to an argv or None
    when the entry isn't a runnable command."""
    cmd = (gen or "").split(" via ")[0].strip()
    if not cmd or cmd.startswith(("planned", "multiple", "manual")) \
            or "<" in cmd:
        return None
    parts = cmd.split()
    if parts[0] in ("node", "python3", "bash", "/usr/bin/python3"):
        return parts
    if parts[0].endswith(".py"):
        return ["/usr/bin/python3", *parts]
    if parts[0].endswith(".sh"):
        return ["/bin/bash", *parts]
    return parts


def run(node_id: str) -> int:
    reg = report.load_registry()
    node = next((n for n in reg.get("nodes") or []
                 if n.get("id") == node_id), None)
    if not node:
        print(json.dumps({"node": node_id, "error": "unknown node"}))
        return 1

    argv = generator_argv(node.get("generator"))
    if argv is None:
        print(json.dumps({"node": node_id, "skipped": "not runnable",
                          "generator": node.get("generator")}))
        return 3

    LOCK_DIR.mkdir(exist_ok=True)
    lock = open(LOCK_DIR / f"{node_id.replace('/', '_')}.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"node": node_id, "skipped": "already running"}))
        return 4

    timeout = int(os.environ.get("REPORT_NODE_TIMEOUT", DEFAULT_TIMEOUT))
    meta_path = node.get("meta")
    proc = subprocess.run(
        argv, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    ok = proc.returncode == 0

    inputs = report.inputs_snapshot(node, reg)
    if meta_path:
        meta = report.load_meta(meta_path)
        if meta:  # generator wrote meta — stamp inputs + resolve pending
            meta["inputs_at"] = inputs
            meta.setdefault("extra", {})["run_node_rc"] = proc.returncode
            p = report._resolve_repo_path(str(meta_path))
            import yaml
            p.write_text(yaml.safe_dump(meta, sort_keys=False,
                                        allow_unicode=True))
            report.pending_clear(meta_path, meta.get("generated_at"))
        else:
            report.write_meta(
                meta_path, node=node_id, layer=node.get("layer", "?"),
                generated_by=" ".join(argv), status="ok" if ok else "error",
                summary=(proc.stdout or "").strip().splitlines()[-1][:200]
                if proc.stdout.strip() else "",
                children=node.get("children"), inputs_at=inputs)
            report.pending_clear(meta_path)
    print(json.dumps({"node": node_id, "rc": proc.returncode,
                      "inputs_at": inputs,
                      "stderr_tail": (proc.stderr or "")[-400:]}))
    return 0 if ok else 2


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(64)
    try:
        sys.exit(run(sys.argv[1]))
    except subprocess.TimeoutExpired:
        print(json.dumps({"node": sys.argv[1], "error": "timeout"}))
        sys.exit(2)
