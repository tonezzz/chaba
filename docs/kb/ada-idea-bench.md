# Ada Idea Bench — dev-lane experiment procedure

Standard procedure for "bench my idea on kk-dev" (or any persona dev lane):
change the dev instance's tool surface / config, run live scenarios against
it, land the result in the benchmark report, restore parity.

First run: kk-cms-only memory experiment 2026-10-12 (idea: CMS is Kaewta's
only memory — tools honestly report availability, she answers honestly).

## Concepts (all existing machinery)

- **Persona lane**: `ada-kk-dev` on idc03 `:8009` (ws) — dev twin of `ada-kk`
  (`:8007`). Dev writes go to `-dev` collections; data never promotes.
  Spec: `docs/ssot/apps/ssot.apps.ada-persona-lanes.yml`.
- **Tool surface** ("buttons/dials/switches"): the env managed block
  `ADA_INCLUDED_TOOLS`/`ADA_EXCLUDED_TOOLS` in `~/.config/secrets/<env>.env`.
  Prod profiles come from `persons.<x>.tools`; experiment surfaces are
  `bench_profiles.<name>` in the same file
  (`docs/ssot/apps/ssot.apps.ada-persons.yml`).
- **Scenarios**: `ada-pi/tests/scenarios-live/*.yaml` — multi-turn scripts
  with `expect:` assertions (`calls_any`, `no_calls_except`,
  `response_contains*`, …). `tier: full` when they write real data.
- **Benchmark**: `ada-pi/tests/benchmark.yml` — named `suites:` +
  `write_allowed_in` policy list. A suite run writes one `kind: benchmark`
  doc into `ada-ha-scenario-reports` → shows on the auto-report page.

## The loop

### 1. Define the experiment surface

Add a `bench_profiles.<name>` entry in `ssot.apps.ada-persons.yml`:

- `instance`/`env_file`/`host` — the dev lane it targets (e.g.
  `kk-dev` / `ada-kk-dev.env` / `idc03`).
- `include:` — the tool keep-list for the experiment. EVERYTHING else is
  stripped — declare deliberately.
- `exclude:` — explicit drops (covers lint + documents intent).
- Also add a `*-parity` profile = the person's normal `include:` so the
  lane can be restored exactly (see `kk-parity`).

### 2. Apply the surface

```bash
python3 scripts/ada/kk-bench-env.py --list                # profiles
python3 scripts/ada/kk-bench-env.py --profile <name>      # dry render
python3 scripts/ada/kk-bench-env.py --profile <name> --apply
```

`--apply` merges the managed block into the env file on the host and
restarts the service. Restore afterwards:

```bash
python3 scripts/ada/kk-bench-env.py --profile kk-parity --apply
```

### 3. Write the scenario(s)

`ada-pi/tests/scenarios-live/<name>.yaml`. Model: earlier turns seed state
(cms_publish_page, notes), later turns probe behavior. Assert honestly:

- `calls_any`/`no_calls_except` pin the tool surface the answer may use —
  this is the "tools report honestly" bar.
- `response_contains_any`/`response_not_contains` catch honest-miss and
  fabrication (e.g. invented `surf-thailand.com` URLs).
- `tier: full` if any turn writes; add the scenario `name:` to
  `write_allowed_in` in `tests/benchmark.yml` or the audit policy flags it.
- Validate: `python3 scripts/scenario-schema-check.py` (ada-pi root).

### 4. Add a benchmark suite

```yaml
# tests/benchmark.yml
suites:
  <suite_name>:
    - <scenario_a>
    - <scenario_b>
```

Plus a cadence line under `cadence:` — bench suites are `on-request`
(they require the non-parity env, so never put them on a timer).

### 5. Run

```bash
# from a checkout with scripts/ + tests/ (tony-dell):
cd ~/CascadeProjects/ada-pi
python3 scripts/scenario-benchmark.py --suite <suite_name> \
  --url ws://127.0.0.1:8009/ws \
  --api-key "$(python3 -c 'import json;print(
      json.load(open("/home/tony/.config/secrets/ada-ha-kk-dev-keys.json")
      )["keys"][0]["key"])')" \
  --mddb http://100.102.134.91:11023/v1
```

Single scenario while iterating:
`scripts/scenario-live.py tests/scenarios-live/<file>.yaml --url ... -v`

Result: a `kind: benchmark` doc in `ada-ha-scenario-reports` (suite, score,
per-scenario status, transcript summary) — diff metas across runs to
measure change. `--report-cms` also writes a CMS report page.

### 6. Read it on the benchmark report

`ada-ha-scenario-reports` collection → reports-index → the auto-report
page. Suite name keeps runs comparable; rerun the same suite after model/
instruction changes for a like-for-like delta.

### 7. Restore

- `kk-bench-env.py --profile kk-parity --apply` (env + restart).
- `-dev` collections keep any seeded pages — disposable by design; delete
  if a run's seed would contaminate the next experiment.

## Preservation — what makes a rerun reproducible

Everything is committed data, not session state:

| Piece | File |
|---|---|
| experiment surface | `bench_profiles.<name>` in `ssot.apps.ada-persons.yml` |
| scenarios | `ada-pi/tests/scenarios-live/*.yaml` |
| suite + policy | `ada-pi/tests/benchmark.yml` |
| toggle mechanism | `scripts/ada/kk-bench-env.py` |
| this procedure | this file + `ssot.procedures.yml` index |

Re-run months later = apply profile → run suite → compare benchmark docs.
If the tool surface merged/renamed meanwhile, `render-tool-profiles.py
--lint` + the deploy lint flag the drift.

## kk-cms-only specifics (first experiment)

- Idea: Kaewta's ONLY memory = CMS reports. `ada_memory_search`,
  `ada_remember`, `ada_forget`, `ada_session_recall` dropped — plus
  `web_search` (a live-search fallback would mask honest misses; add it
  back to `include:` to bench "CMS memory + honest search" instead).
- Suite `kk_memory_cms`: seeded_recall (covered → cms answer),
  honest_miss (uncovered → says so, no fabrication), no_memory_leak
  (memory-seeking → no bank access attempted).
- Known gap: `cms_publish_page` stays in the surface, so a "confident
  invention" could still write a fabricated page — the scenario
  `no_calls_except` on probe turns catches it in the tool-call list.
