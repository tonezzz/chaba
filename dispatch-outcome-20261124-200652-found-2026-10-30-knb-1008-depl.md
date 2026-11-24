# Dispatch outcome — KNB-1008 / card tony-omen-declares-opencode-lanes-1-but-4cbe02

## What was found (live verification, not the stale card premise)

The card (found 2026-10-30) claimed omen's runner-agent.service had
`OPENCODE_LANES=1` with no opencode binary. Both horns were already
resolved before this session:

- `OPENCODE_LANES` is **commented out** in
  `~/.config/systemd/user/runner-agent.service.d/jev-lane.conf` since
  2026-11-09 ("gated on OPS-0846 closeout"). The claim gate now fails at
  `executor=opencode but OPENCODE_LANES=0` — the "no opencode binary"
  defer reason can no longer fire (verified: no such defers in today's
  journal).
- opencode **is** installed: `~/.npm-global/bin/opencode` ->
  `@opencode/cli@2.4.1`, `opencode --version` = v2.4.1, installed
  2026-11-24 12:20. The unit's PATH already includes `~/.npm-global/bin`.
  (`~/.opencode/bin` exists but is empty — a red herring.)

Fleet binary census (verified 2026-11-24): tony-dell, tony-omen,
idc02, idc03, con01 all have a working opencode v2.4.1; mn01 has none.

## Decision

Flag left **off** on omen. Fleet-wide `OPENCODE_LANES` enablement is
gated on the three-job savings pilot and the idc02 lane re-climb
(`opencode-lane-regraduation`, OPS-1255); omen has no
`~/.local/state/opencode-lane` so it would start at S0 (shadow fixtures
only), and it declares no `push:*` labels. The binary being present
means omen is ready the moment the fleet gate opens — re-enable =
uncomment one line in jev-lane.conf + daemon-reload. Flagged for Tony
at card review rather than enabled unilaterally.

## Changes (commit 2aa306267d on dispatch/20261124-200652-...)

- `docs/ssot/infrastructure/ssot.host-software.yml` — new `opencode`
  capability whose probe mirrors `opencode_bin()` resolution
  ($OPENCODE_BIN -> PATH -> ~/.opencode/bin -> ~/.local/bin) plus the
  npm-global prefix and `command -v`; declared on the 5 hosts with the
  binary. `host-ready-check.py` now catches binary drift fleet-wide.
- `scripts/board/runner-agent.py` — `opencode_bin()` fallback gains
  `~/.npm-global/bin/opencode` (npm -g prefix installs were invisible
  unless the unit PATH carried the prefix — exactly omen's case).
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — tony-omen
  runner-agent.service entry documenting env/drop-ins and the
  intentionally-off flag.
- `docs/kb/new-host-onboarding.md` — runner enrollment now requires the
  opencode capability declaration for lane-serving hosts.
- `docs/ssot/jobs/infrastructure/2026-11-24-omen-opencode-lane-flag.yml`
  — full job trail.

## Verification

- `python3 scripts/host-ready-check.py` fleet-wide: opencode probe
  **pass** on tony-dell, tony-omen, con01, idc02, idc03 (kk-mac /
  kk-macbook down = pre-existing unreachable laptops, informational).
- `python3 -m unittest tests.board.test_executor_contract
  tests.board.test_runner_agent_lane` — 144 tests, all OK.
- `node scripts/ssot-validate-all.mjs` — 6238 files, 0 errors.
- Live: `systemctl --user cat runner-agent.service` on omen shows no
  OPENCODE_LANES=1; `~/.npm-global/bin/opencode --version` = v2.4.1.

lessons:
- Card premise was ~3 weeks stale — re-verify live unit env before acting on "flag set but binary missing" findings; the flag had already been commented out.
- `npm i -g @opencode/cli` lands in `~/.npm-global/bin` on omen — outside both old `opencode_bin()` fallbacks and default PATH; capability probes must cover prefix installs, not just `~/.opencode/bin`.
- Binary presence and lane enablement are separate gates — ssot.host-software tracks the binary, ssot.devnest-lanes + per-host lane_gate stage track the lane; don't conflate them when resolving "install or unflag" cards.
