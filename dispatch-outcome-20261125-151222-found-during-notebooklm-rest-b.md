# Dispatch outcome — ada-lane-health-gate-misses-notebooklm-dep (ADA-1369)

## Verdict

**Shipped live — option (a)+(b) implemented, extended to full coverage.**
Every Ada lane whose env carries `NOTEBOOKLM_REST_BASE_URL` now has a
`dep-gate.conf` ExecStartPre drop-in that waits fail-closed until BOTH
hard deps answer their unauthenticated `/health` endpoints: MDDB
`http://100.102.134.91:11023/health` AND notebooklm-rest
`http://100.123.163.11:3011/health`. 11 drop-ins live across idc03 (7),
tony-omen (2), mn01 (2). Zero service restarts — gates take effect on
each unit's next start. Fully reversible per host.

## What the live audit found (card model was incomplete)

- The kraut/tony "gate" was an **ad-hoc, untracked** `mddb-gate.conf`
  dated 2026-10-05 — in neither chaba nor ada-voice git. Now superseded
  by the canonical `dep-gate.conf` and removed.
- **tony-omen lab lanes had NO drop-ins at all** — ada-dev + ada-kk-dev
  migrated idc03→omen 2026-11-18 (SYS-0151) and neither stagger nor any
  health gate followed. They were running fully ungated.
- **mn01 standby lanes** (ada-ha-tony, ada-ha-michael — disabled-but-
  running) also had zero drop-ins.
- `ada-bankq-student` excluded — no `NOTEBOOKLM_REST_BASE_URL` in env
  (open-jev student lane, not a voice lane). Relays excluded likewise.

## Changes

**Repo (this branch, uncommitted per dispatch rules):**
- `stacks/idc03/ada-dep-gate/{install.sh,stack.yml}` — 7 units;
  install removes legacy `mddb-gate.conf`
- `stacks/tony-omen/ada-dep-gate/{install.sh,stack.yml}` — ada-dev,
  ada-kk-dev
- `stacks/mn01/ada-dep-gate/{install.sh,stack.yml}` — ada-ha-tony,
  ada-ha-michael
- `docs/ssot/jobs/ada/2026-11-25-ada-dep-gate-notebooklm.yml` — job trail

**Live (drop-ins + `daemon-reload` only, no restarts):**
- idc03: 7× `dep-gate.conf`, 0 `mddb-gate.conf` left
- tony-omen: 2× `dep-gate.conf`
- mn01: 2× `dep-gate.conf`

## Gate semantics

`ExecStartPre` loops ≤90×: `curl -sf -m3 :11023/health && curl -sf -m3
:3011/health && exit 0; sleep 5` — fail-closed on dep outage; unit's
`Restart=on-failure` retries until deps return. `TimeoutStartSec`:
**180s effective on idc03** (stagger.conf is a lexically-later drop-in
and wins — same budget the old mddb-gate ran under), **300s on
omen/mn01** (dep-gate.conf's own value; default 90s would have killed
the loop early).

## Verification

- `systemctl --user show <unit> -p ExecStartPre` shows the dual-dep
  curl on idc03 kraut/chaba, omen ada-dev, mn01 ada-ha-tony; stagger
  preserved on idc03.
- `TimeoutStartUSec`: 3min idc03 / 5min omen+mn01 — as designed.
- All 11 units still `active` post-daemon-reload.
- Both `/health` endpoints returned 200 from idc02/omen/mn01 **before**
  gating — no unreachable-dep trap.

## Rollback

Per host: `rm ~/.config/systemd/user/<unit>.service.d/dep-gate.conf &&
systemctl --user daemon-reload`. Note: idc03 kraut/tony's legacy
MDDB-only `mddb-gate.conf` is not auto-restored (it was untracked);
recreate the single-curl line if needed.

## Follow-ups (not done, worth noting)

- tony-omen lanes still lack the **stagger** drop-in — probably fine
  (stagger exists for idc03 fleet deploys via deploy-ada.sh), but if
  omen lanes ever mass-restart they have no serialization.
- `install.sh` files are the canonical writers — live drop-ins should
  be changed via repo + rerun, not hand-edits.

lessons:
- "Only kraut/tony have a gate" understated it: the gate was an untracked ad-hoc drop-in from 2026-10-05 — verify drop-ins with `systemctl --user cat`, not repo grep; repo-clean ≠ live-clean.
- Units migrated idc03→tony-omen 2026-11-18 lost ALL drop-ins (stagger + gates) — host migrations must carry ~/.config/systemd/user/*.service.d/, not just unit files.
- Drop-in filename order decides both ExecStartPre sequence AND scalar overrides: dep-gate.conf < stagger.conf, so stagger's TimeoutStartSec=180 silently capped the gate's 300s budget on idc03.
- TimeoutStartSec must live in the gate drop-in itself on hosts without stagger — systemd default 90s would kill a 450s-wait ExecStartPre loop mid-retry.
- Gated only lanes whose env actually has NOTEBOOKLM_REST_BASE_URL (grep ~/.config/secrets per host) — ada-bankq-student and relays don't consume the dep.
