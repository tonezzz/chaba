# Cline review-feed lane — review-column evidence verdicts

`scripts/ops/cline-review-feed.py` drains the review column's mechanical
subset through the con01 Cline kanban board (card `cline-card-review-lane`,
proven pattern: card `lane-cms-content-model` → task `8b60e`, 2026-10-29).

## What it does

1. **SELECT** — `/cards?column=review`, then per-card `is_cline_suitable`:
   drops cards with open human requests, spec/note matching the exclusion
   regex (secrets/creds, deploys, host mutations, live-repo work), and
   cards with no spec/note/comms to review from. Auto-incident prefixes
   (`logs-auto`, `runner-auto`, `cms-auto`, `disk-auto`, `vcast-auto`)
   classify as `incident`; everything else selected is `deliverable`.
2. **CREATE** — one task per card on the con01 board, marker
   `[CARDREVIEW:<id>]` in the prompt for idempotency (re-runs reuse the
   existing task). Max `--max-inflight` (default 3) tasks in
   backlog/in_progress at once — qwen2.5:7b is slow and OR-free models
   share free quota.
3. **COLLECT** — when a task reaches `review`/`trash`, or its session
   ends (`agent_end` in hooks.jsonl — the runtime can lose the session
   record), pull the worktree diff via `bridge.collect_patch` and verify
   `verdict.json` + `evidence.md` exist and are non-empty.
4. **REPORT** — card comms line with the verdict + artifact summary, and
   a `/request` with dict options `close`/`keep`/`requeue` (suggested =
   `close`→close, `hold`→keep, `investigate`→requeue) so Tony answers in
   one word. **The script never moves or closes a card.**

## Dedupe rule (the 8b60e bug)

The lane-cms run posted `task 8b60e review-ready` five times — the poll
loop re-reported unchanged state. The feed keeps
`~/.local/state/cline-review-feed.json` keyed by card → `{task_id,
reported_key, request_raised}` where `reported_key =
task_id|column|updatedAt`. A task whose (id, column, updatedAt) is
unchanged since the last report produces no new comms, and the options
request is raised at most once per card.

## Marker caveat

The marker is `[CARDREVIEW:<id>]`, deliberately NOT `[CARD:<id>]` —
`scripts/ops/cline-board-mirror.py` claims every task whose prompt
contains `[CARD:` as its own read-only projection and would rewrite or
delete a live review task.

## Usage

```bash
# on con01 (needs podman exec into cline-kanban)
python3 scripts/ops/cline-review-feed.py --dry-run          # show picks
python3 scripts/ops/cline-review-feed.py                  # one pass
python3 scripts/ops/cline-review-feed.py --wait-s 3600    # feed + collect
python3 scripts/ops/cline-review-feed.py --card <id>      # one card only
```

Env: `BOARD_API` (default `https://idc03.taila0626a.ts.net:10000`),
`CLINE_REVIEW_STATE`, `CLINE_REVIEW_OUT`. Provider/model default
`ollama/qwen2.5:7b`, pinned to the bridge free-lane allowlist — zero paid
spend. Patches land under `$CLINE_REVIEW_OUT/<card>/<task>.patch`.

## Task contract (what the model must write)

- `verdict.json` — `{"verdict": "close"|"hold"|"investigate",
  "confidence": "low"|"medium"|"high", "reason": "<one line>"}`
- `evidence.md` — claim, what the comms show, gaps, verdict rationale.

Prompts carry the card spec/note/comms inline; the workspace is
disposable and has no repo or host access — cards needing live evidence
are excluded at SELECT, and the model is told to answer `investigate`
rather than invent probe results.
