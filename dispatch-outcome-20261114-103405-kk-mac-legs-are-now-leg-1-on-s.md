# Dispatch outcome — kk-mac-gateway-admission-shim (2026-11-14)

## What changed

**New:** `scripts/devnest/kk_mac_admission_shim.py` — a stdlib-only
fail-fast healthcheck proxy on idc03 `127.0.0.1:11447` in front of the
kk-mac ollama SSH tunnel (`127.0.0.1:11445`). Every request is gated on
`kk_mac_admission.snapshot()`; an ineligible Ada Nest node gets an
instant 503 so LiteLLM falls back to the paid leg instead of queueing a
120s call on a hot/busy member device. Eligible requests proxy through
unchanged (incl. streamed responses). `GET /health` exposes the live
snapshot; drain switch: `touch $XDG_RUNTIME_DIR/kkmac-admission-shim.deny`.
`KK_ADMISSION_HEARTBEAT_FILE` swaps in a simulated heartbeat for tests.

**Extended:** `kk_mac_admission.snapshot()` gained `docs=` (injected
heartbeat docs — simulation/tests) and `ssh_fallback=` params; ssh
probes are now skipped once a deny reason exists (they can only add
reasons) so stale-heartbeat checks stay instant.

**Declared/deployed on idc03:**
- `kkmac-admission-shim.service` — user unit, enabled+active
  (`stacks/idc03/litellm/kkmac-admission-shim.service`, wired into
  `deploy.sh` `USER_UNITS`; runs from the exec checkout
  `~/CascadeProjects/chaba` like embed-pool-shim).
- `~/.config/litellm/config.yaml` — all seven kk-mac `api_base` entries
  repointed `11445` → `11447` (4 `ollama-*-kkmac` models + job classes
  `summary`/`classify`/`bench`). Also synced the previously
  uncommitted 2026-11-13 live drift into the repo copy (kk-mac leg-1 on
  summary/classify/bench, chat-local → tony-dell leg-1 + kk-mac leg-2,
  `timeout: 120`).
- LiteLLM restarted; shim started before the repoint.

**Docs/SSOT:** `ssot.llm-gateway.yml` job-class chains now match live +
new `ollama-kkmac` provider entry; `ssot.audit.hosts.yml` declares the
unit under idc03; `stack.yml` records requires/state;
`docs/kb/kkmac-ollama-lane.md` documents the gate.

## Verified

- Real heartbeat (age ~220s, temp 40C via smctemp ssh fallback) →
  eligible; `summary` served by `ollama_chat/qwen2.5:32b` through the
  shim, `x-litellm-attempted-fallbacks: 0`.
- **Simulated temp-high heartbeat (cpu_temp_c=75) → instant 503 →
  LiteLLM fell back to `gemini/gemini-3.5-flash-lite` in 3.4s**
  (`x-litellm-attempted-fallbacks: 1`) — the card's done-condition.
- Zero drift verified: repo `config.yaml`, unit file, and both scripts
  are byte-identical to what's installed on idc03.
- `audit-hosts.py --host idc03` (report
  `reports/audit-hosts/idc03-20261114-104914.yml`): shim not flagged;
  remaining deltas are pre-existing baseline drift.
- Bug found+fixed in testing: upstream `Content-Length` was stripped
  from proxied responses without close-delimiting → clients hung to
  timeout. Fixed (`RESP_STRIP` keeps it); deny path drains the request
  body.

## How to verify

- `ssh idc03 'curl -s http://127.0.0.1:11447/health'` — admission
  snapshot + counters.
- `ssh idc03 'systemctl --user status kkmac-admission-shim'`
- Drain test: `touch $XDG_RUNTIME_DIR/kkmac-admission-shim.deny` on
  idc03 → any kk-mac-routed call falls to the paid leg instantly;
  `rm` the file to restore.

## Rollback

On idc03: restore the 4 kk-mac `api_base` + 3 job-class entries to
`http://127.0.0.1:11445` in `~/.config/litellm/config.yaml`, restart
litellm; `systemctl --user disable --now kkmac-admission-shim`.
Pre-change live config retrievable via `git show HEAD~1` of the served
checkout or the diff recorded in this session.

## Commit

`25f28b4e81` on `dispatch/20261114-103405-kk-mac-legs-are-now-leg-1-on-s`
(9 files, +311/−28). Not pushed.
