# Dispatch outcome — kanban-dispatch /ready verdicts (KNB-1007 follow-up)

Card: `kanban-dispatch-lane-doesn-t-report-read-1ee640`
Branch: `dispatch/20261124-172624-follow-up-from-knb-1007-deploy` (commit `f59866b399`)

## What changed

`scripts/board/kanban-dispatch.py` (+197/-22):

- **`verdict_pass()`** — runs at the end of every `main()` pass (after
  phase-B starts/merges, before notify flush). For every card with
  `action.status == "queued"` it computes a claimability verdict and
  POSTs `{host: HOST, verdicts, active}` to board-api `/ready`.
  `active` lists this host's in-flight claims (`starting`/`running`
  with `runner` unset-or-local) as `{id, unit, at}`.
- **`_verdict_reason(card, ctx)`** — read-only mirror of the claim
  loop's gate order: pass gates → autonomy tier → retry cap → host pin
  → `blocked_by` → `action.type` → `lane` (manual/jules/nlm_batch) →
  `executor` → `target_host` → labels → push guard → waiting-cards
  gate → foreign-runner claim → host cap. Returns `""` (ok) or the
  blocking reason. No flag/defer/save side effects.
- **`claim_pass_gate(pol, pf_env)`** — the pass-level gates (load,
  kill switch, quiet hours, waiting-cards preflight, provider
  rate-limit cooldown) extracted from `main()` so claims and verdicts
  share one source; `main()` now calls it too.
- **`api()`** helper (runner-agent shape: errors → `{"error": ...}`),
  `READY_REPORT` debounce file (`~/.local/state/kanban-dispatch/
  ready-verdicts.json`, env `KANBAN_DISPATCH_READY_FILE`),
  `READY_FORCE_S` = `KANBAN_DISPATCH_READY_FORCE_S` (default 900) —
  same debounce contract as runner-agent's verdict_pass.
- Inflight capacity is re-surveyed with a fresh `active_tasks()` at
  verdict time (phase-A0's count predates the pass's own starts).

Trail doc: `docs/ssot/jobs/kanban/2026-11-24-kanban-dispatch-ready-
verdicts.yml`.

## Result / verification

- `python3 -m py_compile` clean.
- `python3 -m unittest` on the six kanban-dispatch/board suites:
  **103/103 ok**.
- Stub board-api e2e: `verdict_pass()` POSTs `/ready` with per-card
  verdicts, host-scoped `active`, and payload-hash debounce (second
  identical pass does not repost).
- Full `tests/board` discover: 905 tests, 7F+3E — all pre-existing
  environment/stale-branch issues (pytest not installed on this host,
  3 import errors, runner-tooling pin drift that origin/master already
  resolved — this worktree is 83 commits behind; kanban-dispatch.py is
  identical on master so the merge is conflict-free).
- **Live verify is post-deploy**: tony-dell runs the script from the
  pull-only `chaba-tony-dell` mirror (hourly `chaba-served-mirror-
  sync`), so once this merges and syncs, the next
  `kanban-dispatch.timer` pass (2 min) POSTs and `GET /queue` hosts
  will include `tony-dell` with fresh `age_s` plus a verdict per
  queued card. No unit/config change needed. idc03's manual-drain
  kanban-dispatch unit reports under its own HOST when run — correct,
  it is a real claimer there.

## How to verify after deploy

```
curl -s https://idc03.taila0626a.ts.net:10000/queue | python3 -m json.tool | head -40
# expect hosts.tony-dell.age_s small, and each queued[] entry's
# verdicts/block unreported no longer lists tony-dell
```

lessons:
- kanban-dispatch claims on tony-dell but had no /ready reporter — any new claim lane must POST verdicts or /queue shows 'unreported'.
- verdict_pass mirrors the claim gate order read-only; pass-level gates are shared via claim_pass_gate() so the two can't drift.
- Re-survey active_tasks() at verdict time — phase-A0's count predates the pass's own starts.
- Worktree was 83 commits behind origin/master; runner-tooling pin test failure was stale-branch drift already fixed on master, not this diff.
