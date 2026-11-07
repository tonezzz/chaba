# Dispatch outcome — devnest-host-load-scenario

**Result:** completed read-only host-load assessment, report delivered.

The card spec required an explicit `target_host` but declared no remote
target, so the dispatch runner was declared explicitly:
`target_host=tony-macbook` (verified via `hostname`). Only read-only
commands ran (`hostname`, `nproc`, `uptime`, `/proc/loadavg`, `free -h`,
`df -h`, `systemctl --failed [--user]`, `command -v nvidia-smi`) — no
restart, kill, install, sudo mutation, git push, or deployment.

**Findings (evidence 2026-10-26T23:48Z):** 8 cores, load 7.50/4.68/3.14 →
load/core 0.94/0.59/0.39, a rising trend near saturation; memory 15Gi with
only 2.4Gi available and 6.2Gi of 26Gi swap in use (memory pressure is the
likely load driver); disk `/` at 25% — no pressure; no failed user units,
one failed system unit (`apport-autoreport.service`, benign
crash-reporting); no `nvidia-smi`/GPU telemetry. Recommendations are in the
report and are gated on human review — no remediation performed.

**Artifacts:** `reports/2026-10-27-devnest-host-load-tony-macbook.md`.
Board comments posted to `devnest-host-load-scenario` at start and finish.

**Verify:** read the report file; re-run the same read-only commands on
tony-macbook to compare; check card comms via board-api.
