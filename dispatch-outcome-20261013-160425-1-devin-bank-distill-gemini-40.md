# Dispatch outcome — fix-idc02-timer-pack (2026-10-13)

Runner: idc02 (session ran on the target host itself)

## 1. devin-bank-distill — Gemini 401 (FIXED + verified)

**Root cause:** the unit loaded `EnvironmentFile=~/.config/secrets/gemini-api-key.env`,
which still held a pre-persona-split shared key (suffix …jjmw) that now returns
401 Unauthorized — every chunk of weeks 2026W37–W40 failed on 2026-10-11.

**Fix applied:**
- Provisioned `~/.config/secrets/chaba-paid.env` on idc02 (`GEMINI_API_KEY=` env
  format, mode 600) copied from the canonical raw-key file on idc03 — the
  `gemini-tony-paid` persona key, correct billing lane for a chaba repo job.
- `ssot.jobs.yml`: `devin-bank-distill.env_file` repointed to `chaba-paid.env`;
  re-rendered `systemd/generated/idc02/devin-bank-distill.service` via
  `scripts/render-jobs.py --host idc02` and installed to
  `~/.config/systemd/user/` + daemon-reload.
- Legacy `gemini-api-key.env` replaced with a symlink → `chaba-paid.env` so
  fallback consumers (e.g. `scripts/micro-bench/providers.py`) heal too.
- `ssot.secrets.yml`: idc02 slots + consumer recorded under `gemini-tony-paid`.

**Verification:** direct probe of the key on `gemini-3.5-flash-lite` → HTTP 200
(model name confirmed valid). `systemctl --user start devin-bank-distill.service`
→ exit 0 in ~90s; all 4 backlog weeks (W37–W40) plus W41 distilled, every chunk
succeeded, session docs marked superseded.

## 2. chaba-audit-full — findings already fixed, verified green

The 2026-10-04 monthly run failed on three error-severity audits. All were
fixed same-day in commit `35c0cb1a`:
- `standardization`: duplicate audit name `cms-pages` → renamed `cms-pages-live`.
- `caddy`: no host caddy binary on idc02 → podman `caddy:2` fallback added.
- `security-audit`: `docker: command not found` → docker|podman runtime pick;
  the "Google Drive not mounted" critical is now correctly skipped on non-backup
  hosts (idc02 has no rclone/gdrive remote).

**Verification now:** re-ran `caddy`, `standardization`, and `security-audit`
individually — all pass; then a fresh `node scripts/audits/run.mjs --full` on
idc02 → **all audits passed**, 5 warning-severity findings only
(security-posture, cms-pages, code-quality, dev-system, staleness — ongoing
known warnings, not exit-code failures). New summary.json written by the run.

## Board actions

- `timer-alert-idc02-devin-bank-distill` → evidence comment + closed.
- `timer-alert-idc02-chaba-audit-full` → evidence comment + closed.
- `fix-idc02-timer-pack` → progress + wrap-up comments.

## Observation (not actioned)

`~/.config/secrets/ada-lab.env` on idc02 carries yet another Gemini key
(suffix …nT0A) that currently probes HTTP 429 (quota-limited, not dead).
`ada-lab.service` is active and shows no Gemini-related errors in 24h — likely
rides gateway/fallbacks. Left untouched; flagging in case Tony wants the lab
lane on a persona key too.

## Commit

`3217764c` on `dispatch/20261013-160425-1-devin-bank-distill-gemini-40`
(3 files: ssot.jobs.yml, ssot.secrets.yml, generated service). Not pushed —
dispatch rule.

## How to verify

- `systemctl --user status devin-bank-distill.service` on idc02 → last run
  2026-10-13 16:14, `status=0/SUCCESS`; journal shows all chunks done.
- `grep EnvironmentFile ~/.config/systemd/user/devin-bank-distill.service`
  → `chaba-paid.env`.
- `~/CascadeProjects/chaba/reports/audits/summary.json` → `failed: 0`
  (fresh 2026-10-13 --full run); both timers' next scheduled runs should be
  green (distill Sun 10:15, audit-full Nov 1 03:00).
