# Dispatch outcome — cms-services-weekly-regen

## What was done

Created and installed a weekly systemd user timer on tony-dell that
regenerates the host-services CMS pages, with visible failure logging.

**New files (worktree branch `dispatch/20261004-141859-create-chaba-services-regen-se`):**

- `systemd/chaba-services-regen.service` — oneshot; runs
  `%h/CascadeProjects/chaba/scripts/ada/host-services-cms.py` through a bash
  wrapper that fails the unit on non-zero exit OR any `PUBLISH FAIL` line in
  output; `OnFailure=chaba-services-regen-fail.service`.
- `systemd/chaba-services-regen.timer` — `OnCalendar=Sun *-*-* 05:30:00`,
  `Persistent=true` (fits the existing Sunday block: worktree-sync 01:00,
  chaba-audit 02:00, chaba-kb-audit 04:00).
- `systemd/chaba-services-regen-fail.service` — self-contained failure
  reporter: POSTs a comms entry (`from: chaba`) to board-api
  `127.0.0.1:8787` on card `cms-services-weekly-regen`; if the board API is
  unreachable, writes a focus-inbox YAML into
  `~/CascadeProjects/chaba-tony-dell/docs/ssot/focus-inbox/` (the same inbox
  dir `mcp-health-snapshot` alerts use). No repo dependency — works before
  the branch merges.
- `docs/ssot/jobs/infrastructure/2026-10-04-chaba-services-regen.yml` — trail.

**Modified:**

- `scripts/ada/host-services-cms.py` — now returns exit 1 when any page
  publish fails (previously `PUBLISH FAIL` printed but exit stayed 0, so
  non-zero-exit alerting could never fire on publish errors).
- `docs/ssot/infrastructure/ssot.automation.yml` — `services_regen` entry.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — timer added to tony-dell
  `expected_services`.

**Installed on tony-dell:** all three units copied to
`~/.config/systemd/user/`, daemon-reload, timer enabled — next elapse
Sun 2026-10-11 05:30 +07.

## Verification

- `systemd-analyze verify` clean on all three units; `systemd-analyze
  calendar` confirms Sun 05:30.
- Two manual `systemctl --user start chaba-services-regen.service` runs —
  both `Result=success` (~14s each), all 7 pages published HTTP 200.
- Disk% drift reflects real state: index page `updated` timestamp advanced
  between runs and load values drifted (dell 4.69→5.33); disk column equals
  live `df` on each host — tony-dell 87% (97G/118G, watch-list flagged, leaf
  shows ⚠), tony-omen 38%, idc01 62%, idc02 20%, mn01 20%; michael-ha
  unreachable-by-design (static page).
- Failure paths tested: comms POST to board-api OK (drill comment on card);
  inbox fallback with dead API port produced valid YAML; wrapper exits 1 on
  `PUBLISH FAIL` and on script crash.

## Caveats

- The unit runs the master checkout (`%h/CascadeProjects/chaba`), so the
  exit-code patch lands there only on merge — the wrapper's `PUBLISH FAIL`
  grep covers the gap meanwhile.
- Weekly failures post to `cms-services-weekly-regen` (the only
  cms-services-* card); it remains the comms anchor after the card closes.
