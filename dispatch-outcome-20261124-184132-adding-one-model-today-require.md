# Dispatch outcome — model-route-registration-unify (OPS-1020)

Card: unify model registration across LiteLLM config → opencode provider
map → profile allowlists. Took option (a): hardened
`scripts/devnest/sync-opencode-models.py` (already existed since
2026-10-30), declared hourly timer jobs, added CI check-mode, and fixed
the live drift the new check immediately caught.

## What changed

- `scripts/devnest/sync-opencode-models.py` — provider-aware profile
  validation (only `litellm/` refs checked vs routes; `opencode/`,
  `openrouter/`, `ollama/` refs were false-flagged before), empty
  `model.allowed` = any-tier semantics fixed, `--write` refuses when the
  provider block lacks `options.baseURL` (was minting dead config),
  missing/unparseable opencode.json handled gracefully, `--from-api`
  key discovery (env list → secrets files), `--alert` deduped board-api
  /inbox entry on breaking findings.
- Profile drift fixed: `ops-remote-read` `litellm/gemini-3-flash` →
  `gemini-3.5-flash` (same typo Tony fixed in 5 profiles Oct 30); 
  `ssot-research` dropped `litellm/or-free-north-code` (route removed
  Nov 20, removal never landed in this file); `branch-code-supervised-
  pilot` default/allowed moved off never-existent `litellm/claude-
  fable-5.1` + `litellm/gemini-3-pro` onto the verified `or-` routes.
- `docs/ssot/infrastructure/ssot.jobs.yml` — new `opencode-models-sync`
  job on idc02 (:37) + tony_dell (:41): `--from-config` repo
  config.yaml → `--write --alert`. Route truth is repo config, not live
  /v1/models — virtual keys return per-key-filtered lists that would
  false-flag. Units rendered under `systemd/generated/`.
- `.github/workflows/repo-lint.yml` — new "OpenCode model drift check"
  step (`--check` vs repo config + jack-ide opencode.json), paths filter
  extended to evals/, ssot.jobs.yml, litellm config, systemd/generated.
- `tests/devnest/test_sync_opencode_models.py` — 13 tests, all pass.
- Trail doc: `docs/ssot/jobs/devnest/2026-11-24-model-route-registration-unify.yml`.

## Result / verify

- `sync-opencode-models.py --from-config stacks/idc03/litellm/config.yaml
  --check` → ok:true, 0 breaking (was 16 breaking findings before fixes).
- CI command with `--opencode stacks/idc02/jack-ide/opencode/opencode.json`
  → ok:true, no stale map entries.
- `render-jobs.py --check` → OK 122 jobs, 8 hosts; 4 new unit files
  rendered. Install on-host: `render-jobs.py --host idc02 --ids
  opencode-models-sync --install` (same tony_dell).
- `pytest tests/devnest/test_sync_opencode_models.py` → 13 passed;
  test_opencode_profiles + test_lane_gate + test_render_jobs → pass
  except two PRE-EXISTING failures on the worktree base unrelated to
  this diff: `test_lane_gate.py::test_s1_requires_opencode_lanes_env`
  and `test_runner_tooling_contract.py::test_pin_hashes_match_sources`
  (runner-agent.py sha drift vs manifest pin — fails on clean HEAD too).

## Notes for reviewer

- Timer jobs are declared + rendered but NOT installed on hosts — that
  needs `render-jobs.py --install` on idc02/tony_dell post-merge.
- `lane_gate.STRONG_MODELS`/`PRICE_TABLE` still name phantom
  `litellm/claude-fable-5.1`, `litellm/gemini-3-pro`,
  `litellm/gpt-5.2-codex` routes that never existed — harmless while no
  enabled profile allows them (none do post-fix) but an envelope could
  pass the strong-tier gate then die at provider. Flagged in the trail
  doc for Tony's call (planned native routes vs prune).
- Live `~/.config/litellm/config.yaml` on idc03 vs repo parity is not
  covered — deploy.sh owns that push.

lessons:
- LiteLLM virtual keys return per-key-filtered /v1/models — config.yaml model_list is the only safe fleet route truth for sync jobs.
- opencode provider refs are provider-prefixed (litellm/, opencode/, openrouter/) — cross-provider validation needs prefix filtering or it false-flags everything.
- sync-opencode-models.py --write must refuse provider blocks lacking options.baseURL — otherwise it mints dead config on unconfigured hosts.
- ssot.jobs.yml same-id-per-host pattern (log-shipper precedent) covers fleets without inventing new ids.
- test_lane_gate env-gate test + runner-tooling pin test were already red on this worktree base — check pre-existing failures before attributing to your diff.
