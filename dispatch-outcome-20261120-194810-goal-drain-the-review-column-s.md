# Dispatch outcome — cline-card-review-lane (2026-11-20)

## What changed

- **New `scripts/ops/cline-review-feed.py`** — the review-drain driver:
  1. **SELECT** review-column cards that are cline-suitable (bounded
     deliverable or evidence-verdict). Excludes: open human requests,
     secrets/creds, deploy/host-mutation, live-repo work — via card
     fields + an exclusion regex. Auto-incident prefixes (`logs-auto`,
     `runner-auto`, `cms-auto`, `disk-auto`, `vcast-auto`) classify as
     `incident`; the rest are `deliverable`.
  2. **CREATE** one task per card on the con01 cline-kanban board,
     `[CARDREVIEW:<id>]` marker for idempotency, ≤3 in-flight,
     provider/model pinned to the bridge free allowlist
     (`ollama/qwen2.5:7b` default) — zero paid spend.
  3. **COLLECT** settled tasks (column review/trash, exit 0, or lost
     session + `agent_end` in hooks.jsonl), pull the worktree diff with
     `bridge.collect_patch`, verify `verdict.json` + `evidence.md` exist
     and are non-empty.
  4. **REPORT** card comms with the verdict + artifact summary and raise
     a `/request` with dict options close/keep/requeue + ★ suggestion.
     Never moves or closes a card.
- **`docs/kb/cline-review-feed.md`** — runbook (usage, marker caveat,
  task contract, dedupe rule).
- **`docs/ssot/jobs/kanban/2026-11-20-cline-review-feed.yml`** — trail.

## Bugs fixed while building

- The 8b60e repeat-comms bug: dedupe by last-reported
  `(task_id|column|updatedAt)` in `~/.local/state/cline-review-feed.json`;
  options request fires once per card.
- Report state only latches after board-api confirms the write (a failed
  `/comment` no longer suppresses retry).
- Marker deliberately `[CARDREVIEW:<id>]`, not spec's `[CARD:<id>]` —
  `cline-board-mirror.py` claims every `[CARD:` task as its own
  projection and would rewrite/delete live review tasks.
- board-api 400s `from` values outside `ada|chaba|devin|tony` — ACTOR is
  `devin`.

## Verification (ran live, 2 pilots on con01)

| card | kind | task | verdict | result |
|---|---|---|---|---|
| vcast-auto-yt-live-api | auto-incident | e05b5 | investigate | verdict comms + request `cline-drafted-verdict-investigate-connec-96bd80` (open) |
| board-janitor-locked-edit-atomic-write-db7bed | bounded deliverable | b699c | investigate | verdict comms + request `cline-drafted-verdict-investigate-done-c-a696fe` (open) |

- Both cards stayed `column: review` — no auto-close.
- Re-run pass produced zero new board writes — dedupe works.
- ollama/qwen2.5:7b only — zero paid/model-key spend.
- Patches on con01 at `/tmp/crf/out/<card>/<task>.patch`; task worktrees
  `/root/.cline/worktrees/{e05b5,b699c}/workspace/`.

## How to verify

```bash
curl -s https://idc03.taila0626a.ts.net:10000/card/vcast-auto-yt-live-api?fields=column,requests
ssh con01 'python3 /tmp/crf/scripts/ops/cline-review-feed.py --card vcast-auto-yt-live-api --state /tmp/crf/state.json'   # prints [] — nothing re-reported
```

## Not done / follow-ups

- No con01 systemd timer installed — host mutation, needs declared unit
  (hourly `cline-review-feed.service`) if Tony wants the lane standing.
- Tasks remain `in_progress` on the cline board after collection when
  the runtime loses the session record; cleanup move to trash could come
  later once the pattern settles.

lessons:
  - board-api /comment and /request reject `from` outside ada|chaba|devin|tony with HTTP 400
  - never use `[CARD:` markers in new cline task prompts — cline-board-mirror.py claims all such tasks as its read-only projection and rewrites/deletes them
  - cline task `session` field is unreliable; `agent_end` in hooks.jsonl is the ground truth for "agent finished" (bridge.agent_ended already encodes this)
  - kanban task list output truncates at ~8KB on a pipe — bridge's redirect-to-file trick is required, don't re-learn it
  - report/dedupe state must latch only after the write door confirms — latching on attempt silently swallows failures
