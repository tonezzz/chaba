# Dispatch outcome — cline-card-review-lane (2026-11-23, attempt 3)

## What happened

Attempts 1 (idc02, 2026-11-20 19:48) and 2 (tony-dell, 20:59) both exited
non-zero at the service level. Attempt 1 had in fact finished the work —
script built, both pilots run live on con01, DONE comms posted — but the
commits sat on a dispatch branch that was never pushed, and idc02's
worktree was never merged. Attempt 2 died ~3 min in (provider
rate-limit signature), producing nothing.

This run recovered attempt-1's work instead of rebuilding:

- `git fetch ssh://idc02/...dispatch-wt-20261120-194810...` pulled both
  unpushed commits; cherry-picked onto this branch:
  - `d12abe12c06` — `scripts/ops/cline-review-feed.py` +
    `docs/kb/cline-review-feed.md` +
    `docs/ssot/jobs/kanban/2026-11-20-cline-review-feed.yml`
  - `bb023ad3def` — attempt-1 outcome doc
    (`dispatch-outcome-20261120-194810-goal-drain-the-review-column-s.md`,
    kept for the live-run record).
- Recovered script is **byte-identical** (md5 `5149f6f6…`) to the copy
  still deployed at con01 `/tmp/crf/scripts/ops/cline-review-feed.py`
  that ran the pilots — no drift, no rebuild needed.

## Re-verification this session (2026-11-23)

All spec verify criteria confirmed against live state:

| criterion | result |
|---|---|
| 2 pilots (1 incident + 1 deliverable) | `vcast-auto-yt-live-api` (vcast-auto incident → cline task e05b5) and `board-janitor-locked-edit-atomic-write-db7bed` (deliverable → task b699c), both verdict INVESTIGATE |
| verdict comms + options request | both cards carry `cline review verdict (ollama/qwen2.5:7b …): INVESTIGATE` comms + open requests `cline-drafted-verdict-investigate-connec-96bd80` / `-done-c-a696fe` |
| no auto-close | both cards still `column: review` |
| dedupe | re-ran feed on con01 with the original `/tmp/crf/state.json`: output `[]` — zero board writes, both cards correctly skipped (`reported_key` matches, and the open verdict requests make the cards ineligible anyway) |
| zero paid spend | provider/model pinned to free-lane allowlist (`ollama/qwen2.5:7b` ran; allowlist is ollama-local + OR-free only) |

## Deliverables on this branch

- `scripts/ops/cline-review-feed.py` — SELECT/CREATE/COLLECT/REPORT
  driver; `[CARDREVIEW:<id>]` marker (NOT `[CARD:` — the board-mirror
  claims those), ≤3 in-flight, last-reported `(task_id|column|updatedAt)`
  dedupe in `~/.local/state/cline-review-feed.json`, never moves cards.
- `docs/kb/cline-review-feed.md` — runbook.
- `docs/ssot/jobs/kanban/2026-11-20-cline-review-feed.yml` — job trail.

## How to verify

```bash
git log --oneline origin/master..HEAD   # 3 commits incl. this doc
curl -s 'https://idc03.taila0626a.ts.net:10000/card/vcast-auto-yt-live-api?fields=id,column'   # still review
ssh con01 'python3 /tmp/crf/scripts/ops/cline-review-feed.py \
  --card vcast-auto-yt-live-api --state /tmp/crf/state.json --out /tmp/crf/out'   # prints []
```

## Not done / follow-ups

- No systemd timer on con01 — lane is manual/one-shot until Tony
  declares a unit (host mutation, out of dispatch scope).
- Settled cline tasks stay `in_progress` on the cline board when the
  runtime drops the session record; a cleanup move-to-trash is a later
  refinement (noted in attempt-1 outcome).

lessons:
  - unpushed dispatch-branch work is recoverable via `git fetch ssh://<host>/<worktree-path> HEAD` + cherry-pick even days later — check the failed run's host worktree before rebuilding
  - a verdict request the lane raises itself makes the card ineligible next pass (`open human request` skip) — the lane self-drains, no extra bookkeeping needed
  - board-api comms/requests persist across runner churn — re-verify idempotency cheaply by re-running with the original state file rather than re-running the full lane
