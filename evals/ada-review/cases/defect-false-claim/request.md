# Request (anchored: card opencode-task-agent-profiles, job p1-ops-readonly-idc02)

Produce a JSON health snapshot of host idc02 using read-only commands only.
Emit only the JSON object as the final message. Required fields per the
held-out contract: host, collected_at, uptime_seconds, load1/5/15,
cpu_count, mem_total_mb, mem_available_mb, disk_root_pct, failed_units,
read_only=true.
