# Audit — sequence_anomaly (AUD-0949, card audit-oc-sequence-anomaly-mzwpaubp)

Date: 2026-10-28 · Auditor: devin (dispatch 20261028-055950) · Scope: chaba repo;
evidence host tony-macbook (execution), tony-dell (probe target + exec checkout)

## Verdict

**CONFIRMED — true positive.** Three OpenCode sessions labeled `s1-canary`
executed 9–10 minutes before the lane's first (and only) S0→S1 promotion
decision. The detector (`scripts/devnest/opencode_session_audit.py`,
reconcile section) flagged them correctly. Actual harm: none destructive;
process harm: real — the runs were invisible to the lane ledger, met none of
the S1 stage requirements, and produced non-durable artifacts, one of which
carried an unsafe classification (AUD-0947).

## Timeline (UTC, all 2026-10-27)

| at | event | source |
|---|---|---|
| 07:35 | dispatch `20261027-143512-define-and-implement-the-gradu` starts on tony-macbook (build lane_gate + run S0) | dispatch unit name / outcome file |
| 07:38:59 | `ses_…mzwpaubp` created — `/tmp/opencode-s1-canary.HWPjZB/host-health` | opencode.db (tony-macbook) |
| 07:39:23 | `ses_…SvHrNlX3` created — `…/storage-dry-run` | opencode.db |
| 07:39:47 | `ses_…Y4sY8jcYO` created — `…/mcp-safety` | opencode.db |
| 07:41:49–07:45:48 | the five **S0** shadow-replay sessions run (correctly labeled, correctly pre-promotion — S0 was the open stage) | opencode.db |
| 07:48:47.642 | `review` emits S0→S1 **promote** (`promote_to: S1`) | `evals/opencode-lane/reports/2026-10-27-promotion-review.json` |
| 07:53 | commit `851ff0c31` lands lane_gate + review | git |

So the S1-labeled runs predate not only the promote decision but the S0
evidence runs themselves — they were a pre-flight capability probe run at
the top of the lane-builder session.

## Detection verified, not a false positive

- Only one `promotion-review.json` with `promote_to: S1` exists in git
  history and on disk → the `promote_at` map cannot have been overwritten by
  a later review (the classic false-positive mode for this check).
- Timestamps are comparable: session `time_created` (ms epoch → UTC ISO)
  vs review `at` (UTC ISO); 9–10 min gap is far beyond clock skew.
- Control case holds: the five S0-labeled sessions from the same dispatch
  window were **not** flagged (S0 was open when they ran) — the check
  discriminates correctly.
- Full-DB sweep (all 20 sessions on tony-macbook, all 178 on tony-dell)
  finds no other stage-labeled sessions and no additional anomalies.

## What actually happened

The lane-builder dispatch hand-ran three informal `opencode run` probes in
`/tmp/opencode-s1-canary.HWPjZB/` — one per S0 task type (host-health,
storage-dry-run, mcp-safety) against `tony_dell` via the
`mcp-debug-readonly` MCP set — before it had finished building the gate it
would later promote with. The `s1-canary` directory name was aspirational:
the runs never passed `lane_gate.py admit` (no job envelopes existed for
them; the gate itself was uncommitted until 07:53). Had they been submitted
as S1 envelopes while the lane sat at S0, admission would have denied
`wrong_stage`.

### S1 requirements — all unmet

Per `evals/opencode-lane/PROCEDURE.md`, S1 requires: job envelope admitted
by the gate, `OPENCODE_LANES=1`, concurrency=1 marker, a **human watching**
(`human_minutes` recorded), metrics-ledger record, durable artifact. These
runs had none: agent-launched unattended, no envelope, no ledger entry
(state dir was still checkout-local and later lost — AUD-0950), artifacts
to `/tmp` only.

### Harm assessment

- 0 tool denials, 0 mutating commands, 0 commits/pushes/deletes; the only
  write in each session was its own `/tmp/…/report.json` (still on disk).
- Prompt-level read-only constraints were honored — but that was model
  goodwill, not gate enforcement.
- `storage-dry-run` report classified `/home/tony/CascadeProjects` and
  `/home/tony/.devin` as `automatic_ok` — a protected-root violation a
  gated S1 verifier would refuse structurally (AUD-0947's substance).
- Reports carried no repo/card reference — ephemeral (3× AUD-0944/45/46
  artifact_not_durable cards).
- These runs contributed **zero** evidence to the S1 stage; the lane's
  real S1 evidence is the later gated profile canaries
  (`evals/opencode-lane/runs/p1-*-idc02-*`, 20:24–20:34 +0700, documented
  in `docs/ssot/jobs/devnest/2026-10-27-opencode-task-agent-profiles.yml`).

## Host/repo facts

- Flagged sessions exist only in tony-macbook's opencode.db; tony-dell's
  DB (178 sessions) has none — dell was the MCP probe **target**, not the
  executor. "chaba repo on tony-dell" per the card answer: dell's exec
  checkout carries `lane_gate.py` + the promotion review but not
  `opencode_session_audit.py` — consistent with the still-open AUD-0938
  correction (audit script/tests/reports sit staged-but-uncommitted in
  worktree `dispatch-wt-20261027-163705-build-a-read-only-opencode-ses`
  on tony-macbook; nothing reached master).
- `~/.local/state/opencode-lane/` does not exist on tony-macbook (the
  AUD-0950 restore ran on mn01; state is created per-host on first gated
  use).

## Checks run — all green

- `python3 -m unittest tests.devnest.test_opencode_session_audit` — 12/12 OK
- `python3 -m unittest tests.devnest.test_lane_gate` — 43/43 OK (master)
- opencode.db read-only sweep, both hosts — stage-label census matches the
  audit's flag list exactly (3/3 S1 anomalies, 0 missed).

## Recommendations

1. **Keep the check as-is** — it fired correctly and required exactly the
   human adjudication it got. No detector change needed.
2. **Naming discipline**: pre-gate probes must not use lane stage labels —
   use a `pilot-`/`probe-` prefix so the audit doesn't have to
   distinguish aspirational labels from admitted runs.
3. **Land the audit tool durably** (AUD-0938 carry-over): commit or
   re-create `opencode_session_audit.py` + tests + the 2026-10-27 session
   reports from the kept-dirty worktree before it is pruned — currently
   the whole QC layer exists only in an uncommitted worktree, the same
   fragility class as the lane_state loss it audits.
4. Close this card as confirmed-anomaly; root fixes already tracked by
   AUD-0947 (unsafe classification), AUD-0944/45/46 (ephemeral artifacts),
   AUD-0950 (state dir, fixed), AUD-0938 (audit-artifact durability).
