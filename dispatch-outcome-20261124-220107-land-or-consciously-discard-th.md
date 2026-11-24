# Dispatch outcome — land-or-consciously-discard worktree job artifacts

Card: `audit-miss-uncommitted-worktree-job-artifacts` (AUD-0973 / OPS-1288 family)
Branch: `dispatch/20261124-220107-land-or-consciously-discard-th` (5 commits on origin/master)

## What was done

Inventoried the four named worktrees on tony-macbook plus hunted the two
stray job records across every reachable host. Salvaged via file-level
extraction + 3-way merges onto fresh master — no direct master commits.

**Landed (5 commits):**

1. `bf7dc235bf` — ssot.procedures.yml: `nest-kk-mac-pack` +
   `storyboard-panel-to-cut` procedure registrations.
2. `d8178cc952` — kk-mac-video-render-probe: 6 nest job records,
   `build-kk-mac-scene-packs.py`, `kk-mac-i2v-runner.py`, 12 colab packs
   (ltx-mps-probe + storyboard-i2v probe/fullshot01/shot02–10, incl.
   hash-bound `inputs/shot*.pt` ~41MB), 5 tests, KK-Mac section appended
   to `docs/kb/colab-mcp-jobs.md`.
3. `6a91114b88` — kk-pdf-image-audit: source-audit report, 3 nest job
   records, 5 new packs (image-conditioning, pdf-image-audit,
   pdf-text-diff, r4-preflight, voice-clone), 2 tests; 3-way merged
   `preview/pack.yml` (kept master's `hf_repos`, took session's
   r4-preflight requires + shot-QC + edge-tts pin) and
   `test_pack_preflight.py`.
4. `adb8ae5ba2` — sacred-father: `storyboard-panel-to-cut-procedure.md`
   (final worktree version) + its nest job record.
5. `cb7f544952` — opencode-first-eval: devnest job record,
   `compile_proposal.py`, 10 plan job yamls, `plan-route-only` +
   `proposal-only` profiles, 3 reports, `evals/shadow/task` artifacts,
   `test_plan_compiler.py`; 3-way merged `lane_gate.py`,
   `opencode_profiles.py`, `test_lane_gate.py`,
   `test_opencode_profiles.py` onto master's newer runner
   (v2-standalone/run_profile_process/observer/watch kept; added
   `isolation.project_context=scratch`, `project_dir_for_run`,
   `run_opencode`, `classify_failure_reason`, ollama-qwen7b pricing).

Trail doc: `docs/ssot/jobs/board/2026-11-24-worktree-artifact-salvage.yml`
(full per-source landed/discarded ledger + verification).

## Consciously discarded (with reasons)

- `evals/opencode-lane/runs/**` — gitignored on master; ephemeral
  per-run output (65MB, incl. node_modules).
- `docs/ssot/jobs/nest/2026-10-29-kk-private-v2-preview.yml` (worktree
  copy) — master already has a NEWER version.
- `tests/colab/test_kk_video_preview_v2.py`, preview-v2 pack — already
  identical/complete on master.
- `evals/opencode-lane/jobs/s0-*.yaml` worktree versions — master newer.
- `docs/ssot/ssot.dev-system.assessment.yml` diffs in all worktrees —
  stale auto-assessment snapshots.
- `docs/kb/nang-sibsong-lxmf-contacts.md` — phantom: does not exist in
  the worktree, any worktree, any git object on tony-macbook, or any
  reachable host.
- `docs/ssot/jobs/ops/2026-11-03-ops1037-command-efficiency-apply.yml`
  and `docs/ssot/jobs/models/2026-11-03-kk-ltx23-gpu-format-audit.yml` —
  NOT FOUND anywhere reachable (all macbook worktrees' status +
  `git log --all`, filesystem find, and ~/CascadeProjects on
  idc02/idc03/tony-dell/tony-omen/mn01/con01). Owning worktrees likely
  cleaned before the audit. Nothing to land; regenerate if needed.

## Verification

- `pytest tests/devnest/test_opencode_profiles.py` → 89 passed
- `pytest tests/colab/test_pack_preflight.py` → 36 passed
- landed colab/devnest tests → 34 passed
- `test_lane_gate.py` → 58 passed, 1 failure that reproduces on clean
  origin/master (`Admit.test_s1_requires_opencode_lanes_env`) —
  pre-existing, unrelated.
- YAML parses on edited `ssot.procedures.yml` + merged `pack.yml`.

## Notes for review

- The 11 storyboard-i2v packs carry ~41MB of `inputs/shot*.pt` —
  declared, hash-bound inputs; shot01/02 exist only in that worktree.
  Landed for self-contained packs; candidate for later Drive-only
  extraction if repo size matters.
- Merge-sweep: branch is 5 commits ahead of origin/master; standard
  dispatch merge applies.

lessons:
- Card specs can list phantom files — verify existence on the host AND in git objects before planning salvage; nang-sibsong-lxmf-contacts.md and the two stray job ymls existed nowhere.
- Whole-dir tar copies can silently revert newer master files (s0-*.yaml, preview-v2 pack.yml) — diff every overlapping path against origin/master before staging.
- `git merge-file` 3-way per modified file worked well, but semantic conflicts need judgment: master's runner had evolved (v2-standalone, observer, watch_seconds) past the session's run_opencode — keep master machinery, graft the session's project_dir/classify_failure_reason features.
- evals/*/runs/ is gitignored on master — check .gitignore before assuming "untracked = land".
