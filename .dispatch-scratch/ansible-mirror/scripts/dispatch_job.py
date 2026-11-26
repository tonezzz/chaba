#!/usr/bin/env python3
"""
Job Dispatch CLI Wrapper

Simplifies dispatching jobs via the Ansible playbook.
Reads job spec from YAML file or command-line args.

Usage:
  ./dispatch_job.py --job train-llama-001 \
    --image ghcr.io/user/llama-train:latest \
    --cmd "torchrun --nproc_per_node=4 train.py" \
    --gpus 4 --min-vram 20 --require gpu

  ./dispatch_job.py -f job-spec.yaml
"""

import argparse
import json
import os
import subprocess
import sys
import yaml
from pathlib import Path


def build_ansible_cmd(args) -> list:
    """Build ansible-playbook command from parsed args."""
    cmd = [
        "ansible-playbook",
        str(Path(__file__).parent.parent / "playbooks" / "dispatch_job.yml"),
        "-i", str(Path(__file__).parent.parent / "inventory.ini"),
    ]

    # Required job parameters
    for param in ["job_id", "job_image", "job_cmd"]:
        val = getattr(args, param.replace("-", "_"))
        if not val:
            raise ValueError(f"Missing required parameter: {param}")
        if param == "job_cmd":
            # Free text: key=value -e splits on whitespace — use JSON form.
            cmd.extend(["-e", json.dumps({param: val})])
        else:
            cmd.extend(["-e", f"{param}={val}"])

    # Optional parameters with defaults
    optional_params = {
        "job_gpus": "1",
        "job_min_vram_gb": "8",
        "job_max_load_pct": "70",
        "job_max_mem_pct": "80",
        "job_timeout_sec": "86400",
        "target_group": "all",
        "container_runtime": "podman",
        "sidecar_redis_host": "100.123.163.11",
    }

    for param, default in optional_params.items():
        val = getattr(args, param.replace("-", "_"), None)
        if val is not None:
            cmd.extend(["-e", f"{param}={val}"])
        else:
            cmd.extend(["-e", f"{param}={default}"])

    # Tags (comma-separated lists)
    for param in ["job_require_tags", "job_exclude_tags"]:
        val = getattr(args, param.replace("-", "_"), None)
        if val:
            tags = ",".join(val) if isinstance(val, list) else val
            cmd.extend(["-e", f"{param}=[{tags}]"])

    # Verbosity
    if args.verbose:
        cmd.append("-" + "v" * args.verbose)

    return cmd


def main():
    parser = argparse.ArgumentParser(
        description="Dispatch containerized job via Ansible",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dispatch 4-GPU training job to any GPU host with 20GB+ VRAM
  %(prog)s --job train-001 --image my/train:latest --cmd "train.py" \\
    --gpus 4 --min-vram 20 --require gpu

  # Dispatch CPU-only batch job to IDC hosts
  %(prog)s --job batch-001 --image my/batch:latest --cmd "process.py" \\
    --gpus 0 --require idc --exclude gpu

  # From YAML spec file
  %(prog)s -f job-spec.yaml
"""
    )

    # Input modes
    parser.add_argument("-f", "--file", help="Job spec YAML file")

    # Required (if not using -f)
    parser.add_argument("--job-id", dest="job_id", help="Unique job ID")
    parser.add_argument("--image", dest="job_image", help="Container image")
    parser.add_argument("--cmd", dest="job_cmd", help="Command to run in container")

    # Resource requirements
    parser.add_argument("--gpus", dest="job_gpus", type=int, default=1, help="GPUs required (default: 1)")
    parser.add_argument("--min-vram", dest="job_min_vram_gb", type=int, default=8, help="Min VRAM per GPU in GB (default: 8)")
    parser.add_argument("--max-load", dest="job_max_load_pct", type=int, default=70, help="Max CPU load %% (default: 70)")
    parser.add_argument("--max-mem", dest="job_max_mem_pct", type=int, default=80, help="Max memory %% (default: 80)")

    # Placement constraints
    parser.add_argument("--require", dest="job_require_tags", action="append", help="Required host tags (repeatable)")
    parser.add_argument("--exclude", dest="job_exclude_tags", action="append", help="Excluded host tags (repeatable)")
    parser.add_argument("--group", dest="target_group", default="all", help="Target host group (default: all)")

    # Runtime
    parser.add_argument("--timeout", dest="job_timeout_sec", type=int, default=86400, help="Job timeout seconds (default: 86400)")
    parser.add_argument("--runtime", dest="container_runtime", choices=["podman", "docker"], default="podman")

    # Infrastructure
    parser.add_argument("--redis", dest="sidecar_redis_host", default="100.123.163.11", help="Redis host for sidecar metrics")

    # Output
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv, -vvv)")
    parser.add_argument("--dry-run", action="store_true", help="Print ansible command without executing")

    args = parser.parse_args()

    # Load from YAML file if provided
    if args.file:
        with open(args.file) as f:
            spec = yaml.safe_load(f)
        for k, v in spec.items():
            if not getattr(args, k.replace("-", "_"), None):
                setattr(args, k.replace("-", "_"), v)

    # Validate required
    for req in ["job_id", "job_image", "job_cmd"]:
        if not getattr(args, req.replace("-", "_")):
            parser.error(f"Missing required argument: --{req} (or provide via -f)")

    try:
        cmd = build_ansible_cmd(args)
    except ValueError as e:
        parser.error(str(e))

    print(f"Dispatching job {args.job_id}...")
    print(f"Command: {' '.join(cmd)}")

    if args.dry_run:
        print("DRY RUN - not executing")
        return 0

    # Execute
    env = os.environ.copy()
    env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    env["ANSIBLE_PIPELINING"] = "True"

    result = subprocess.run(cmd, env=env)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())