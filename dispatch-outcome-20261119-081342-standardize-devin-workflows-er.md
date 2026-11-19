# Dispatch outcome — Standardize Devin workflows & error handling

**Card:** `standardize-devin-workflows-error-handli-e19df2` (DEV-0253)
**Result:** done — audit + codification delivered on branch
`dispatch/20261119-081342-standardize-devin-workflows-er`, commit
`e307d7ccee` (docs-only, 4 files, +321 lines).

## What the card asked

Tony's answered request (2026-10-26): *"chaba — audit current
error-handling patterns across lanes, write ssot.procedures entries +
AGENTS.md rule"*. Earlier attempts (2026-11-17, tony-omen + tony-dell)
died exit=1 with zero commits before doing any work — this run is the
first to actually execute the spec.

## What changed

- **`docs/kb/devin-error-handling-standard.md`** (new) — the audit:
  a lane-by-lane table of the failure surfaces (kanban-dispatch,
  runner-agent, merge-sweep, dispatch-wt-sweep, board-api/publication,
  devin-dispatch + watch, job-run, request/answer sweeps,
  waiting_cards + the autonomy envelope), the distilled **10-rule
  standard**, plus a gaps section (three retry counters with different
  semantics, vendored-twin drift in the standalone runner deploy,
  dispatch-watch's record-less "inferred success", awaiting_action
  semantics being convention-only).
- **`docs/ssot/ssot.procedures.yml`** — two entries under a new
  `# --- dispatch / unattended work ---` section:
  `devin-error-standard` (lane-author trigger) and
  `session-blocked-protocol` (in-session trigger: /request,
  needs-input.txt, exit-42, answers.jsonl).
- **`AGENTS.md`** — new duty "Devin workflow & error-handling standard
  (added 2026-11-19 — DEV-0253)" after procedure-lookup: the 10 rules
  for lane authors + the session-side rails contract.
- **`docs/ssot/jobs/board/2026-11-19-devin-workflow-error-standard.yml`**
  (new) — job record: scope answer, deliverables, lanes audited, the
  10 rules, gaps, verify commands.

## The standard in one line

Nothing invented — codified: fail loud with bounded evidence, bounded
retries re-armed only by a human verb, failure evidence rides the next
attempt, blocked ≠ failed, advisory components never block, gate at
claim not mid-run, probes outside the flock, nothing unproven
destroyed, exit≠0 means crashed-not-findings, finished ≠ verified.

## How to verify

- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/ssot.procedures.yml'))"` — ran, OK
- `python3 scripts/ssot-prose-smell.py` — ran repo-wide, 0 flagged
- `grep -n 'devin-error-standard\|session-blocked-protocol' docs/ssot/ssot.procedures.yml` — lines 145-146
- `grep -n 'Devin workflow & error-handling standard' AGENTS.md` — line 164
- Read `docs/kb/devin-error-handling-standard.md` — audit table + rules + gaps

lessons:
- The card's answered request was the real spec — the first scope answer (2026-10-25) was a meta-option that re-asked the question; the second (2026-10-26) carried the actionable answer. Always read `requests:` answers before scoping.
- Two prior dispatch attempts on this card died exit=1 with zero commits (runner-side, no work landed) — the retry-ledger/backoff machinery worked as designed; this run succeeded on idc02.
- `ssot.procedures.yml` entries are pointers only (id/where/trigger/status) — the audit body belongs in a kb doc, not in the index (anti-sprawl + the >40-line prose-smell lint).
- `verified: false` and "verified withheld" are deliberately different states in merge-sweep — checked-and-failed requeues, unproven holds for a human.
