# Dispatch outcome — tony-ha svc-chaba-scripts admin fix

Card: `tony-ha-svc-chaba-scripts-lost-admin-lov-dc0302` (OPS-1305)
Date: 2026-11-25 · Runner: idc02 dispatch worktree

## What was wrong

`network-scan-tony` (tony-dell, every 15m) failed at
`scripts/build-dossier-devices.py tony-ha`: WS auth succeeded as
`svc-chaba-scripts` but `lovelace/config/save` returned
`{code: unauthorized}`. Root cause: the 2026-10-27 owner-LLAT revocation
(`ha-owner-llat-co-use-split`) minted `svc-chaba-scripts` into HA group
`system-users` (non-admin), but its lanes' job — pushing the Dossier
Devices view — is admin-gated. REST `/api/` and `auth/current_user` kept
working, so the failure only surfaced at the save step.

## What I changed (live, on tony-omen)

Promoted the `svc-chaba-scripts` **user** to admin via the HA websocket
API — no restart, no `.storage` hand-edit:

- `config/auth/update {user_id: 5edf6625…, group_ids: ["system-admin"]}`
  on `ws://127.0.0.1:8123/api/websocket`, authenticated with the
  `telemetry-ha-push.env` LLAT (verified `is_owner/is_admin` = Tony).
- HA 2026.8.3 admin model verified in-container: `is_admin` = owner OR
  member of `system-admin`; `user.groups` assignment invalidates the
  cached `is_admin`, and the auth store persists to `.storage/auth`
  immediately (confirmed on disk).

Scope: one HA user → all four per-host LLATs (`scripts-omen/dell/idc03/
mn01` in `home-assistant-token.env`) inherit admin. `svc-ada`,
`svc-nodered`, `svc-chaba-guest`, `svc-chaba` remain non-admin. Chose
user promotion over swapping an owner LLAT into the token files — keeps
per-consumer attribution and per-lane revocability, doesn't spread owner
creds.

## Verified (done-condition)

- `auth/current_user` as svc-chaba-scripts → `admin=True`.
- `ssh tony-dell; ~/CascadeProjects/chaba/venv/bin/python3
  scripts/build-dossier-devices.py tony-ha` →
  `Pushed tony-ha Devices view (50 rows for tony-ha)` — the exact
  lovelace/config/save path that was failing now succeeds.

## Repo changes (this worktree, uncommitted for dispatcher merge)

- `docs/ssot/jobs/home-assistant/2026-11-25-svc-chaba-scripts-admin-promotion.yml`
  — trail/runbook doc (new).
- `docs/ssot/infrastructure/ssot.secrets.yml` — `ha-tony-token-ops` note
  updated: svc-chaba-scripts is admin since 2026-11-25.
- `docs/kb/ha-ada-isolation.md` — annotated the "non-admin svc token"
  claim with the svc-chaba-scripts exception.

## Notes / follow-ups

- `scripts/ada/ha-svc-user.py` has no promote/group flag — it always
  provisions `system-users`; fine for ada lanes, wrong default for
  script lanes that push lovelace config.
- If HA ever gains per-dashboard ACLs, svc-chaba-scripts can be scoped
  back to `system-users`.

lessons:
- HA WS `config/auth/update` accepts `group_ids` and flips `is_admin` live (cache invalidated via User.groups on_setattr) — no restart, persists to .storage/auth.
- Admin groups on tony-ha: `system-admin` / `system-users` / `system-read-only`; `is_admin` = owner OR system-admin member (auth/models.py).
- `lovelace/config/save` is `@require_admin` — svc (system-users) tokens auth_ok but get `{code: unauthorized}` only at the save step; REST /api/ stays 200, which masks the problem.
- On tony-omen, tony-ha runs host-network in rootless podman; `ws://127.0.0.1:8123/api/websocket` + system python3 (websockets 15.0.1) is enough for auth surgery — no venv needed.
- `telemetry-ha-push.env` HA_LONG_LIVED_TOKEN on omen is a Tony owner/admin LLAT — usable for admin WS calls when no admin env slot exists.
