# Dispatch outcome — audit sequence_anomaly (AUD-0949)

Runner: tony-macbook. Card: audit-oc-sequence-anomaly-mzwpaubp. Read-only
audit; no push, no deploy, no card-state changes beyond a board-api comment.

## Verdict: CONFIRMED — true positive, low harm

Three OpenCode sessions labeled `s1-canary` ran on tony-macbook
2026-10-27 07:38:59–07:39:47 UTC — ~9 minutes before the lane's only
S0→S1 promote (07:48:47Z, committed in 851ff0c31 at 07:53Z). They were
informal pre-flight probes at the top of the lane-builder dispatch
(20261027-143512): raw `opencode run` in `/tmp/opencode-s1-canary.HWPjZB`,
never admitted by lane_gate (no envelope; the gate itself was uncommitted),
so they bypassed every S1 requirement (human watch, OPENCODE_LANES env,
concurrency marker, ledger record, durable artifact). Had they gone through
`admit` at S0 they would have denied `wrong_stage`.

Not a detector false positive: only one `promote_to: S1` review exists in
history (no map-overwrite); timestamps are UTC-vs-UTC; and the five
S0-labeled sessions in the same window were correctly NOT flagged.

Harm: none destructive — 0 tool denials, 0 mutations, writes confined to
each run's own /tmp report. But the runs were invisible to the lane ledger,
artifacts were ephemeral, and the storage-dry-run output carried unsafe
`automatic_ok` classifications on protected roots (AUD-0947). The lane's
real S1 evidence is the later gated profile canaries (runs/p1-*-idc02-*).

Host note: the card option said "chaba repo on tony-dell" — verified there:
dell's opencode.db (178 sessions) contains zero canary sessions; dell was
only the MCP probe target. Its exec checkout has lane_gate + the promotion
review but NOT opencode_session_audit.py — the AUD-0938 correction is still
open: the audit tool/tests/reports sit staged-uncommitted in worktree
`dispatch-wt-20261027-163705-build-a-read-only-opencode-ses` on tony-macbook
and should be landed before that worktree is pruned.

## Checks — all green

- `test_opencode_session_audit` 12/12 OK; `test_lane_gate` 43/43 OK
- opencode.db stage-label census, macbook (20) + dell (178): exactly the 3
  flagged S1 anomalies, none missed, none extra

## Artifacts

- `evals/opencode-lane/reports/2026-10-28-sequence-anomaly-audit.md` — full report
- `docs/ssot/jobs/devnest/2026-10-28-opencode-sequence-anomaly-audit.yml` — job doc
- Findings posted to the card via board-api /comment (done-condition met)

## Recommendations

1. Keep the detector unchanged — flag + human adjudication worked.
2. Pre-gate probes should use `pilot-`/`probe-` dir prefixes, never stage labels.
3. Land the audit tool durably (AUD-0938 carry-over).
