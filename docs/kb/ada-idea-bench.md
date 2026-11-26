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
- **Scenarios**: `ada-voice/tests/scenarios-live/*.yaml` — multi-turn scripts
  with `expect:` assertions (`calls_any`, `no_calls_except`,
  `response_contains*`, …). `tier: full` when they write real data.
- **Benchmark**: `ada-voice/tests/benchmark.yml` — named `suites:` +
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

`ada-voice/tests/scenarios-live/<name>.yaml`. Model: earlier turns seed state
(cms_publish_page, notes), later turns probe behavior. Assert honestly:

- `calls_any`/`no_calls_except` pin the tool surface the answer may use —
  this is the "tools report honestly" bar.
- `response_contains_any`/`response_not_contains` catch honest-miss and
  fabrication (e.g. invented `surf-thailand.com` URLs).
- `tier: full` if any turn writes; add the scenario `name:` to
  `write_allowed_in` in `tests/benchmark.yml` or the audit policy flags it.
- Validate: `python3 scripts/scenario-schema-check.py` (ada-voice root).

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
cd ~/CascadeProjects/ada-voice
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
| scenarios | `ada-voice/tests/scenarios-live/*.yaml` |
| suite + policy | `ada-voice/tests/benchmark.yml` |
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

### 2026-11-24 profile reconciliation

`persons.kk.tools` is the production surface and the source of truth:

- `kk-parity` is now an exact copy of it. A stale "restore" profile used
  to leave the dev lane on an October surface after every bench run.
- `kk-cms-only` is production minus the four memory tools and `web_search`,
  plus `cms_publish_page` kept **only** as a test-only seed writer for
  `kk_cms_only_seeded_recall` (prod dropped it 2026-10-14; `wp_post` owns
  member writes). `cms_edit` is gone — the suite never used it. The seed
  page carries marker `ZETA-KK-CMS-7741` and is deleted by the scenario's
  cleanup block, so it cannot contaminate later honest-miss probes.
  Public writes stay on the production `wp_*`/`cpt_post` path in both
  profiles.
- `tests/ada/test_bench_profile_parity.py` fails on any drift in those
  relationships, on include/exclude overlaps, or if a bench profile ever
  targets a non-`-dev` env file. Run it before touching either profile.
- Remove the test-only writers here **and** rewrite the seed scenario
  together when a production-real seed writer exists.

### 2026-11-24 — deterministic out-of-band seed (current state)

`kk_cms_only_seeded_recall` no longer asks the model to publish. It uses
`scenario-live.py`'s top-level `seed:` block, which writes the ZETA page
through MDDB `/v1/add` and verifies it via `/v1/search` before any turn;
a failed seed exits INFRA (3), never a scored recall turn. `cleanup`
deletes the page afterwards. MDDB meta values must be `[]string` —
`seed_payload()` normalizes scalars.

Run the bench with `MDDB_BASE_URL` exported so seeding and cleanup hit the
same MDDB as `--mddb`, e.g.
`export MDDB_BASE_URL=http://100.102.134.91:11023/v1`.

Two consecutive runs after this change scored **1.0** (3/3) at 21:04 and
21:06 — the suite now tests CMS recall rather than the model's
publish/confirm behaviour. `no_successful_calls_except` in
`scenario-live.py` ignores calls the lane gate refused; 5 unit tests in
`ada-voice/tests/test_scenario_live_harness.py` cover both behaviours.

### Creating a requested report for Kaewta

Prod Kaewta has no arbitrary CMS write tool (`cms_publish_page`/`cms_edit`
were dropped 2026-10-14; `wp_post`/`cpt_post` go to WordPress). A page she
must recall later is created out of band with
`scripts/ada/cms-report-add.py --lane kk ... --dry-run` then `--apply`.
The writer pins lane→collection, validates slug/domain/summary against SSOT,
refuses overwrite without `--overwrite`, posts with `contentMd` (the
camelCase MDDB field — `content_md` silently stores an empty body), reads
the page back, and regenerates `reports-index`. Card template:
`docs/ssot/templates/kk-cms-report-request.yml`; 6 unit tests in
`tests/ada/test_cms_report_add.py`.
