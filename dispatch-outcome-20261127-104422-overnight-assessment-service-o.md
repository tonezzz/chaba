# Dispatch outcome — overnight-assessment-two-step-fix (OPS-1493)

## Result: SUCCESS — service green, 6/6 steps ok ×3 consecutive runs

`overnight-assessment.service` on idc03 (`systemctl --user start`, oneshot)
now exits `Result=success` with `reports/ORCHESTRATION.json` showing
**6/6 steps ok** on three consecutive runs (run_ids 04:22:09, 04:23:24,
04:23:57 UTC). Verified live, not just code-reviewed.

## What was actually wrong (4 distinct issues, not 2)

1. **service_log_sweep** — `dict(p)` on `Counter.most_common()` tuples:
   element #0 is the pattern *string*, so `dict()` failed with
   "length 70". Card spec's "sqlite rows" guess was wrong — no sqlite in
   the script. Fix: `[{"pattern": p, "count": c} for p, c in top_errors]`
   (the shape `promote-reports.py` already consumes). An identical line-91
   fix had already landed on master mid-session (1ac983ba66); my branch
   adds the *second* latent bug behind it: `check_service()`'s exception
   path omitted `"chars"`, crashing the MD writer with `KeyError: 'chars'`
   for any unit whose `mcp_logs` call raised → added `chars: 0`.

2. **health_snapshot / tony-omen-sensor-reader** — NOT a stale entry, NOT a
   dead container. tony-omen's `/etc/sysctl.d/99-chaba-hardening.conf`
   (written 2026-11-26 by the fleet hardening pass) set
   `net.ipv4.ip_forward=0`. Docker-published ports then drop silently: DNAT
   fires in nat/PREROUTING but packets never reach the filter DOCKER chain
   (proved via iptables counters + tcpdump — SYNs arrive on tailscale0,
   nothing leaves the bridge). Host services (22, 8090, 8799) kept working,
   which is why only docker ports (sensor-reader:8001, netdata:19999)
   timed out. Restored: `sysctl -w net.ipv4.ip_forward=1` + commented the
   line out of the conf (backup `.bak-20261127`). sensor-reader → 200.

3. **health_snapshot / con01** — once omen recovered, two genuinely-down
   declared services surfaced: `mddb-follower.service` (warm-DR replica,
   :11123) and `ada-stt.service` (:8914, was disabled). Both cleanly
   stopped ~2026-11-26 evening — collateral of that night's con01
   maintenance, not SSOT-sanctioned (both `expected_state: active,
   critical: true` in ssot.audit.hosts.yml). Restarted both on con01
   (follower resumed from persisted LSN — no re-snapshot); re-enabled
   ada-stt. Both health checks → expected status.

4. **ssot_validate** — a *new* malformed file kept failing the step after
   the card's referenced fix: `jobs/infrastructure/2026-11-27-ada-review-refresh-prune-timeout.yml`
   had `- file.py: prose` items whose same-indent continuations are invalid
   YAML, AND lacked required `title:`. Converted items to `>-` folded
   scalars + added header fields. idc03 validator now: 7995/7995, 0 errors.

## Files changed (branch `dispatch/20261127-104422-overnight-assessment-service-o` @ 5a50e2c8ff, NOT pushed)

- `scripts/overnight/service-logs-sweep.py` — chars:0 fix (line-91 fix already on master)
- `docs/ssot/jobs/infrastructure/2026-11-27-ada-review-refresh-prune-timeout.yml` — YAML repair
- `docs/ssot/jobs/infrastructure/2026-11-27-overnight-assessment-two-step-fix.yml` — trail doc
- `docs/kb/host-hardening-baseline.md` — ip_forward/docker gotcha

## Out-of-band host changes (task-required, verified)

- tony-omen: `sysctl -w net.ipv4.ip_forward=1`; `/etc/sysctl.d/99-chaba-hardening.conf` line commented (backup kept)
- con01: `systemctl --user start mddb-follower.service`; `enable --now ada-stt.service`
- idc03 `~/CascadeProjects/chaba-tony-dell`: identical uncommitted patches to service-logs-sweep.py + the jobs YAML for instant verification — content identical to this branch, so kanban-commit/merge converges cleanly (no drift).

## How to verify

```
ssh idc03 'systemctl --user start overnight-assessment.service;
  python3 -c "import json;d=json.load(open(\"$HOME/CascadeProjects/chaba-tony-dell/reports/ORCHESTRATION.json\"));print(d[\"ok\"],[s[\"id\"] for s in d[\"steps\"] if not s[\"ok\"]])"'
# expect: True []  and  systemctl --user show overnight-assessment.service -p Result → success
```

Card comms posted on `overnight-assessment-two-step-fix` and
`timer-alert-idc03-overnight-assessment`.

## Watch-items (not blockers)

- mddb-api :11023/health flapped 503 once mid-run (200 before/after) —
  honest transient under load; if it recurs nightly, /health may need to
  distinguish replica-lag from down.
- ssot_validate has now failed twice on single newly-merged malformed YAML
  files — merge gate doesn't run ssot-validate-all; worth adding to the
  dispatch close-out gate (noted in trail doc followups).

lessons:
- `dict()` on a `(str, int)` tuple iterates the STRING — "element #0 has length N" means the pattern text itself, not sqlite rows; check what the iterable actually contains before reaching for row_factory.
- `net.ipv4.ip_forward=0` in a sysctl hardening drop-in silently kills ALL docker/podman published ports while host services stay green — diagnose with iptables counters (nat DNAT +N, filter DOCKER +0) + tcpdump on the ingress iface.
- A health-audit "timeout" can be host firewall/sysctl, not the service — verify the endpoint locally on the target host first (`curl 127.0.0.1` vs tailscale IP) before touching the service or the SSOT entry.
- Once one health endpoint is fixed, re-run the audit immediately — it often unmasks the NEXT real outage hiding behind the first (con01 had two dead declared services).
- Job-trail YAML under docs/ssot/jobs/ still needs `title:` + valid structure — `- file.py: prose` with same-indent continuation lines is a mapping-parse trap; use `>-` folded scalars for prose list items.
