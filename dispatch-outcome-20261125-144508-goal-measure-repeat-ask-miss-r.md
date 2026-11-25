# Dispatch outcome — session-capture-d1-metrics (attempt 3, verify-only)

## Result

All card deliverables were already landed on origin/master by salvage commit
`566ed29e07` ("OPS-1368: capture Phase D follow-ups + recover d1-metrics
artifacts"). Attempt 2 (mn01, 12:27) verified them and merge-sweep auto-closed
the card at 12:39; Tony's 14:03 VERIFY-QUEUE triage held it back again on a
stale "no committed deliverable" note, and this retry (tony-omen, 14:45)
re-verified. This session made **no code changes** — the worktree is clean.

## Verified deliverables (all committed, `git ls-files` confirmed)

- `reports/capture/metrics-20261125.md` — read-only metrics report:
  repeat-ask 15 asks / 13.12 per week / register 34d stale (last `at:`
  2026-10-22); miss rate 0 since 2026-11-23 instrumentation; stale-pointer
  proxy 35 candidates >30d (oc-note 32, ssot 3); time-to-find 3 real
  info_find.py samples, median 1647ms; matrix precision 100% on regenerated
  ledger. Measured vs proxy labels are explicit — no fake events.
- `docs/ssot/jobs/kanban/2026-11-25-session-capture-d1-metrics.yml` — job doc
  with goal, artifacts, verify commands, no-fake-events posture.
- `docs/ssot/ssot.knowledge-capture.yml` — "Phase D Refresh (2026-11-25)"
  section recording measured values, the ledger-durability gap, and tuning
  thresholds (repeat-ask >14d stale, misses/week >2, pointer candidates >30,
  time-to-find median >5000ms or resolved <80% over >=20 runs, matrix
  precision <90% over >=50 creates).
- Follow-ups resolved under `session-capture-d-1-follow-ups-ledger-du-78e13f`
  (done): canonical ledger durable home = idc02
  `~/.local/share/chaba/capture/` + daily `chaba-capture-harvest`;
  `pointer-stale-add.py` wired into sweep + info-find skills.

## Acceptance check

- Read-only report: yes — metrics report + job doc only.
- SSOT thresholds/tuning: yes — Phase D Refresh section in
  ssot.knowledge-capture.yml.
- No fake events: yes — proxy/measured labels explicit; time-to-find samples
  are real `info_find.py run` invocations.

## Register-freshness observation (per sweep-duty rule)

`ssot.repeat-ask.yml` newest `history[].at` = 2026-10-22 → 34d stale (>14d
threshold). Cannot determine from this host whether Tony genuinely had zero
repeat-asks or the increment path is a capture gap; the question is already
covered by the recorded threshold ("sweep duty re-checks register freshness")
and the resolved D.1 follow-ups card, so no new card filed — flagged here for
the next sweep to adjudicate.

## How to verify

```
git log --oneline -1 566ed29e07
grep -n "Phase D Refresh" docs/ssot/ssot.knowledge-capture.yml
sed -n '1,20p' reports/capture/metrics-20261125.md
python3 -c "import yaml; yaml.safe_load(open('docs/ssot/ssot.repeat-asks.yml'))"
```

lessons:
- VERIFY-QUEUE triage can re-hold an already-merged card on a stale "no committed deliverable" note — before redoing work, check `git log origin/master -- <expected artifact paths>` and prior card comms for a salvage/merge-sweep close.
- `reports/*` is gitignored in chaba; report deliverables need explicit force-add — verify with `git ls-files`, not just file existence.
