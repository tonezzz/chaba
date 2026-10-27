# Task: read-only host health report — {{HOST}}

Produce a JSON health snapshot of THIS host (`{{HOST}}`). Emit ONLY the
JSON object as your final message — the runner writes it for you; you
hold no write tools and any denied tool call fails the job.

Collect with read-only commands only (everything else is denied):

- hostname / current time: `hostname`, `date -Iseconds`
- uptime + load averages: `uptime` (load1/load5/load15 from the output).
  For `uptime_seconds`: call `uptime -s` (boot timestamp) and `date +%s`
  (epoch now) as two separate calls, then subtract the two numbers
  YOURSELF — `python3`/`expr`/`bc` are not allowlisted and will be
  denied. NEVER try `/proc/*` — reads outside the checkout are denied
  and count against the job.
- cpu count: `nproc` or `lscpu`
- memory: `free -m` (values in MB)
- root filesystem usage: `df -P /` (used percent, integer)
- failed units: `systemctl list-units --failed --no-legend` and
  `systemctl --user list-units --failed --no-legend` (list names only;
  empty list is fine)

Call commands ONE per bash call — `&&` chains are denied as a whole.
Reading files outside this checkout (e.g. `/proc/*`) is denied — use the
commands above; they already cover every field.

Required JSON fields (exact names):

    host, collected_at, uptime_seconds, load1, load5, load15,
    cpu_count, mem_total_mb, mem_available_mb, disk_root_pct,
    failed_units, read_only

`read_only` MUST be `true`. Do not write files, do not read anything
under `~/.config/secrets`, do not install or change anything. When the
JSON is complete, output it and stop.
