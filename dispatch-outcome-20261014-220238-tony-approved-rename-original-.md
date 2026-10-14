# ada-pi → ada-voice rename (card ada-pi-rename-ada-voice, attempt 2)

The Pi lie is retired. Repo renamed, all reachable checkouts renamed, dispatch
layer dual-keyed during transition, prod deploy verified green on the new path.

## What landed

- **GitHub**: `tonezzz/ada-pi` → `tonezzz/ada-voice` via `gh api PATCH`.
  Old name redirects for web + git protocol (verified `ls-remote`).
- **Checkouts renamed** `~/CascadeProjects/ada-pi` → `ada-voice` on all five
  reachable hosts — tony-dell (22 worktree .git fixups, 5 units patched),
  idc02 (9/4), idc03 (11/23), tony-omen (13/3), tony-macbook (4/0).
  Each host keeps a back-compat symlink `ada-pi -> ada-voice`; a forward
  symlink `ada-voice -> ada-pi` had been staged first so nothing ever saw
  a missing path. mn01 unreachable (ssh timeout) — still pending.
- **ada-voice repo self-sweep**: branch `dispatch/20261014-ada-voice-self-sweep`
  merged to main (`6fa8e9b`) — 60 files, bare `ada-pi` → `ada-voice`;
  hyphenated compounds (`ada-pi-pwa`, card/task slugs) and upstream
  `nazirlouis/ada-pi` preserved. All renamed checkouts pulled to `3aae927`.
- **chaba sweep** (this branch, `e07a471aa`, 340 files): scripts, stacks,
  systemd templates, SSOT, AGENTS.md, tests; `integrations/ada-pi` git-mv'd
  to `integrations/ada-voice`. Kanban card YAMLs deliberately untouched —
  a legacy `ada-pi` alias in repos.conf/BUILTIN_REPOS/REPO_TESTS/devin-dispatch.sh
  resolves old `action.repo` values (board-api has no field-edit endpoint,
  and cards/ edits lose to upstream-wins merges anyway).
- **Dispatch layer live**: `~/.local/share/devin-dispatch/repos.conf` on dell +
  macbook now carry canonical `ada-voice` + legacy `ada-pi` alias; other hosts
  had no conf file and get the alias via swept BUILTIN_REPOS on next chaba pull.
- **New executor**: `scripts/devin/rename-ada-voice.sh` — `status` shows the
  fleet table; `run <host|all> [--force]` is idempotent, quiet-gated per host
  (refuses while an ada devin-task lacks exit_code), does mv + compat symlink +
  worktree/unit/repos.conf fixups. Used for all five renames.
- **Runbook**: `docs/ssot/jobs/infrastructure/2026-10-14-ada-pi-rename-ada-voice.yml`

## Verification

- `deploy-ada.sh idc03` **green on the renamed checkout**: tool-lint clean,
  pytest **1448 passed**, all 8 services restarted and active from
  `~/CascadeProjects/ada-voice` (card's tool-lint + pytest + deploy verify ✓).
- `git status`, `remote -v`, `worktree list` verified per host; every
  `dispatch-wt-*`/`ada-wt-*` .git pointer rewritten to the canonical path.
- chaba: `ssot-validate-all` 2352/2352 valid; pytest tests/board+ada+ada_memory
  — failures identical on un-swept live master (pre-existing, see gotchas).
- `dr.repos()` resolves both `ada-voice` (canonical) and `ada-pi` (alias) →
  `/home/tony/CascadeProjects/ada-voice`; board-api accepts `ada-voice` cards.

## Pending / follow-up

- **mn01** — offline during the run; `rename-ada-voice.sh run mn01` when back.
- **Compat retirement** — remove `ada-pi` symlinks + alias lines after a clean
  soak; optional card `action.repo` sweep. Tracked in new card
  `ada-voice-rename-cleanup` (ADA-0681).
- **Dispatch claim on ada-voice** — resolution verified; first real claim
  happens naturally next dispatch (alias guarantees no strand either way).

## Pre-existing failures found (not caused by this change)

- `tests/ada` patch-apply tests fail on live master too — staged
  `integrations/` drop patches drifted vs evolved ada-voice sources
  (memory.py:206, line_relay.py:42, chat.py:234, common.py:301).
- `tests/board/test_claim_order` empty-claim — `overloaded()` load gate reads
  real host load; fails whenever load5/core is high. Environmental.

lessons:
  - regex lookarounds need PCRE2 (`rg` doesn't do them); worse, a misplaced
    lookahead `(?![a-z]-)` vs `(?!-[a-z])` silently renamed service names —
    verify swept diffs on a compound sample before committing
  - ada dispatches spawn constantly; a fleet-wide "quiet window" may never
    arrive — a compat symlink makes the cutover safe per-host instead
  - staged `integrations/` drop patches go stale fast; the apply-check tests
    were already red on master before the rename touched anything
  - `board-api` has no field-patch endpoint; a `repos.conf` alias line is the
    race-free way to keep old `action.repo` values resolving
  - several hosts (idc02/idc03/omen) have no live repos.conf — they ride on
    BUILTIN_REPOS from their chaba checkout; sync lag is real there
