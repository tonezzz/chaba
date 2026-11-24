# Dispatch outcome — devin-usage-reduction (DEV-0044)

Session: 20261124-224339-assessment-2026-11-23-delivere on idc02, branch
`dispatch/20261124-224339-assessment-2026-11-23-delivere`.

## What this session did

Processed the roadmap card end-to-end: re-verified the 2026-11-23
assessment against live repo/host state, picked the first low-risk task
class to re-route off the devin lane, filed one follow-up card per open
lever, and left the decision trail in a job doc.

## Findings (verified, not from memory)

- **Already landed:** OPS-0838 (queue-time classify), OPS-0869 (lane
  catalog), OPS-0885 (free-lane pilot) are all done/archived. DEV-0045
  classifier slices merged via PR #199 (kw:host removal, cheapest-first
  lane order, timer-alert pin, lane_source stamping, kanban-stats
  lane×source watch). `devin-usage.py` already reports free-tier window
  burn (added 2026-11-23).
- **Usage re-measure (idc02, 30d):** 191 sessions / 876.7M prompt; avg
  4.46M; audit/assess shape = 56.8M across 12 sessions. 97% cached.
- **Open-card classifier snapshot:** 198 open cards → devin cohort 72
  (61 jevos-fallback + 11 kw hits); free_lane already absorbs
  timer-alert/report/try/docs classes.
- **Allowance remaining is NOT machine-readable today:** `devin` CLI has
  no usage subcommand; `/usage` is TUI-only; transcript.json carries
  token metrics only. Filed an investigation card.
- **Task-dir GC gap confirmed on idc02:** 917 dirs under
  `~/.local/share/devin-dispatch/tasks`, `devin-cleanup.timer` not
  installed (unit not found), `devin-session-prune` covers only
  tony_omen sessions.db. Caveat recorded: devin-usage.py reads these
  dirs, so retention must exceed the 30d reporting window.
- **Lever 2 already covered:** lane_envelope claim-hold + attempt caps
  are implemented; retry-storm detection and zero-commit churn already
  have backlog cards. No dupe filed.

## Pick: first low-risk class to re-route

**Bounded read-only audit/assessment/review/investigate cards →
free_lane** (ops-readonly profile via LANE_PROFILES). Title-scoped match
with mutation-verb exclusion — spec bodies can't trigger it. Contract
§3 already reserves read-only profiles for reports/audits; worst-case
misroute costs a free-lane attempt, never devin burn.

## Cards filed (board-api, backlog, armed dispatch, unqueued)

| ref | id | lever |
|---|---|---|
| DEV-1332 | devin-usage-allowance-visibility | 3 — allowance remaining |
| DEV-1333 | devin-taskdir-gc-dispatch-hosts | 5 — task-dir hygiene fleet |
| DEV-1334 | dispatch-prompt-budget-measure | 4 — session-bloat drivers |
| DEV-1335 | classifier-readonly-audit-class-reroute | 1 — the picked class |

## Deliverables

- `docs/ssot/jobs/devnest/2026-11-24-devin-usage-reduction.yml`
  (committed on this branch, 28ddf0c8e2) — full verification + decision
  trail.
- 4 cards above; progress + final comms on `devin-usage-reduction`.

## Decision gates respected

No lane-pinned default adopted (routing contract still draft — Tony
review pending). No runner timers touched. No paid_frontier escalation.
No deploy/push; card writes went through board-api only.

## How to verify

- `python3 scripts/devin/devin-usage.py --days 30` on any dispatch host.
- `python3 scripts/board/lane-savings.py --month 2026-11` for lane mix.
- Job doc: `docs/ssot/jobs/devnest/2026-11-24-devin-usage-reduction.yml`.
- Cards: board-api `GET /card/<id>` for DEV-1332..1335.

lessons:
- "devin usage" is not in the devin CLI — no `usage` subcommand; `/usage` is TUI-only and transcripts carry only token metrics, so allowance-remaining needs an api.devin.ai probe (filed as DEV-1332).
- Dispatch task dirs accumulate forever on hosts without devin-cleanup.timer — only dell/omen are declared; idc02 had 917 dirs. devin-usage.py depends on those dirs, so GC retention must exceed the reporting window.
- Lane classifier keyword hits match spec bodies as substrings — adding 'audit' to LANE_KW['free_lane'] would misroute every 'audit then fix' card; title-scoped rules (like the timer-alert pin) are the safe pattern.
- valid_lanes() at the board-api write door = LANE_MODELS ∪ LANE_EXECUTORS minus retired — 'devin' is NOT a settable action.lane; you cannot pin lane=devin via /card, use executor=devin instead.
- Free_lane-classified cards without action.lane_envelope are HELD at claim (no attempt burned) — filing a spec-heavy card that self-classifies free_lane will stall until someone stages an envelope or pins executor=devin.
