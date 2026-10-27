# ha-owner-llat-co-use-split — outcome (2026-10-27)

## Result: DONE — all consumer envs on dedicated non-admin svc tokens; all owner LLATs revoked.

## What the live audit found (differed from card premise)

- tony-ha, node-red, chaba-guest, ha-live all live on **tony-omen** since the
  LAN-cohort migration — the card's "tony-dell" references were stale.
- Not one but **three distinct Tony OWNER tokens** were sitting in the slots:
  - `fp 8d1a7d29a3` — the shared Ada-era LLAT (`client_name=tony-ha`):
    omen {chaba-guest.env, nodered-ha.env}, dell {all three envs + ada-pi-pwa.env},
    mn01 {ada-ha-tony.env}, idc03 {5× .bak envs only}
  - `fp 6e6553888f` — omen home-assistant-token.env (already dead by revoke time;
    was likely a short-lived token)
  - `fp 0362b97704` — `client_name=tony-devin` LLAT: idc03 + mn01
    home-assistant-token.env (all the script consumers)

## Actions

1. Provisioned on tony-ha via `scripts/ada/ha-svc-user.py` (run on tony-omen,
   system python3 has websockets; owner-A used as admin until last):
   - `svc-chaba-guest` (new, non-admin) → lane `chaba-guest`
   - `svc-nodered` (new, non-admin) → lanes `nodered-omen`, `nodered-dell`
   - `svc-chaba-scripts` (new, non-admin) → lanes `scripts-{omen,dell,idc03,mn01}`
   - `svc-ada` (existing) → standby lanes `ada-ha-tony-standby`, `ada-pi-pwa-standby`
2. Rewrote 9 env slots across omen/dell/idc03/mn01 (timestamped `.bak-*` kept;
   dead owner strings only). Every slot WS-verified `auth/current_user` →
   `is_admin=false`, `is_owner=false`.
3. Restarted consumers: node-red on omen+dell (`:1880` → 200); started
   `chaba-guest` on omen (enabled+active, `:8014` → 200 — declared
   expected-active, had never been started since migration); started `ha-live`
   (active, `:8444` serve up). `chaba-guest-lan` left inactive — SSOT says
   staged. idc03/mn01 consumers are per-invocation scripts — no restart needed.
4. Revoked owner LLATs via `auth/refresh_tokens` → `auth/delete_refresh_token`
   on the `is_current` `long_lived_access_token` entry:
   - owner-A id `2f8ec4b6…` (`tony-ha`) — deleted, verified 401
   - owner-C id `b8e6ad92…` (`tony-devin`) — deleted, verified 401
   - owner-B — already invalid (no live refresh entry needed deleting)
5. **Casualty fixed**: `ha-auth-watch.py` uses admin-gated `system_log/list` —
   broke under the non-admin scripts token. Patched to fall back to the
   `http-login` persistent notification (verified non-admin-readable; already
   contains the invalid-auth text). Live copy synced to dell, `--dry-run`
   passes (polls both instances, 0 errors). Committed in worktree.

## Repo changes (commit 08fef2f9b on dispatch branch)

- `scripts/audits/ha-auth-watch.py` — PN fallback for non-admin tokens
- `docs/kb/ha-ada-isolation.md` — Phase B revoke done, owner-token bullet + what-if updated
- `docs/ssot/infrastructure/ssot.secrets.yml` — `ha-tony-token-ops` slots now list per-host svc client_names
- `docs/ssot/infrastructure/ssot.home-assistant.lanes.yml` — tony-dev twin note

## Verify

- `curl http://127.0.0.1:8123/api/` on omen: unauth→401 (alive), svc token→200, old owner tokens→401
- `systemctl --user is-active {node-red,chaba-guest,ha-live,tony-ha}` on omen → active
- WS `auth/current_user` per slot → `svc-*`, `is_admin=false`
- HA logbook now attributes calls to `svc-chaba-*` / `svc-nodered` / `svc-ada`

## Notes / leftovers

- `.bak-*` env files on hosts contain the dead owner strings (inert, 0600).
- dell's `node-red` HA_URL still points at `http://tony-dell:8123` (dead since
  migration) — pre-existing; token swap makes it harmless either way.
- `ha-auth-watch` on dell: repo change must merge for the exec checkout to
  converge; the live-patched copy is identical so safe-pull reconciles cleanly.
