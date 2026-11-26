#!/usr/bin/env python3
"""
Fleet GPU Availability Report

Queries sidecar metrics from Redis to show GPU capacity across all hosts.

Usage:
  python3 scripts/gpu_status.py --redis 100.123.163.11
"""

import argparse
import json
import redis
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Show fleet GPU availability")
    parser.add_argument("--redis", default="100.123.163.11", help="Redis host")
    args = parser.parse_args()

    r = redis.Redis(host=args.redis, decode_responses=True)

    # Active GPU reservation holds: {(host, gpu_index): hold_info}
    holds = {}
    for key in r.scan_iter("gpu:hold:*"):
        parts = key.split(":")
        if len(parts) != 4:
            continue
        try:
            idx = int(parts[3])
        except ValueError:
            continue
        try:
            info = json.loads(r.get(key) or "{}")
        except json.JSONDecodeError:
            info = {}
        holds[(parts[2], idx)] = info

    print(f"Fleet GPU Status — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 78)
    print(f"{'HOST':<12} {'GPU':<24} {'VRAM TOTAL':>11} {'VRAM USED':>11} {'VRAM FREE':>11} {'UTIL':>6} {'HOLD':<14} {'TAGS'}")
    print("-" * 78)

    total_free = 0
    gpu_hosts = 0

    for key in sorted(r.scan_iter("sidecar:*")):
        data = r.hgetall(key)
        hostname = data.get("hostname", key.split(":")[-1])
        gpu_count = int(data.get("gpu_count", 0))
        tags = data.get("tags", "[]")

        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = []

        if gpu_count == 0:
            print(f"{hostname:<12} {'(no GPU)':<24} {'-':>11} {'-':>11} {'-':>11} {'-':>6} {'-':<14} {','.join(tags)}")
            continue

        gpu_hosts += 1
        gpus = json.loads(data.get("gpus", "[]"))
        for gpu in gpus:
            name = gpu.get("name", "unknown")
            total_mb = gpu.get("mem_used_mb", 0) + gpu.get("mem_free_mb", 0)
            used_mb = gpu.get("mem_used_mb", 0)
            free_mb = gpu.get("mem_free_mb", 0)
            util = gpu.get("util_pct", 0)
            total_free += free_mb
            hold = holds.get((hostname, gpu.get("index")))
            hold_label = (hold or {}).get("job_id", "RESERVED")[:14] if hold else "-"
            print(f"{hostname:<12} {name:<24} {total_mb:>8}MB {used_mb:>8}MB {free_mb:>8}MB {util:>5}% {hold_label:<14} {','.join(tags)}")

    print("-" * 78)
    print(f"GPU hosts: {gpu_hosts} | Total free VRAM: {total_free} MB ({total_free/1024:.1f} GB)")

    # Active reservations detail
    if holds:
        print()
        print("Active GPU reservations:")
        for (host, idx), info in sorted(holds.items()):
            key = f"gpu:hold:{host}:{idx}"
            pttl = r.pttl(key)
            ttl_s = max(0, pttl) // 1000 if pttl and pttl > 0 else 0
            print(f"  {host} gpu{idx}: job={info.get('job_id', '?')} "
                  f"reservation={info.get('reservation_id', '?')} ttl={ttl_s}s")

    # Show recommendations
    print()
    print("GPU job sizing guidance:")
    for vram_gb in [1, 2, 3, 4]:
        needed_mb = vram_gb * 1024
        status = "AVAILABLE" if total_free >= needed_mb else "WAIT (insufficient free VRAM)"
        print(f"  {vram_gb}GB job: {status}")


if __name__ == "__main__":
    main()