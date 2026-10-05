# Outcome — kanban-push-notify: board request push notifications

## What changed

- `scripts/board/board_notify.py` (new) — push channel helper + CLI.
  Channels via `BOARD_NOTIFY_CHANNEL`: `ha` (default), `yomi`, `ntfy`,
  `file` (test sink), `off`. Best-effort, 8s timeouts, never raises.
- `scripts/board/board-api.py` — `POST /request` now stamps `at`/`from`/
  `to` on each request (`to` absent = tony). Agent-raised requests
  targeting tony queue a push after a 30s debounce
  (`BOARD_NOTIFY_DEBOUNCE_S`) so bursts arrive as one batched
  "Board: N new requests" summary — quiet-by-design.
- `scripts/board/request-sweep.py` (new) — runs inside the kanban-sync
  tick (every 15min). Open tony-targeted requests unanswered
  >`BOARD_SWEEP_AGE_H` (12h default) get ONE batched escalation push;
  `escalated_at` stamped in the card under `/tmp/board-api.lock` so it
  fires exactly once. Push failure → nothing stamped → next tick retries.
  `--dry-run` previews.
- `scripts/ada/kanban-sync.sh` — step 2b runs the sweep.
- Docs: `docs/ssot/kanban/ssot.kanban.yml` (request schema + /request
  endpoint), `docs/ssot/infrastructure/ssot.jobs.yml` (kanban-sync note),
  `docs/ssot/jobs/kanban/2026-10-05-board-request-notify.yml` (decision
  record + runbook).

## Channel decision

Picked **HA iPhone push** (`notify.mobile_app_tony_ip` on tony-ha
loopback :8123, clickAction `/chaba-admin/board`) — the same path
devin-dispatch-watch uses for every finished job. Evaluated per the card:
yomi LINE rejected — `/api/yomi/session-status` is currently
`valid:false` (LINE revoked session; re-login rate-limited 1/h and needs
Tony), no notification chatId is configured anywhere, and self-send is
unverified; the yomi channel is implemented behind
`BOARD_NOTIFY_CHANNEL=yomi` + `BOARD_NOTIFY_YOMI_CHAT` for when the
session is restored. ntfy.sh rejected — new external SaaS + app/topic
subscription with no existing usage in the repo (also implemented,
behind `BOARD_NOTIFY_CHANNEL=ntfy`).

## Verification (all ran green)

- `board_notify.py` CLI → real iPhone push sent ("Board test").
- Test board-api instance (worktree, :9877): `POST /request` devin→tony
  → notification fired; `to:ada` and `from:tony` correctly stayed quiet;
  3 concurrent POSTs → one batched "Board: 3 new requests" push.
- Sweep vs isolated `/tmp/sweep-test` card dir: 13h-old open request →
  exactly one "unanswered >12h" push + `escalated_at` stamp; second run
  quiet; legacy requests without `at` fall back to comms/card.updated
  timestamps; 4 overdue requests across 3 cards → one batched push.
- `python3 scripts/board/board-api.py --selftest` → ok; YAML validated.

## To go live after merge

Restart `board-api.service` on tony-dell so the live :8787 instance
picks up the hook. The sweep needs no install — it runs inside the
existing kanban-sync.timer tick.
