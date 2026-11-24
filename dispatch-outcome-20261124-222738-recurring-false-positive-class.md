# Dispatch outcome — cms-auto-health host-down gate

Card: `cms-auto-health-stop-carding-powered-off-e11c7a` (KNB-0046)
Branch: `dispatch/20261124-222738-recurring-false-positive-class`
Commit: `f2aeb3a39c7` — fix(ada): cms-auto-health host-down gate for powered-off generators

## What changed

Direction A from the card spec — explicit host field + reachability gate:

- `stacks/services/nest-mgr/nest-mgr.py` — `publish()` now writes
  `host: <hostname>` into the `ada-cms-automation/nest-<host>` registry
  cfg on every publish (3-line add incl. comment).
- `scripts/ada/cms-auto-health.py` —
  - `_tailscale_peers()` / `host_online()`: one cached
    `tailscale status --json` per run builds a label→online map
    (HostName, DNSName first label, TailscaleIPs, self=online). Probed
    lazily — only when a cfg would otherwise go unhealthy.
  - `host_gate()` wraps `judge()`: a stale/error/dead verdict on a cfg
    carrying `host` is demoted to `state=host-down` **only** when the
    host is confirmed tailnet-offline. Unknown reachability (no host
    field, tailscale missing/erroring, peer unseen) fails open.
  - `host-down` ∈ `HEALTHY_STATES`: no card is created; an open
    `cms-auto-*` review card auto-closes through the existing
    GREEN_WINDOWS streak with a host-down-specific note
    ("generator host `x` offline on tailnet — staleness while powered
    off is expected").
- `tests/ada/test_cms_auto_health.py` — 14 tests: peer-map parsing
  (HostName/DNSName/IP/self/case/FQDN), all fail-open paths, gate
  demotion for stale+error+dead, and main()-loop card suppression +
  auto-close with CARDS/MDDB stubbed.
- `docs/ssot/jobs/cms/2026-11-24-cms-auto-health-host-down-gate.yml` —
  job record.

## Result / verification

- `pytest tests/ada/test_cms_auto_health.py` — 14/14 pass.
- `pytest tests/ada/` — 397 pass; 1 unrelated pre-existing failure
  (`test_persona_photo_store.py::test_patch_states_healthy` — staged
  ada-voice drop patches rotted on upstream drift, environmental).
- `pytest tests/nest_mgr/` — 27/27 pass.
- Live probe on tony-dell: `host_online()` → tony-macbook/mn01/idc03
  True, idc01 (off) False, ghost-host None.
- Real registry check: all 7 `nest-*` cfgs currently lack `host` —
  expected until each host's nest-mgr republishes.

## Rollout note (not done — needs per-host redeploy)

`install.sh` scp's `nest-mgr.py` to `~/.local/share/nest/` per host —
the `host` field lands only after each host's nest-mgr is redeployed
and next publishes (≤15 min later). Until then that host keeps the old
behavior. cms-auto-health itself ships via the normal repo sync
(`chaba-kanban-sync` worktree on tony-dell, next 15-min tick).

True-positive check: `cms-auto-nest-tony-dell` (nest-mgr.service
disabled on tony-dell, host reachable) still cards correctly — the
gate only suppresses on confirmed offline.

## Lessons

- `tailscale status --json` Peer.HostName can differ from the tailnet
  name (mn01's HostName is `tony-mn`) — always match DNSName first
  label + TailscaleIPs too, not just HostName.
- `.husky/pre-commit` maps `scripts/ada/*` → `pytest tests/ada`, so an
  unrelated environmental failure (`test_persona_photo_store` drop-rot
  vs live ada-voice) blocks every commit there;
  `CHABA_PRECOMMIT_TESTS=0` is the per-commit opt-out that keeps the
  other gates (SSOT YAML, pin gate) armed.
- cms-auto-health runs on tony-dell via kanban-sync.timer in the
  dedicated `chaba-kanban-sync` worktree — it self-updates from
  origin/master each tick; no manual deploy needed for the consumer
  side.
