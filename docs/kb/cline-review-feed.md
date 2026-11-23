# Cline review feed — draining the review column's mechanical subset

`scripts/ops/cline-review-feed.py` (KNB-1009, card `cline-card-review-lane`)
feeds cline-suitable **review** cards through the con01 Cline kanban so each
one comes back with an evidence check + a drafted verdict in comms — Tony's
review becomes a one-word decision on an options request.

Companion to the **intake** lane (`cline-kanban-nest-bridge/intake.py`,
`docs/kb/cline-lane-tagging.md`): intake drafts *new work* from `cline`-tagged
backlog cards; the review feed *verifies done-claims* on cards already in
review. They share the con01 `cline-kanban` container and the disposable
`/workspace` — but different task markers:

- `[CARD:<id>]` — cline-board-mirror projections (never started)
- `[NEST_JOB_KEY:<key>]` — intake/bridge tasks
- `[CARDREVIEW:<id>]` — this lane's tasks

## What it does per run

1. **REPORT** — for each `[CARDREVIEW:]` task whose session ended
   (`agent_end` hook or column=review), verify artifacts
   (`verdict.json` parses, verdict in close|hold|investigate; `evidence.md`
   non-empty), collect the worktree diff, then post to the Chaba card:
   - comms: `cline review verdict (ollama/qwen2.5:7b, task <id>): VERDICT — <reason>`
   - `/request` `cline-drafted-verdict-<verdict>-*` with options
     close / keep / requeue and a ★ suggestion
     (close→close, hold→keep, investigate→requeue).
   - moves the task to the Cline board's `review` column.
   - **never auto-closes** — humans keep the gate.
2. **SELECT** — review-column cards that are bounded: auto-incident
   prefixes (`logs-auto`, `runner-auto`, `cms-auto`, `disk-auto`,
   `vcast-auto`) get an evidence-pack prompt ("check this claimed
   condition"); everything else with a spec/note gets a done-claim check.
   Excluded: open human requests awaiting Tony, secret/deploy/security
   keywords, cards already fed. Incidents first, then stalest-updated.
3. **CREATE** — `kanban task create` + `task start`, max 3 concurrent
   `[CARDREVIEW:]` tasks (qwen2.5:7b on omen takes ~10–30 min; the cap
   also protects the shared free quota).

## Dedupe (the lane-cms 5x-repost bug)

Two layers, either one alone is sufficient:

- state file `~/.local/state/chaba/cline-review-feed.json` records the last
  reported `(task_id, column, updatedAt)` per card — an unchanged tuple
  skips reporting entirely.
- the card's own comms/requests are scanned before every write — a lost
  state file (e.g. the 2026-11-20 run whose work died on idc02's unpushed
  branch) still cannot double-post.

## Usage

```sh
# anywhere with `ssh con01` access (CLINE_SSH=con01 default);
# on con01 itself: CLINE_SSH="" — no paid keys needed, ollama only
python3 scripts/ops/cline-review-feed.py            # dry-run plan
python3 scripts/ops/cline-review-feed.py --execute  # report + create pass
python3 scripts/ops/cline-review-feed.py --execute --phase report
python3 scripts/ops/cline-review-feed.py --execute --card <id>
```

Env: `BOARD_API` (default idc03:10000), `CLINE_SSH`, `CLINE_CONTAINER`,
`CLINE_BOARD_JSON`. Flags: `--max-tasks` (3), `--provider/--model`
(allowlist: ollama qwen2.5:7b, qwen3:4b), `--state`, `--out-dir`
(patches, default `~/.local/state/chaba/cline-review-feed/`).

## Verified

2026-11-20 (first run, script lost with idc02's branch; verdicts + requests
live on cards): `vcast-auto-yt-live-api`→task `e05b5`,
`board-janitor-locked-edit-atomic-write-db7bed`→task `b699c`, both
verdict=investigate, both raised open `cline-drafted-verdict-*` requests.

2026-11-23 (this implementation): dedupe pass moved `e05b5`/`b699c` to
Cline `review` with zero new card writes; fresh pilots
`cms-auto-nest-tony-macbook`→`43d16`,
`report-graph-producer-metas-never-reach-7b0982`→`297a1`.

## Limits / gotchas

- Evidence-only review: the disposable workspace has no repo or live
  hosts, so "investigate" is the honest verdict whenever proof lives
  outside the card text. That's a feature — weak-model verdicts draft,
  humans decide.
- `kanban task` CLI needs `KANBAN_RUNTIME_HOST=0.0.0.0 PORT=3485` env and
  its >8KB stdout is piped through container temp files (bridge pattern).
- Over ssh, remote argv must be shlex-joined or the login shell eats
  `$O`/pipes/quotes — the reason the earlier bridge never ran remotely.
- An in_progress task whose session died without `agent_end` looks
  "running" forever; it holds one cap slot. `task delete` + recreate is
  the manual escape.
