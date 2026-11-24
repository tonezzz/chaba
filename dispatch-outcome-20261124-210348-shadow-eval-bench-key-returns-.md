# Dispatch outcome — litellm-key-bench-dead-shadows-chaba

## What changed

Implemented card fix (b) in `scripts/devnest/shadow_eval.py`:

- **`bench_key_candidates()`** (new): ordered, deduped `(source-label, key)`
  candidates. Per-variable preference — every `LITELLM_KEY_BENCH` source,
  then `LITELLM_KEY_CHABA`, then generic `LITELLM_KEY` — across process env,
  `~/.config/secrets/litellm-keys.env`, and `litellm-chaba.env` (the last
  also fixes hosts like tony-omen that only carry the chaba env file, where
  `bench_key()` previously returned `""` entirely).
- **`bench_key(verify=True)`**: probes each candidate against
  `{LITELLM_BASE}/v1/models` with `_http_ok(..., want_2xx=True)` and returns
  the first 2xx — a dead BENCH key can no longer shadow a working CHABA.
  Falls back to first-present when nothing verifies (proxy down, all keys
  dead, `verify=False`, or `SHADOW_OFFLINE=1`), preserving offline/legacy
  behavior.
- **`probe()`**: checks `/health/liveliness` first and only spends candidate
  probes when the gateway answers; reuses the resolved key for the authed
  check and `/v1/models` fetch; records `secrets.bench_key_src` (provenance
  label, no secret material) so operators can see which source won.
- **`evaluate_rungs()`**: L2 DEGRADED secrets check now accepts
  `litellm-chaba.env` as well as `litellm-keys.env`.

Tests: 8 new `BenchKeySelection` cases in `tests/devnest/test_shadow_eval.py`
(dead-BENCH env/file shadowing, chaba.env candidate, fallbacks, dedup/order,
no-probe under offline/verify=False).

Job doc: `docs/ssot/jobs/devnest/2026-11-24-litellm-bench-key-probe.yml`.

## Result / verification

- `pytest tests/devnest/` — 369 passed.
- Live on tony-omen: `shadow_eval.py probe` → `litellm_authed:true`,
  `bench_key_src:file:litellm-chaba.env:LITELLM_KEY`, 44 litellm models;
  `matrix` → L2 PASS; synthetic S0 litellm `lane_gate.admit()` →
  `admit:true, reasons:[]` (previously `failed_provider:litellm`).
- End-to-end dead-key check: `LITELLM_KEY_BENCH=sk-deadbeef` → bench_key()
  probed it (401), then picked the litellm-chaba.env `LITELLM_KEY` (200).
- Direct curl: chaba key `/v1/models` → 200 (44 models); bogus key → 401.

## Not done

- Card fix (a) — rotate/re-create the BENCH virtual key in LiteLLM — is an
  admin/credential change on idc03 (master key, /key/delete + /key/generate),
  out of scope for a worktree dispatch and needing explicit approval. Fix
  (b) makes it unnecessary for correctness; rotation is optional hygiene.
- Repo-side change only; hosts pick it up via `chaba-repo-sync.timer`
  (exec-checkout sync). No service restart needed — shadow_eval/lane_gate
  run per-invocation.

## How to verify

```
python3 -m pytest tests/devnest/test_shadow_eval.py -x -q
python3 scripts/devnest/shadow_eval.py probe   # litellm_authed:true + bench_key_src
python3 scripts/devnest/lane_gate.py admit evals/opencode-lane/jobs/<job>.yaml
```

lessons:
- shadow_eval.bench_key() only knew LITELLM_KEY_BENCH/CHABA + litellm-keys.env — hosts with only litellm-chaba.env (tony-omen) got "" → litellm_authed:false; the chaba env file's LITELLM_KEY is now a last-resort candidate.
- Virtual keys are per-key filtered: /v1/models 200 ≠ the key can call every model — per-key allowlists still differ (BENCH alias-restricted).
- probe() resolves the bench key once and reuses it for the models fetch — don't call bench_key() twice per probe (each call can cost N candidate probes).
- secrets.bench_key_src in the probe dict records which source label won — check it before assuming which key a lane run billed.
