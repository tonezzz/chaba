# dispatch-outcome — ansible-chaba-stale-quadlet-inventory

## What was found

The 2026-11-26T02:17Z regeneration by `/home/tony/tony-projects/ansible-chaba`
(idc02, previously unversioned) rewrote fleet quadlets from badly stale
`host_vars` inventory. Confirmed damage/drift:

- **idc03**: `mddb.container` would have restarted the MDDB primary on
  `tradik/mddb:2.15.3` with `/data` (empty DB), dropping
  `mddb-follower.env` + ~30 env vars; `gemini-ollama-proxy.container` ran a
  different script path than live; `obsidian-vault.container` shadowed a
  native systemd unit; `tony-ha.container` OK.
- **idc02**: `mddb.container` (live follower) badly stale; `mddb-cms` +
  `mddb-panel` were phantom services that never ran (failed loop);
  `notebooklm-rest` had CHANGEME_* env that would override the real
  env_file; `notebooklm-mcp` pointed at a missing env file; 
  `status-data-api.container` shadowed an enabled manual unit.
- **con01**: `mddb-follower.container` stale image (2.15.4-lsn).
- **mn01**: `mn-ha-dev.container` missing PodmanArgs/ports/healthchecks;
  `storage.conf` had fatal multi-line TOML — **all podman commands broken**.
- **tony-dell**: mass unit failure 11:55–11:56 (conmon `k8s-file` +
  `--log-tag`); 10 quadlets belonged to services migrated off dell months
  ago (ActiveEnterTimestamp empty, no containers); `chaba-postgres-16` and
  `raceman-php` quadlets drifted from live.
- **All 5 hosts**: ansible-written `storage.conf` carried an invalid
  `rootless` key (podman decode warning on every call) and string/bool
  `pull_options` issues.

## What changed

- Restored drifted `.container` files to live truth (`podman inspect` +
  pre-regen `.bak-*` files + `stacks/` SSOT) on idc03 (×4), idc02 (×3),
  con01, mn01, tony-dell (×2). **Zero restarts** — file edits +
  `systemctl --user daemon-reload` only; running containers untouched.
- Retired (renamed `.retired-20261127-quadsweep`): idc03 obsidian-vault;
  idc02 mddb-cms/mddb-panel/status-data-api; tony-dell 10 migrated-service
  quadlets. `reset-failed` applied on dell.
- Rewrote `~/.config/containers/storage.conf` on all 5 hosts (valid TOML,
  no `rootless` key); backups `storage.conf.bak-20261127-quadsweep`.
- **Retired the generator**: `quadlet_services` → `quadlet_services_retired`
  in all 5 `inventory/host_vars/*.yml` (data preserved; role skips).
  Fixed `roles/quadlet-services/templates/storage.conf.j2` (removed
  `rootless`).
- **Version control**: `git init` + pushed to
  <https://github.com/tonezzz/chaba-ansible> (private). The card's declared
  `github.com/tony/chaba-ansible` doesn't exist and `tony` isn't an
  account tonezzz can create under — fleet GitHub identity is `tonezzz`.
  `.github/workflows/ansible.yml` left on disk but gitignored (gh token
  lacks `workflow` scope).

## Result

Every ansible-regenerated quadlet on the fleet now either matches live
`podman inspect` truth or is retired. The ansible-chaba quadlet path can
no longer rewrite quadlets (`quadlet_services` undefined → role no-ops).
Trail doc: `docs/ssot/jobs/infrastructure/2026-11-27-ansible-chaba-stale-quadlet-inventory.yml`.

## How to verify

- `ssh <host> 'podman info'` clean on idc03/idc02/con01/mn01/tony-dell.
- `ssh idc03 'systemctl --user list-units | grep -E "mddb|ollama|gemini"'`
  — active running, correct descriptions.
- `ssh tony-dell 'ls ~/.config/containers/systemd/*.container'` — only
  chaba-postgres-16, gemini-ollama-proxy, gpu-queue{,-processor},
  raceman-php remain.
- `cd /home/tony/tony-projects/ansible-chaba && git log --oneline` and
  `gh repo view tonezzz/chaba-ansible`.

## Open items (need Tony)

- tony-dell `gemini-ollama-proxy.service` is enabled+failed (kept per
  sibling card); it will retry at next boot — approve a manual start or
  retire it.
- stacks/ SSOT gaps: idc02 mddb/notebooklm-*/status-data-api and idc03
  tony-ha have no `stacks/` entries — quadlet truth is on-host only.
- con01 `stacks/con01/mddb-follower/mddb-follower.container` has the
  replication secret in plaintext (pre-existing).

lessons:
- Quadlet units without `ContainerName=` produce `systemd-<unit>` container names — audit `podman ps -a`, not assumed names.
- "Managed by Ansible" headers + `Documentation=` URLs mark generated quadlets; verify each against `podman inspect` before trusting.
- Podman `storage.conf`: TOML inline tables must be single-line; `pull_options` wants STRING values; `rootless` is not a valid key.
- Multi-line TOML inline tables are TOML 1.1 — podman's parser rejects them fatally (broke all of mn01's podman).
- `gh` OAuth tokens need `workflow` scope to push `.github/workflows/`; exclude or use git credential helper for pushes.
