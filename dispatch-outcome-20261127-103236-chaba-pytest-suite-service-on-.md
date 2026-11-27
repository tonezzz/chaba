# Dispatch outcome — chaba-pytest-suite 7 regressions (nightly-pytest-suite-7-regressions-fix)

## Result

All 7 reported failures fixed at source; targeted rerun green:

```
python3 -m pytest tests/ada/test_persona_photo_store.py \
  tests/colab/test_kk_mac_image_render_poc.py \
  tests/test_consultant_fixture.py \
  tests/test_litellm_consult_routes.py \
  tests/devnest/test_opencode_profiles.py -q
→ 122 passed, 21 subtests passed, 0 failed
```

`tests/devnest/test_opencode_profiles.py::JobLibrary::test_profile_envelopes_parse_and_lint`
was already passing — no change needed (item 5 of the card).

## What changed (6 files + 1 job trail)

1. **`tests/ada/test_persona_photo_store.py`** — `test_patch_states_healthy`
   now calls `materialize_main()` instead of `materialize_head()`. The
   ada-voice checkout on the suite host (tony-omen) sits on a stale
   feature branch (`feat/ada-ocb-ssot-search`, upstream gone), so a
   HEAD-based guard rots on branch drift. Drops target upstream `main`;
   `materialize_main` prefers `origin/main` and falls back to HEAD —
   same pattern already used by `test_cast_loop_breaker.py`.

2. **`integrations/ada-voice/backend/tool_guide.persona-photo-store.patch`**
   and **`ssot.tool-surface.persona-photo-store.patch`** — regenerated
   against ada-voice `origin/main` c9a2f01. The old hunks anchored on
   `tool_guide.yml` EOF-after-`weather_station` (~line 764) and the old
   `coverage_debt` ordering; upstream grew to 931 lines (now ends with
   `ada_fleet_jobs`) and the debt list gained `ada_sweep`, `ada_lesson`,
   `ada_adobe_stock`. Same payload, new context. Verified
   `git apply --check` clean against both dell's `origin/main` (c9a2f01)
   and tony-omen's local `origin/main` (0a5dbd8) — all 6 drop patches
   apply on omen, so the guard reports all-`applies` there.

3. **`scripts/colab/packs/kk-mac-image-render-poc/inputs/render-request.json`**
   — restored the DISABLED TEMPLATE (blob `aed64103deb`, the version
   before commit `d2d648c2569`). That OPS-0037 WIP-rescue commit had
   swept up the *armed* one-shot request from the idc02 exec checkout:
   `status: approved`, Tony-approved 2026-11-20, render window
   11-20→11-21 (lapsed 6 days ago), and a model revision truncated by
   one char (`...a7` vs pinned `...a7b`). An approved-status request
   checked into the template slot defeats the pack's fail-closed
   design — this is what broke all 4 colab tests. The armed variant is
   preserved in git history at `d2d648c2569` if the render record is
   ever needed.

4. **`fixtures/consultant-tasks.jsonl`** — repointed 10 `source:`
   citations from `docs/ssot/kanban/cards/<id>.yml` to
   `docs/ssot/kanban/cards/archive/<id>.yml`. The cards were archived,
   not deleted. `source` is provenance-only — `consultant-bench.py`
   never reads it; only the on-disk existence test does.

5. **`tests/test_litellm_consult_routes.py`** — the fallback-target
   scan now unwraps dict legs (`{model: x, disable_fallbacks: true}`)
   to their model name. The eval-judge lane pins dict legs to block
   litellm's recursive fallback expansion (silent free-tier retry) —
   that's the real config schema and the test predated it. The
   assertion is unchanged: `consult-*` aliases must appear neither as
   fallback sources nor targets, and a dict-leg consult alias would
   still be caught.

6. **`docs/ssot/jobs/ops/2026-11-27-chaba-pytest-suite-7-regressions.yml`**
   — job trail with full root causes and verification evidence.

## Notes / follow-ups

- Outcome commented on `nightly-pytest-suite-7-regressions-fix` and
  `timer-alert-tony-omen-chaba-pytest-suite`. Consumer proof = next
  `chaba-pytest-suite.service` run on tony-omen after merge.
- tony-omen's ada-voice checkout drift (feature branch + stale
  `origin/main` 0a5dbd8 vs remote c9a2f01) is worth a hygiene look but
  is not blocking — `materialize_main` made the guard immune to it.
- `.dispatch-scratch/` in this worktree contains tracked leftovers from
  a prior dispatch (ansible-mirror, nestroot media); I briefly deleted
  it by mistake and restored via `git restore` — verified intact.

lessons:
- Patch-guard tests for staged drops must materialize origin/main, not checkout HEAD — suite hosts park ada-voice on stale feature branches.
- `git checkout <commit> -- <file>` stages the change; `git reset` after if you want a uniform unstaged tree.
- `.dispatch-scratch/` is TRACKED in this repo (prior dispatch leftovers) — never rm -rf it; restore with `git restore` if touched.
- Unified-diff patches rot silently when upstream appends after the anchor — regenerate against current origin/main rather than retrying.
- litellm router_settings.fallbacks legs can be dicts ({model, disable_fallbacks}) — set-iterating them raw raises unhashable-type TypeError.
