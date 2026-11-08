# dispatch 20261108-124119 — timer chaba-repo-sync on tony-dell failing

Card: `timer-alert-tony-dell-chaba-repo-sync` (OPS-1169). Runner: idc02.

## What was found

`chaba-repo-sync.service` on tony-dell wedged all morning (timeout at
10:42 / 11:28 / 12:02, exit-code at 10:54 / 11:41 / 12:15, signal at
12:33). Root cause — already partially diagnosed in card
`chaba-exec-checkout-divergence` and verified here against the live
checkout and reflog:

- An **orphaned `board-api.py`** (spawned ~Nov 4 inside the
  devin-desktop scope; the `chaba-board-api.service` unit is
  `.parked`/dead by design) kept serving **127.0.0.1:8787** bound to
  `~/CascadeProjects/chaba` — the **exec** checkout, not the served
  one on idc03.
- Everything on dell that defaults to loopback 8787
  (`timer-sentinel.py`, `board-cli.py`, reconcile's primary base)
  wrote through it; board-api's immediate `_commit_write` produced
  **837 unpushed local commits** between 10:31 and 12:19, all
  `board-api@chaba.local`.
- Every 15-min `git pull --rebase --autostash` then replayed the
  entire pile — card-union merge driver per conflicted card step,
  `.ref-seq` conflict churn (`*.local-conflict-*` non-card flags),
  reconcile flag posts (~30s each through a slow door) — burning
  ~5min CPU until `TimeoutStartSec=300` SIGTERMed it. The merge
  fallback then died on "merge refused before conflict stage
  (dirty tree?)". Same wedge class documented in
  `reconcile-local-conflicts.py` (2026-11-07 incident).

## Resolution (was already in motion mid-incident)

- Rogue process killed ~12:30 (PID 262964); nothing listens on
  dell:8787 now.
- Manual `git reset --hard origin/master` at 12:34:25 discarded the
  pile; pull fast-forwarded. 12:35 tick = clean no-op, **12:51 tick
  finished in 7.7s**, checkout at 0/0 vs origin.
- Discarded tip `5e656cf3cb` remains in the reflog (~90d).

## Lost-write recovery (done this session)

Semantic YAML diff of `5e656cf3cb` vs `origin/master` over all 177
differing card files (83 with unique content). Replayed the real
uniques to canonical board-api on idc03, each tagged
`[replayed ... recovered from reflog]`:

- `ada-opencode-control-plane-tab`, `ada-opencode-nl-card-resolve`,
  `adobe-stock-render-preview-wiring` — close-verification comms
- `opencode-retry-stale-worktree` — OPS-1039 unblock evidence
- `line-wp-site-manager` — 2 watcher comms
- `keep-eye-on-floods-4f0f97` — open flood-watch request re-raised
  (`re-raised-2026-11-08-original-request-fl-ea7044`)

Skipped: ~1000 sentinel "[still suspicious]" comms (re-derive), stale
queued scalars on timer-alert cards (canonical already ran them), 6
timer-alert cards existing only on the discarded side (sentinel
recreates).

Needs human triage (listed on the card, NOT re-moved — humans own
workflow fields): `ops-local-conflict-guard` (done vs review),
`colibri-bench-qwen3-6-35b` (review vs backlog),
`ada-opencode-live-demo-opsread` (review vs done),
`ada-opencode-repair-menu-card` / `adobe-stock-illustration-pivot-test`
(backlog vs review).

## Residuals / follow-ups (carded in comms)

- dell-side `BOARD_API` defaults of `127.0.0.1:8787` are a
  repeat-wedge trap — repoint to `board-cli --ssh idc03` or add a
  loopback-8787 canary on non-served hosts.
- `.parked` units on dell violate declared-or-dead hygiene; ~30 stale
  worktrees.
- Uncommitted leftovers on the exec checkout (staged focus-inbox
  file, modified `ssot.ui.ha.yml`) and 7 retained autostash entries.

## Trail

- Findings comms posted on `timer-alert-tony-dell-chaba-repo-sync`
  and `chaba-exec-checkout-divergence`.
- `docs/ssot/jobs/infrastructure/2026-11-08-chaba-repo-sync-timeout-rogue-board-api.yml`

## Verify

```
ssh tony-dell 'journalctl --user -u chaba-repo-sync.service -n 20'   # <10s ticks
ssh tony-dell 'cd ~/CascadeProjects/chaba && git rev-list --left-right --count HEAD...origin/master'  # 0 0
ssh tony-dell 'ss -tlnp | grep 8787'                                 # empty
```
