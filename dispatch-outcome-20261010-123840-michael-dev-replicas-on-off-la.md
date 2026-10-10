# Dispatch outcome — michael-dev off-LAN mirror gate

**Card:** `michael-dev-offlan-mirrors` — idc03 (~1.5k/day) + tony-omen
(~2.1k/day) severe log lines: `mha_mirror_*` REST sensors + template
mirrors on michael-dev replicas can't reach `http://michael-ha:8123`
off-LAN → timeouts + UndefinedError spam.

**Decision (already on card):** Tony answered request
`mirror-replica-policy` = **gate-mirrors** — keep replicas, gate
`mha_mirror_*` behind a reachability check (fail quiet, retry slow).
This dispatch implemented that answer.

## What changed

All in the worktree, committed on
`dispatch/20261010-123840-michael-dev-replicas-on-off-la` (0b392077).
Nothing deployed, nothing pushed.

- `docs/home-assistant/dev/dev-mocks.yaml` (canonical package source,
  deployed as `packages/a_dev_mocks.yaml`):
  - new `command_line` binary_sensor **`michael_ha_reachable`** — probes
    `http://michael-ha:8123/` with curl every 300s, always exits 0 (quiet;
    this is the "retry slow" path).
  - all 57 `rest:` mirror resources: `scan_interval: 30 → 86400`,
    `timeout: 5` — scheduled poll is now a once-a-day fallback.
  - new **`mha_mirror_refresh` automation** — every 30s fires
    `homeassistant.update_entity` on all mirror sensors **only while the
    gate is on** (parity cadence when reachable, e.g. tony-dell), plus one
    burst on gate→off so mirrors mark `unavailable` promptly.
  - every mirror's `value_template`/`availability` now guards
    `value_json is defined and value_json is mapping` — kills the
    UndefinedError raised rendering `value_json.state` on failed/empty
    fetches; availability also ANDs the gate.
  - the 9 template switch wrappers (`rest_command.mha_call`) get
    `availability` on the same gate — no dead-link toggle hangs.
- `stacks/tony-omen/michael-dev/packages/a_dev_mocks.yaml` +
  `stacks/tony-dell/michael-dev/packages/a_dev_mocks.yaml` — same gated
  transform applied to the tracked host snapshots.
- `scripts/home-assistant/mirror-sweep.py` — `--yaml` emitter now emits
  gated blocks and reminds to append new mirrors to the automation's
  entity list.
- SSOT: `ssot.home-assistant.entities.yml` dev_mocks note,
  `ssot.home-assistant.michael.dev.yml` entity_mocks note, `AGENTS.md`
  parity-entities line.
- Trail: `docs/ssot/jobs/home-assistant/2026-10-10-mha-mirror-gate.yml`.

## Deploy (not done by this dispatch)

Per replica host, copy `docs/home-assistant/dev/dev-mocks.yaml` to
`~/.config/michael-dev/packages/a_dev_mocks.yaml` then `ha_reload_core`
via HA-MCP or `systemctl --user restart michael-dev.service` (or run
`scripts/home-assistant/deploy-michael-dev.sh` on that host).
**Gap found:** `stacks/idc03/michael-dev/packages/` is empty — the live
package on idc03 was never tracked; deploy + add it to stacks tracking
like the other two hosts.

## How to verify

- `python3` yaml parse of all three package files passes (validated here
  with a `!secret`-tolerant loader); no entity_id collisions with the
  template mocks.
- Post-deploy on idc03/tony-omen: `binary_sensor.michael_ha_reachable`
  = off while michael-ha is unreachable; mirror sensors show
  `unavailable`; `journalctl --user -u michael-dev` / container logs show
  ~0 REST timeout/UndefinedError lines (vs ~1.5–2.1k/day). Residual: one
  fetch per mirror at HA startup + once daily ≈ 57 lines/event.
- On tony-dell (same LAN): gate stays on, mirrors refresh every 30s as
  before.
