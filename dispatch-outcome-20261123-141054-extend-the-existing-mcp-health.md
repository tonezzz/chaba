# Dispatch outcome — automate-host-post-restart-verification-5ad4ac

## What was built

`transition.post_restart` was a manual-only checklist; the existing
`mcp-health-snapshot.timer` (OnBootSec=5min / OnUnitActiveSec=15min) already
fired after every boot but only took a global health snapshot. This dispatch
extends that same service path — no parallel mechanism:

- **`scripts/post-restart-verify.py` (new)** — check-only verifier, chained
  as the FIRST `'-'`-prefixed ExecStart of
  `systemd/mcp-health-snapshot.service` (first+`-` so the snapshot's known
  exit-nonzero quirk can't skip it, and findings never fail the unit).
  - **Once per boot**: reads `/proc/sys/kernel/random/boot_id`, compares to
    `~/var/chaba/post-restart-verify/last-boot-id`; same-boot timer fires
    no-op → no duplicate spam. `--force`/`--dry-run`/`--exit-code`/`--host`/
    `--boot-id`/`--ops` for manual and test runs.
  - **SSOT-gated**: only hosts in
    `automation.post_restart_verify.configured_hosts` (tony_omen, tony_dell)
    or with `host_notes.<host>.post_restart_checks` run a pass; others skip.
  - **Check types**: command, systemd, http, file, mount, podman,
    failed_units — covering the machine-checkable items of the runbook +
    host_notes (Omen: tailscale IP, nvidia-smi, cpufreq-limit + 2.00GHz cap,
    sensor-reader, weaviate-index timer, gdrive mount, dell reachability;
    Dell: podman containers, gpu-queue, yomi-api, caddy/ha-live tailnet
    endpoints, Xorg seat, barrier-pin-vt.timer, DP-2 status).
  - **Structured result**: `~/var/chaba/health/post-restart-verify-<host>-<bootid8>.json`
    + `-latest.json` + a `~/var/chaba/reports/timeline.jsonl` record.
  - **Findings**: one aggregate board-api `/inbox` entry per boot per
    must-fail-set (fingerprinted like host-ready-check); warn-level stays in
    the report. No auto-remediation; exits 0 on completed pass (OPS-0581).

## Stale refs fixed

- Omen CPU cap 2.20GHz → **2.00GHz / scaling_max_freq=2000000** in
  `docs/ssot/ssot.mysystem.home.yml` (canonical; ssot.operations.yml was
  already correct).
- Barrier KVM retired: published copies resynced from canonical
  (`public/docs/overview/ssot.mysystem.home.yml`,
  `stacks/web/public/ssot.mysystem.home.yml`);
  `docs/overview/hosts.tony-dell.yml` + public copy now record retirement
  (no barriers.service/barrierc/24800 expectation; barrier-pin-vt.timer kept);
  `workflows/monitoring/home-profile-health-check.yml` barrier-client check
  replaced with barrier-pin-vt.timer (also fixed a self-dependency
  `depends_on` bug there).
- `docs/kb/host-reboot-verification.md`: new "Automated pass" section;
  seat-unit check lists lxqt-seat/xfce-seat.
- `ssot.automation.yml`: chained_execstart noted on mcp-health-snapshot.

## Verified (on this host, env-overridden paths)

- New boot-id → one pass; same boot-id re-run → "already verified" no-op;
  `--force`/`--dry-run` behave.
- Unconfigured host (idc02) skips cleanly, no state writes, twice.
- Must-failures produce JSON report + timeline record + single inbox POST
  attempt (dead BOARD_API logged gracefully, report still written).
- `ssot-validate-all.mjs`: all changed SSOT files valid (5 pre-existing
  errors in unrelated focus-inbox/jobs files untouched).
- Trail doc: `docs/ssot/jobs/infrastructure/2026-11-23-post-restart-verify.yml`.

## To activate on hosts (not deployed — repo-only per dispatch rules)

```bash
# on tony-omen / tony-dell after checkout sync:
cp ~/CascadeProjects/chaba/systemd/mcp-health-snapshot.service \
   ~/.config/systemd/user/mcp-health-snapshot.service
systemctl --user daemon-reload
# first timer fire verifies the CURRENT boot (no state yet) — expected.
```

lessons:
- Type=oneshot: a failing non-'-' ExecStart aborts later ExecStarts — chain dependent steps first or '-'-prefix them; mcp-health-snapshot.mjs has a known exit-nonzero quirk (known_failed fix-exit-code).
- Board-api POST /inbox is the current focus-inbox door for host-side finding reporters (host-ready-check.py pattern) — don't write focus-inbox YAML from exec checkouts.
- public/docs/overview/ + stacks/web/public/ SSOT copies drift badly; docs/kb/ssot-documentation-standards.md says resync from canonical.
- YAML plain scalars can't contain ': ' — quote multi-line list entries in trail docs.
