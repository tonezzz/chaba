# Dispatch outcome — kk-cms-only-memory-pilot-acceptance

**Result: pilot DECLARED + APPLIED to prod ada-kk on idc03.** KK acceptance
and Tony approval were already on the card (request
`kk-do-you-accept-a-reversible-3-7-day-cm-d8c11e` answered "approve — KK
accepts, proceed with pilot" at 12:26). This session executed the FLOW.

## What changed (worktree, awaiting merge)

- `docs/ssot/apps/ssot.apps.ada-persons.yml` — `persons.kk.tools`: the five
  tools (`ada_memory_search`, `ada_remember`, `ada_forget`,
  `ada_session_recall`, `web_search`) moved include→exclude; new
  `env_knobs: {ADA_SESSION_PRIME: "1", ADA_PRIME_SKIP_HISTORY: "1"}`;
  `tool_profiles` field docs + `bench_profiles` comments updated;
  `kk-parity` include/exclude re-mirrored to the new prod surface (its
  env_knobs deliberately kept at pre-pilot `SKIP_HISTORY=0` — control arm).
- `scripts/ada/render-tool-profiles.py` — new `env_knobs` support: renders
  a second managed block (`ada-env-knobs`, same marker format as
  kk-bench-env.py) for person profiles; absent = unmanaged, `{}` = cleared.
  kk-bench-env.py remains dev-only and untouched.
- `tests/ada/test_render_tool_profiles.py` — new, 9 tests.
- `tests/ada/test_bench_profile_parity.py` — comments/assertions updated
  for post-promotion semantics (all green).
- `docs/assessments/kk-cms-only-pilot-plan.md` — status → APPROVED+APPLIED.
- `docs/ssot/jobs/ada/2026-11-26-kk-cms-only-pilot-apply.yml` — full apply
  record, evidence, pending items, rollback.

## Live state (idc03)

- `~/.config/secrets/kk-ha/backend.env` re-rendered via
  `render-tool-profiles.py --host idc03 --apply`; snapshot at
  `backend.env.bak.20261126T060430Z` (last-5 rotation).
- `ada-kk.service` restarted 13:05→13:06 +07; `/api/health` → `ok:true`,
  `degraded:false`. Env knobs live: `ADA_SESSION_PRIME=1`,
  `ADA_PRIME_SKIP_HISTORY=1`.
- Effective session surface verified from env + ada-voice tool-lint:
  include=21/exclude=36, all 5 drops excluded, 19 resolvable tools offered
  (`wp_read`/`wp_update` are stale include names — tools.d drop never
  installed on idc03, pre-existing and harmless).
- `render-tool-profiles.py --host idc03 --check` → UNCHANGED both lanes
  (zero drift once this branch merges).
- Side effect disclosed on card: `tony-ha/backend.env` also re-rendered —
  only retired a dead hand-written `ADA_EXCLUDED_TOOLS` line already
  overridden by the managed block; functionally a no-op, no tony restart.

## Pending (needs humans / time)

- LINE smoke: one message in the kk-ha group → sane Kaewta reply. Yomi's
  LINE session is expired (needs phone re-login); webhook can't be
  synthesized. KK's first real message doubles as smoke.
- Daily checks 3–7d per pilot plan: health, covered CMS recall, honest
  miss, session-audit review. Keep-or-revert at window end.
- Rollback path documented in the job record (env snapshot or SSOT revert
  + re-render + restart; no data touched).

## Verify

- `python3 scripts/ada/render-tool-profiles.py --host idc03 --check`
- `ssh idc03 'systemctl --user is-active ada-kk.service; curl -s
  http://127.0.0.1:8007/api/health'`
- `uv run --with pytest --with pyyaml python -m pytest
  tests/ada/test_render_tool_profiles.py tests/ada/test_bench_profile_parity.py
  tests/ada/test_kk_bench_env.py -q` → 21 passed

lessons:
- render-tool-profiles.py --apply touches EVERY profile on the target host,
  not just the changed one — it converged a stale hand-written env line on
  tony-ha/backend.env as a side effect. Snapshot or diff-check sibling
  env files before prod --apply runs.
- /api/tools on ada-voice lists the RAW runner surface, not the
  session-filtered declarations — verify effective tools by parsing the
  env managed block + tool-lint collect_surface, not that endpoint.
- YAML job/SSOT files: "word: value" inside plain scalars and list items
  breaks parsing twice over — quote multi-word pending items.
- kk-parity bench profile must mirror persons.kk.tools include/exclude —
  promoting a bench surface to prod requires re-mirroring parity in the
  same change or test_bench_profile_parity fails.
