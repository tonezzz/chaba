# Dispatch outcome — ada-proactive-digest-morning-brief-via-t-3abb02

## What changed

- `scripts/ada/morning-brief.py` (new, executable) — gathers education
  due lessons (board-api `/lesson` `op:list source:wiki`, reusing
  `lessons-due.py` fetch_rows/bucket_rows so the bucket rule can't
  drift), open card `requests:`, 24h dispatch outcomes (host-local
  devin-dispatch ledger, card-side `action.status`+`updated` fallback),
  and red health flags (reports/system-report.yml +
  ~/var/chaba/health/meta.yml). Renders a ≤9-line `[ada] morning brief`
  and POSTs `{text}` to `http://127.0.0.1:8911/send` (ada-tg-relay →
  Tony DM — loopback contract, no creds in the script). `--print`
  renders without sending; `MB_SEND_URL`/`MB_CHAT_ID`/`BRIEF_PAGE_URL`
  env overrides.
- `docs/ssot/infrastructure/ssot.jobs.yml` — declared
  `ada-morning-brief` systemd job: host idc03, `*-*-* 07:35:00` (after
  daily-brief 07:05+narration and lessons-due 07:30), 2m timeout.
- `docs/ssot/jobs/ada/2026-11-20-ada-morning-brief.yml` — job trail doc.

## Result / verification

- `python3 scripts/ada/morning-brief.py --print` run live on tony-omen:
  real data rendered — 159 education due (top 3 named +"+156"), 4 open
  requests, 4 done / 3 failed dispatches from the local ledger, no
  health flags.
- Both new/changed YAML files pass repo SSOT validation (pre-commit
  gate green; commit bffb5dcdab on this branch).
- NOT verified: the actual /send POST — :8911 is loopback on idc03
  only, so a real send requires running on idc03.

## Deploy steps remaining (need Tony approval / merge first)

1. Merge this branch to master; let idc03's exec checkout sync
   (chaba-repo-sync.timer).
2. `scripts/render-jobs.py --host idc03 --install` to materialize
   `ada-morning-brief.timer`.
3. Optional smoke on idc03: `morning-brief.py --print`, then one manual
   send before the 07:35 fire.

lessons:
- card `updated` is bumped by board sweeps — action.status+updated is a
  bad proxy for "dispatch finished in window"; read the devin-dispatch
  ledger meta.json finished_at instead.
- ada-tg-relay /send (:8911) is loopback-only — --print from a
  satellite host verifies everything except the final POST.
- Prior failure on this card was runner-side (service exit=1 in ~3s,
  agent never ran) — not a code defect; no prior branch carried work.
