# Per-instance secret stores migration — outcome

Card: `per-instance-secret-stores-migration`. Full trail: `docs/ssot/jobs/ada/2026-10-23-per-instance-secret-stores.yml`.

## What changed

**Lane stores on idc03 (`~/.config/secrets/<lane>/{backend.env,keys.json}`):**
- `tony-ha/` — from `ada-ha-tony.env` + `ada-ha-tony-keys.json`; fresh admin minted; `ADA_KEYS_FILE` pinned; `ada-ha-tony.service` + tg/line relays + 8 scenario/memory/health units repointed; :8002 verified (`/api/auth/keys` → caller=admin, 42 keys incl. cms-viewer, user-guest, screen-*)
- `michael-ha/` — from `ada-ai-kraut.env` + `ada-ai-kraut-keys.json` (the renamed ada-ha-michael lane); fresh admin; `ada-ai-kraut.service` + `ada-tg-relay-mn` + `telegram-mn-bot.env` updated; :8003 verified
- `kk-ha/` — from `ada-kk.env` + `ada-ha-kk-keys.json`; existing unique admin kept; `ada-kk.service` + `ada-tg-relay-kk` + `telegram-kk-bot.env` updated; :8007 verified
- `ada-ha/` — NEW lane `ada-ha-ada.service` on :8006 (env cloned from ada-dev + ada-ha HA token for tony-omen:8125, fresh keys, empty keyring); tailnet route `/apps/ha/ada-ha` added
- Dev lanes `ada-dev`/`ada-kk-dev` got fresh unique admins — the old shared admin value is live nowhere on idc03

**:8001 retired** — after repointing every consumer: input-bridge `ADA_AUTH_URL`→:8002 + `ADA_ADMIN_KEY`→tony admin; `line-bot.env` `ada:`→:8002; idc02 caddy-edge `/cms*`+`/api/cms*`→`/apps/ha/ada-tony{uri}`; idc02 `vcast-real.env` admin key (all 3 displays re-claimed); idc03 caddy-edge `api.surf-thailand.com`+sslip catch-alls→:8002; tailscale serve `/`→:8002. Then `stop`+`disable ada-pi-pwa.service`; :8001 closed; post-checks 200 on root, /cms, /api/auth/keys, api.surf-thailand.com, LINE delivering, vcast screens registered.

**household.yml** — schema defined in new `docs/ssot/infrastructure/ssot.household.yml`; seeded on all 4 nodes (tony-ha & ada-ha on omen, kk-ha on idc03, michael-ha at `/homeassistant/household.yml`).

**mn01 standby** — admin values rotated to new per-lane values; keys.json copies synced.

**gemini-tier** (idc03 `~/.local/bin`) — now scans `*/backend.env`, maps lane stores to persona keys, SERVICES updated (ada-ha-michael→ada-ai-kraut, −ada-pi-pwa, +ada-ha-ada).

**SSOT** — secrets slots rewritten (no more `legacy_to_migrate`/`state: planned`), instances statuses→active, routes updated, ada-pi-pwa stack marked retired, new `ssot.household.yml`.

## Deviations from card text
- "ada-ha-michael.*" → actual files were `ada-ai-kraut.*` (grand-rename 2026-10-16); handled accordingly
- ada-ha store placed on idc03 (where backends run), not tony-dell as the planned slot said — SSOT corrected
- michael-ha household path is `/homeassistant/` (HAOS), not `~/.homeassistant/`

## Verify
```
ssh idc03 'ls ~/.config/secrets/{tony-ha,michael-ha,kk-ha,ada-ha}; systemctl --user is-active ada-pi-pwa'  # inactive
curl -s -o /dev/null -w '%{http_code}' https://idc03.taila0626a.ts.net/          # 200 via :8002
curl -s -o /dev/null -w '%{http_code}' https://api.surf-thailand.com/            # 200 via :8002
```

## Follow-ups
- ~19 chaba repo scripts still reference flat env paths (deploy-ada.sh, sync-ada-state.sh, key-watch.py, rotate-ada-secrets.sh, secrets-inventory-cms.py …) — need a follow-up pass
- idc01 was unreachable — its standby ada-pi-pwa/input-bridge copies still carry :8001-era config
- Old shared admin survives only in `_attic-20261023/` + `.bak` files (inert)
