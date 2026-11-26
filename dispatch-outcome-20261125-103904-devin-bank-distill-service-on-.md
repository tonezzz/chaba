# Dispatch outcome — devin-bank-distill-oauth-token-type

## What was found

The card's premise was wrong in an interesting way: this was **not** an
OAuth token-type/scope problem. `devin-bank-distill.service` on tony-omen
was a **stale duplicate** — the canonical job lives on con01
(`ssot.jobs.yml`, migrated dell→idc02→con01; `ssot.automation.yml` already
called the omen copy a "STALE DUPLICATE still firing"). Its
`EnvironmentFile=~/.config/secrets/ada-pi-pwa.env` (dated 2026-09-21)
held a dead Gemini API key (`AQ.Ab8RN6KKS…`). Google answers a revoked
`AQ.*` key with HTTP 401 `ACCESS_TOKEN_TYPE_UNSUPPORTED` — reproduced
verbatim with a one-shot `generateContent` probe.

Blast radius was bigger than the card: the same env file feeds omen's
**live** `ada-memory-rollup.timer` (nightly), which was failing with the
identical 401 every night. `ada-pi-pwa.service` (dead unit) and the dead
`yomi-api` override.conf held the same dead key family.

## What was changed (live on hosts)

- **tony-omen**: rotated `GEMINI_API_KEY` in `ada-pi-pwa.env` to the local
  `ada-paid` key value (verified HTTP 200 before/after; backup at
  `ada-pi-pwa.env.bak-20261125-distill`, mode 600 kept). Removed stale
  `devin-bank-distill.{service,timer}` (disable --now, rm, daemon-reload).
- **tony-dell**: removed the same dead unit files (timer was already
  disabled; they referenced an older `gemini-api-key.env`).
- Verified fleet-wide: only con01 retains `devin-bank-distill.timer`
  (canonical, healthy — last run 2026-11-22 distilled a week).

## Verification

- Post-fix `systemctl --user start ada-memory-rollup.service` on omen:
  `Result=success`, **0** auth failures, 35 rollup docs written
  (weekly/monthly across 5 banks) — the periods that failed at 03:45
  were regenerated. This exercises the real `gemini_rest` code path.
- `list-timers | grep distill` on omen → 0; dell files gone; idc02 was
  already clean; idc03's match is the unrelated `ada-memory-distill`.

## Repo changes (commit c435b71238 on dispatch branch)

- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — moved
  `devin-bank-distill.timer` from `expected_services` to
  `expected_absent` on tony-dell AND tony-omen with shed notes.
- `docs/ssot/infrastructure/ssot.automation.yml` — updated the
  "STALE DUPLICATE" note to record the removal.
- `docs/ssot/infrastructure/ssot.secrets.yml` — `gemini-yomi` slots on
  omen annotated (dead yomi key; `ada-pi-pwa.env` rotated to ada-paid).
- `docs/ssot/jobs/infrastructure/2026-11-25-devin-bank-distill-omen-stale-dup-cleanup.yml`
  — full job trail.

## Follow-ups noted (not done — out of scope)

- The dead yomi free key (`AQ.Ab8RN6KKS…`) may be copied elsewhere —
  worth a fleet grep of secrets dirs for that prefix if yomi is revived.
- `ada-pi-pwa.service` on omen is dead weight (PWA moved; live path is
  `chaba-guest.service` on `chaba-guest.env`) — candidate for a future
  declared-or-dead sweep.

lessons:
- ACCESS_TOKEN_TYPE_UNSUPPORTED from generativelanguage.googleapis.com is Google-speak for "credential isn't a usable API key" — a revoked/rotated AQ.* key produces it, not just OAuth misuse. Probe the key with one curl before theorizing about token flows.
- Duplicate systemd units survive job migrations: ssot.jobs.yml said con01 but omen/dell copies kept firing — audit.hosts.yml expected_services entries were stale and helped perpetuate them. Check `systemctl --user list-timers` on EVERY host the audit manifest names, not just the canonical one.
- A single secrets file can feed multiple units with different criticality — the "stale duplicate" env file was also silently breaking a live nightly job (ada-memory-rollup). Map all consumers of a secrets file before rotating.
- `journalctl --user` on omen is volatile — last boot was ~1.5 days before inspection, so pre-reboot unit failures leave no logs; `systemctl --user list-timers` LAST timestamps + live repro beat journal archaeology.
