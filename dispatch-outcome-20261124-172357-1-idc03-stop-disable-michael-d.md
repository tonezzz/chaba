# Dispatch outcome — mn-dev-rename (OPS-0726)

**Card:** `mn-dev-rename` — physically rename the michael-dev HA dev twin (now `mn-ha-dev`) + repo sweep.
**Branch/commit:** `dispatch/20261124-172357-1-idc03-stop-disable-michael-d` @ `ab24689422a` — 81 files, +366/−340.
**Target name:** `mn-ha-dev` (not `mn-dev`) — authoritative per `ssot.system-map.yml` homes id, `ha_dev_twins` rename_map, and the 2026-11-23 grand-rename runbook. The open board request `target-name-for-the-dev-twin-rename-mn-d-c65456` was never answered; card spec text was stale.

## Live state (done, verified)

**idc02** — the live instance moved idc03→idc02 on 2026-10-26; card spec was stale about the host.
- `michael-dev.service` stopped/disabled; quadlet renamed `~/.config/containers/systemd/michael-dev.container` → `mn-ha-dev.container` (`ContainerName=mn-ha-dev`); `systemctl --user daemon-reload`; `mn-ha-dev.service` active.
- `~/.config/michael-dev` → `~/.config/mn-ha-dev`; podman container recreated; in-config refs sed'd (`.storage` left alone).
- Secrets: `~/.config/secrets/ha-michael-dev.env` → `ha-mn-ha-dev.env`; compat symlink left at old name on idc02/idc03/tony-dell/tony-omen (idc01 timed out — doesn't hold it; mn01/con01/macbook don't either).
- `mha-state-push.service` repointed to new dir + env, restarted — "mirroring 60 entity ids".
- Verified: `http://127.0.0.1:8124` → HTTP 200 on idc02; container `mn-ha-dev` healthy.

**Parked copies renamed:**
- idc03: masked `mn-ha-dev.service` symlink → /dev/null (parked), `~/.config/mn-ha-dev` dir.
- tony-dell: stale unit mask removed (no michael/mn unit links remain); `migrated-off/michael-dev.container` → `mn-ha-dev.container`.
- tony-omen: `michael-dev-parity.{service,timer}` → `mn-ha-dev-parity.*`, wants-symlink recreated (timer next run 2026-11-25 06:15); `michael-dev.container.parked` renamed.
- Historical `.bak` quadlets left with old names (deliberate — artifacts).

**Live edges:**
- idc02 `~/web-srv/caddy/Caddyfile`: added `/apps/ha/mn-ha-dev*` redirect → `:8124`, kept `michael-dev` legacy alias; `caddy validate` + reload OK; both paths → 308.
- mn01 `Caddyfile.mn01` patched live, `caddy-mn01.service` active, `/apps/ha/mn-ha-dev` → 308 verified.
- tony-dell `~/.config/devin/mcp_config.json` server key `michael-dev` → `mn-ha-dev` (backup `.bak-mnha-dev-20261124`).

## Repo sweep (~80 files)

`docs/ssot/**` live-state (infrastructure + top-level registries), `AGENTS.md`, `scripts/**`, `stacks/**` (quadlets, web Caddyfile, mn01 Caddyfile, web public apps). Excluded: `kanban/cards+archive` history, `ssot.focus.yml`, jobs history, `scripts/bench/**` corpora.

Notable edits:
- `ssot.home-assistant.lanes.yml` `instances.mn-ha-dev` (also fixed stale `ssh: idc03` → `idc02`).
- `ssot.system-map.yml`: `ha_dev_twins` marked DONE 2026-11-24; alias note removed.
- `ssot.routes.yml`: `ha-mn-ha-dev` + `ha-michael-dev-legacy`; `ssot.secrets.yml` token id `ha-mn-ha-dev-token`.
- `ssot.home-assistant.michael.dev.yml` → `ssot.home-assistant.mn-ha-dev.yml` (git mv); `deploy-michael-dev.sh` → `deploy-mn-ha-dev.sh` (git mv).
- `stacks/web/public/apps/ha/michael-dev/` → `mn-ha-dev/` (git mv); `ha-common.js` tab id/label; `index.html` menu; `ssot.ui.ha.yml`.
- Public hostname `michael-dev.surf-thailand.com` and card/job ids (`capacity-move-michael-dev`, `michael-dev-offlan-mirrors`) preserved — historical identifiers, not the service name.
- Validators: SSOT YAML syntax/required-fields/refs all passed in pre-commit; routes.json OK.

## How to verify

- `ssh idc02 'systemctl --user status mn-ha-dev.service; curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8124/'` → active + 200.
- `journalctl --user -u mha-state-push.service -n 5` → "mirroring 60 entity ids".
- `curl -sI https://idc02.taila0626a.ts.net:8124/` and the `/apps/ha/mn-ha-dev` web path → 308.
- Repo: `git show ab24689422a --stat`; `grep -rn michael-dev docs/ssot scripts stacks AGENTS.md` → only intentional leftovers (kanban history, legacy-alias comments, public hostname).

## Follow-ups / loose ends

- `~/.config/mn-ha-dev/mha-state-push.py` still contains literal `ha-michael-dev.env`/`michael-dev` strings internally — works because the compat symlink exists; clean in a follow-up once consumers are confirmed updated.
- Compat symlinks (`ha-michael-dev.env` → `ha-mn-ha-dev.env`) intentionally left on all hosts — remove after repo sync propagates and consumers are confirmed.
- idc01 was unreachable during the secret sweep; verify `ha-michael-dev.env` doesn't exist there on next contact.
- `.bak`/parked quadlet files retain old names on idc03/tony-omen — historical artifacts, not live units.
- mn01 staged web files were synced/verified via live edge check (`/apps/ha/mn-ha-dev` → 308); served dir confirmed live.

lessons:
- Card specs go stale across the grand-rename — the live instance was on idc02 (moved 2026-10-26), not idc03; always recon `systemctl --user list-units` + quadlet path before touching units.
- Generated quadlet units can't be `systemctl --user enable`d — enable via the quadlet's `WantedBy=` and daemon-reload instead.
- Board request answers may never arrive; when SSOT (system-map homes id, rename_map, runbook) is unanimous, proceed on it and note the unanswered request in the outcome.
- Leave compat symlinks at old secret paths during a fleet rename — cheap insurance for stale consumers; remove in a follow-up.
- Pre-commit SSOT validation emits IP/hostname warnings that are pre-existing noise — check for NEW warnings vs baseline rather than treating all output as failure.
