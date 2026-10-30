#!/usr/bin/env python3
"""Route explicit DevNest task specs to eligible worker inboxes.

This is deliberately a broker, not a task generator. Upstream producers place
normalized JSON specs in the shared inbox. The broker routes KK-Mac work when
its admission gate is green and stages complete Colab packs without launching
or stopping a runtime.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from kk_mac_admission import snapshot

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
KK_CLASSES = {"summary", "operator_brief", "structured_extract", "safe_route"}


def rc(*args: str, input_text: str | None = None) -> str:
    p = subprocess.run(
        ["rclone", *args], input=input_text, text=True,
        capture_output=True, timeout=90,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:300] or "rclone failed")
    return p.stdout


def inbox(remote: str) -> list[str]:
    return [
        x for x in rc("lsf", f"{remote}/inbox", "--files-only").splitlines()
        if x.endswith(".json")
    ]


def queue_depth(remote: str) -> int:
    # One recursive listing avoids one remote API call per historical pack.
    entries = rc("lsf", f"{remote}/packs", "--recursive").splitlines()
    packs = {line.split("/", 1)[0] for line in entries if line.strip()}
    terminal = {
        line.split("/", 1)[0]
        for line in entries
        if line.endswith("/done") or line.endswith("/failed")
    }
    return len(packs - terminal)


def read_spec(remote: str, filename: str) -> dict:
    spec = json.loads(rc("cat", f"{remote}/inbox/{filename}"))
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    if not SLUG.fullmatch(str(spec.get("task_id", ""))):
        raise ValueError("task_id must be a safe slug")
    lane = spec.get("lane")
    if lane not in {"kk_mac_local", "colab"}:
        raise ValueError("lane must be kk_mac_local or colab")
    if not spec.get("task_class"):
        raise ValueError("task_class is required")
    return spec


def mark_routed(remote: str, filename: str, destination: str) -> None:
    rc(
        "rcat", f"{remote}/inbox/{filename}.routed",
        input_text=json.dumps({"destination": destination}) + "\n",
    )


def route_kk(
    spec: dict, source: str, filename: str, destination: str
) -> str:
    if spec["task_class"] not in KK_CLASSES:
        raise ValueError(f"KK task class not admitted: {spec['task_class']}")
    if not spec.get("prompt"):
        raise ValueError("KK task requires prompt")
    target = f"{destination}/inbox/{spec['task_id']}.json"
    rc("copyto", f"{source}/inbox/{filename}", target)
    return target


def route_colab(spec: dict, source: str, destination: str) -> str:
    pack_source = Path(str(spec.get("pack_source", ""))).resolve()
    repo = Path(__file__).resolve().parents[2]
    allowed = (repo / "scripts" / "colab" / "packs").resolve()
    if not str(pack_source).startswith(str(allowed) + "/"):
        raise ValueError("pack_source must be under scripts/colab/packs")
    pack_name = str(spec.get("pack_name") or pack_source.name)
    if not SLUG.fullmatch(pack_name):
        raise ValueError("pack_name must be a safe slug")
    # Staging is intentional; runtime launch remains an explicit Colab gate.
    rc("copy", str(pack_source), f"{destination}/packs/{pack_name}")
    return f"{destination}/packs/{pack_name}"


def produce(
    source: str = "gdrive:ada-nest-devnest",
    kk_remote: str = "gdrive:ada-nest-kk-llm",
    colab_remote: str = "gdrive:ada-nest",
    max_depth: int = 3,
) -> dict:
    result = {"source": source, "routed": [], "held": [], "rejected": []}
    gate = snapshot()
    kk_enabled = os.environ.get("DEVNEST_KK_MAC_ENABLED", "true").lower() == "true"
    source_entries = set(rc("lsf", f"{source}/inbox", "--recursive").splitlines())
    kk_depth = queue_depth(kk_remote) if kk_enabled else 0
    for filename in inbox(source):
        try:
            spec = read_spec(source, filename)
            if f"{spec['task_id']}.routed" in source_entries:
                continue
            if spec["lane"] == "kk_mac_local":
                if not kk_enabled:
                    result["held"].append(f"{filename}:kk_disabled")
                    continue
                if kk_depth >= max_depth:
                    result["held"].append(f"{filename}:kk_capacity")
                    continue
                if not gate.get("eligible"):
                    result["held"].append(f"{filename}:kk_admission")
                    continue
                destination = route_kk(
                    spec, source, filename, kk_remote
                )
                kk_depth += 1
            else:
                destination = route_colab(spec, source, colab_remote)
            mark_routed(source, filename, destination)
            result["routed"].append({
                "task_id": spec["task_id"],
                "lane": spec["lane"],
                "destination": destination,
            })
        except Exception as exc:
            result["rejected"].append(f"{filename}:{type(exc).__name__}")
    result["kk_gate"] = gate
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="gdrive:ada-nest-devnest")
    ap.add_argument("--kk-remote", default="gdrive:ada-nest-kk-llm")
    ap.add_argument("--colab-remote", default="gdrive:ada-nest")
    ap.add_argument("--max-depth", type=int, default=3)
    args = ap.parse_args()
    print(json.dumps(produce(
        args.source, args.kk_remote, args.colab_remote, args.max_depth
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
