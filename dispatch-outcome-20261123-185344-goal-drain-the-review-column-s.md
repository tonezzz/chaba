# Dispatch outcome — cline-card-review-lane (2026-11-23, tony-dell attempt)

## What this run did

Recovered and finished the work the tony-omen attempt-6 session died
mid-debug on, then ran the lane live off-con01 for the first time.

1. **Recovered staged work** from the dead tony-omen worktree
   (`dispatch-wt-20261123-183550-*`, still on disk): a rewritten
   `cline-review-feed.py` (comms-latch dedupe, `already_requested`,
   card-left-review audit path, `parse_verdict` tolerant JSON,
   `trash_collected`) plus a `.dispatch-bin/podman` ssh shim whose quoting
   fix was the session's last act before the unit died.

2. **Embedded the shim into the feed** as `--podman-ssh HOST` /
   `CLINE_REVIEW_SSH` — generates a tempdir `podman` shim that
   single-quote re-escapes every argv element (ssh's remote-shell reparse
   was expanding the nested `sh -c '"$@" >"$O" …'` script's `$O`/`$@`/`$?`
   before podman saw them — the reported failure) and adds ssh
   ControlMaster multiplexing (~5 ssh calls per podman exec; 21.7s →
   ~7s per `task list`). Verified lossless on args containing spaces,
   quotes, `$VAR`, backticks and literal newlines.

3. **Fixed three more bugs found running the drain live:**
   - dedupe-skipped settled tasks never reached `trash_collected` —
     bb711 sat `in_progress` on the cline board holding an inflight slot
     forever; now dedupe branch trashes settled tasks.
   - `tasks` snapshot predated collect-trashes, so `room` computed 0 and
     the pass exited before creating anything; list is refetched after
     collect.
   - a trashed/done predecessor shadowed fresh re-feeds of the same card
     (`feed_tasks` now prefers live columns; terminal `existing` no
     longer blocks create).

4. **Ran the drain** (`--podman-ssh con01`, seeded state merged from
   con01 `/tmp/crf/state.json` + tony-omen local state):
   - `cms-auto-nest-tony-macbook` ← task 43d16: verdict **INVESTIGATE**
     comms + request `cline-drafted-verdict-investigate-redepl-5d52a2`
   - `fix-cms-publish-page-slug-argument-missi-96152a` ← fabd1: verdict
     **HOLD**, audit comment only (card already `done` — no request on a
     settled card), task trashed
   - bb711/e05b5/b699c: deduped via state+comms latches — **zero repeat
     comms** (the bug this card exists to kill); bb711 trashed
   - created **45847** (`ada-dispatch-approve-button`) and **43511**
     (`cline-proposal-pilot-edu-no-th`), both `in_progress` on
     ollama/qwen2.5:7b — zero paid spend (allowlist enforced)

## Live-run incident

con01 **rebooted mid-run** (~19:2x +07; uptime 8min when checked) —
wiped `/tmp/crf` and killed one feed pass on a 30s podman-cat timeout.
All containers (cline-kanban, ollama, caddy-edge, mddb-follower) came
back; kanban state persisted. Recreated `/tmp/crf` with the new
script+bridge. Feed restarted (`--wait-s 2400`); the two in-flight tasks
show `in_progress` — post-reboot session state is the known
lost-session case the feed already handles via `agent_end` hooks.

## Deliverables (commit 89110e00a3d on this branch)

- `scripts/ops/cline-review-feed.py` — all of the above
- `docs/kb/cline-review-feed.md` — runbook: comms latch, trash, tolerant
  parse, `--podman-ssh` usage + quoting rationale
- `docs/ssot/jobs/kanban/2026-11-20-cline-review-feed.yml` — fixes/next
  trail updated

## Verify

```bash
python3 scripts/ops/cline-review-feed.py --podman-ssh con01 --dry-run
# board: comms on cms-auto-nest-tony-macbook (verdict+request),
#        audit line on fix-cms-publish-...; both cards unmoved
```

## Not done / follow-ups

- Tasks 45847/43511 still in flight at session end — next feed pass
  collects them (state `~/.local/state/cline-review-feed.json` on
  tony-dell is durable; comms latch makes any host safe).
- e05b5/b699c cline tasks linger in the board's `review` column —
  harmless (not cap-counting); a human can inspect or trash.
- No systemd timer — still manual/dispatch-driven (host mutation gate).
- Rare edge: if `/comment` lands but `/request` fails, the comms latch
  can latch `request_raised` without the request on a state-lost rerun —
  verdict comms still informs Tony; noted, not built.

lessons:
  - unpushed dispatch-branch work survives on the dead host's worktree — `git -C <wt> diff HEAD` + scp recovered the whole tony-omen attempt
  - ssh→remote-shell reparse eats `$O`/`$@`/`$?` inside nested `sh -c` args — single-quote re-escape every argv element; ControlMaster or a pass takes tens of minutes
  - kanban `task list` output truncates ~16KB through a pipe — bridge redirects inside the container; don't hand-roll `podman exec ... | json.load`
  - con01 reboots wipe /tmp — deployed scratch copies (/tmp/crf) are ephemeral; repo is canonical
  - a feed pass that trashes tasks must refetch the task list before computing inflight room, and dedupe-skipped settled tasks still need trashing or they hold cap slots forever
