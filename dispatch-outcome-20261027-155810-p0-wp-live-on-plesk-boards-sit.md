# dispatch-outcome — line-wp-site-manager, execute "proceed" (2026-10-27, 2nd dispatch)

## What this session was for

The 14:02 dispatch completed P0 verification and staged the P2/P3
ada-voice drops (wp_read/wp_update), then raised the spec's open Q.
Tony answered **"proceed"** (15:37) to the default proposal —
*dedicated LINE group per customer-site, existing tony/kk-style lane
pattern, per-site `wp-<customer>.env` app password (Option A identity
map)* — and the answer-sweep re-queued the card. This session executed
that answer: the proposal is now codified as the onboarding standard.

## What changed

- `docs/ssot/apps/ssot.wp-boards.yml` — new `sites:` registry (boards
  entry + commented customer template) and `customer_onboarding:`
  section recording the approved model, the env-binding isolation
  argument, and the customer lane shape (ada-kk clone, no ha_upstream,
  member-site tool set).
- `docs/kb/wp-customer-site-onboarding.md` — NEW runbook: WP/Plesk
  setup → app-password mint → 0600 env file → lane clone → LINE group
  wiring (LINE_ALLOWED_GROUP_IDS / LINE_GROUP_PERSONA /
  LINE_NAME_BACKENDS / LINE_USER_CALLERS) → consumer-surface verify.
- `scripts/wp-boards/site-preflight.py` — NEW onboarding verifier
  (stdlib-only, mirrors the scripts/ada WP-writer env contract):
  front-page + redirect-loop check, REST index with `/wp-json/` →
  `index.php?rest_route=` fallback detection, anon `/wp/v2/users`
  enumeration warning, unauth `users/me` 401 gate, `--env-file`
  authenticated round-trip, `--write-env` writes a 0600 env file
  without echoing the password.
- `docs/ssot/apps/ssot.line-groups.yml` — notes: customer-group
  convention (dedicated group per site, persona hard-pin, callers
  entry, pointer to runbook).
- `docs/ssot/infrastructure/ssot.secrets.yml` — NEW entry
  `wp-boards-app-password`: registers the previously-unregistered
  wp-boards.env (slots + consumers incl. lane envs, wp-* timers,
  board-api, wp-cam-snapshot on tony-omen) and declares the
  `wp-<slug>.env` per-site convention + rotation steps.
- `docs/ssot/jobs/ada/2026-10-27-wp-customer-site-lanes.yml` — NEW
  decision doc: approved model, rejected alternatives (shared lane +
  site param, split creds, chat-delivered passwords), artifacts,
  verification.

## Key design point

Isolation is structural, not a filter: `backend/wp_client` resolves
`WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD` from the lane's process env,
and no wp tool accepts a `site` parameter — a customer lane cannot be
aimed at another site's credentials. One dedicated lane instance per
customer site; per-site app password revocable in that site's wp-admin.

## Verification run

- `site-preflight.py https://boards.surf-thailand.com/wp` → exit 0:
  front 200, REST 200 "Chaba web boards" 219 routes, unauth
  users/me 401, anon-enumeration warn (expected WP default).
- `index.php?rest_route=` fallback exercised directly → 200, 31 types.
- `yaml.safe_load` on all four edited/created YAMLs + full
  `scripts/ssot-validate-refs.py` → 3177 files, no broken refs.
- `py_compile` on the new script.

## Status vs task list

- P0 live + REST reachable — re-verified ✅
- P1 app password — settled 2026-10-14 (wp-boards.env on idc03); the
  per-site mint step is now runbook + secrets-registry standardized ✅
- P2/P3 tools — staged + merged by the prior dispatch; **still await
  drop-apply + deploy-ada.sh on idc03** (can't deploy from this
  worktree)
- Open Q — answered "proceed", implemented as the standard above ✅

## How to verify

- `python3 scripts/wp-boards/site-preflight.py https://boards.surf-thailand.com/wp` → exit 0
- `python3 scripts/ssot-validate-refs.py` → no broken refs
- Read: `docs/kb/wp-customer-site-onboarding.md`,
  `ssot.wp-boards.yml` `sites:`/`customer_onboarding:` sections
- On next real customer: run the runbook checklist end-to-end; after
  idc03 deploy, kk lane "what is on my site" → wp_read list.
