# Chaba Lab — evaluation platform for Ada

Date: 2026-09-27 · goal: stable, repeatable evaluation KK can test for real

## What exists now (live)

- **51 live scenarios** in `ada-pi/tests/scenarios-live/` covering memory,
  CMS, cast, devin ledger, speaker-ID, docs, persona, recall.
- **`scripts/scenario-report.py`** — suite runner; writes one doc per
  scenario into `ada-ha-scenario-reports` (never pollutes memory search),
  retries once and marks `flaky`, supports per-scenario keys/device/URL.
- **`scripts/ada/lab-results.py`** — renders latest per scenario → CMS
  page `lab-results` (status matrix: pass/flaky/fail, failed turns, time).
- **`ada-scenario-smoke.timer`** on idc01 — hourly `--tier smoke` run +
  auto-rerender of `lab-results`. (Nightly full run: add `OnCalendar` for
  `--tier full` when the suite settles — full takes ~30-60 min.)
- **Real-user flows**: `kk_first_contact`, `kk_info_probe`, plus a guest
  key path — KK can be handed an iPad and walked through the checklist
  while transcripts auto-evaluate.

## For KK — lab checklist

CMS page `lab-checklist` holds a fixed set of voice tasks (ask time/
flood status, remember a preference, publish a page, ask to recall it
next session, try an English question). Each session gets a transcript;
a `transcript_eval` pass grades tool-calls, answer correctness, and
language fidelity afterward — real-user signal without scripting her.

## Roadmap

1. Smoke timer live hourly — watch `lab-results` tomorrow for flakes.
2. Nightly `--tier full` + weekly trend digest to `chaba-home/report`.
3. `speaker:` session override so KK-scoped scenarios run in CI (today
   they need her voice).
4. Coverage matrix (mn01 job running): map tools→scenario coverage,
   auto-flag uncovered verbs.
5. Bench metrics: p50/p95 turn latency + tool-call count per scenario —
   the runner already logs them; surface on `lab-results`.

## How to use it day to day

- Before touching `backend/`: run smoke tier → `lab-results` green.
- New feature = new scenario first (TDD for voice behavior).
- KK test day: checklist page + record sessions + eval pass after.
