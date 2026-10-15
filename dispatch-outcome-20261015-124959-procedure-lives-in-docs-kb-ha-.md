# ha-ada-isolation — Phase A + Phase B (tony-ha) executed

Card: `ha-ada-isolation` (HOM-0464). Runner idc02. Runbook `docs/kb/ha-ada-isolation.md` updated; live posture CMS index `ha-ada-isolation` now shows **5/6 PASS**.

## What was done

**Phase A (idc03, safe)**
- `~/.config/systemd/user/<unit>.service.d/isolation.conf` on all 10 ada units — `MemoryMax=2G`, `CPUQuota=150%` (200% for `ada-bankq-student`), `LogRateLimitIntervalSec=30s`/`LogRateLimitBurst=1000`. Verified effective via `systemctl show`; all units active, health ports 200.
- `scripts/deploy-ada.sh` idc03 SERVICES reordered to the documented canary ladder (dev → relays → member → tony last) and extended with `ada-kk-dev` (:8009) and `ada-tg-relay-kk` — same "fresh code" rationale Tony approved for ada-kk.
- Gemini keys confirmed pool-isolated (4 pools, no cross-pool sharing) — approved "two pools" standard met.

**Phase B (tony-ha — approved 2026-10-11)**
- `svc-ada` non-admin user created on tony-ha (id `84e7b655f47d49cea47340e946590114`) via new tool `scripts/ada/ha-svc-user.py` (WS `config/auth/create` + `config/auth_provider/homeassistant/create`, OAuth login flow, `auth/long_lived_access_token` per lane).
- `HOME_ASSISTANT_TOKEN` swapped in `ada-ha-tony.env` + `ada-pi-pwa.env` (backups kept: `*.bak-svcada-<ts>`); units restarted; `auth/current_user` verifies `svc-ada`, `is_owner=false`, `is_admin=false`.

**Phase C (verified)**
- Stopped `ada-ha-tony` + `ada-pi-pwa`: tony-ha `/api/` answered 401 throughout (alive, auth required); michael-ha likewise. Services restarted clean.

## Repo changes (committed on dispatch branch, not pushed)

- `docs/kb/ha-ada-isolation.md` — refreshed: new coupling map (svc-ada creds, ada-kk-dev row), checklist marked, phases annotated.
- `scripts/ada/ha-svc-user.py` — new reusable Phase-B tool (michael-ha repeat is one command).
- `scripts/ada/ha-ada-isolation-cms.py` — fixed drift: DEPLOY_SH path, SERVICES parser for `host_config()`, BACKENDS gains ada-kk-dev + pwa→tony-ha, pool-aware Gemini check, empty-key hash artifact.
- `scripts/deploy-ada.sh`, `docs/ssot/infrastructure/ssot.services.yml`, job record `docs/ssot/jobs/home-assistant/2026-10-15-ha-ada-isolation-phase-ab.yml`.

## Blocked / pending Tony

- **michael-ha Phase B** — approval request raised on the card (`phase-b-on-michael-ha-approve-creating-s-89770d`, recommended approve). Procedure proven, one command via `ha-svc-user.py`.
- **Old owner LLAT revoke — deferred**: the same token is still used by `chaba-guest.env`, `nodered-ha.env`, `home-assistant-token.env` on tony-dell (new finding). Follow-up card `ha-owner-llat-co-use-split` (HOM-0705) created.
- **kk Live-layer Gemini key** — Tony GCP mint, tracked on `kk-gemini-key`.

## Verify

- `ssh idc03 'systemctl --user show ada-ha-tony -p MemoryMax -p CPUQuotaPerSecUSec'` → 2G / 1.5s.
- CMS `ha-ada-isolation` index: 5/6 PASS (fail = michael owner token, by design until approved).
- `ssh idc03 '~/CascadeProjects/ada-voice/.venv/bin/python /tmp/ha-svc-user.py verify --ha-url https://tony-dell.taila0626a.ts.net:8123 --env ~/.config/secrets/ada-ha-tony.env'` → `svc-ada`, non-admin (note: /tmp copy was removed post-run — re-scp `scripts/ada/ha-svc-user.py` if needed).
