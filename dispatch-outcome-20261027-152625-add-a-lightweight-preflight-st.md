# Dispatch outcome — kk-video-preflight-stage

Added a lightweight, CPU-safe preflight stage to the KK video queue
release. A new `*-preflight` pack validates the project package and every
dependent pack, writes a deterministic `preflight.json` + `preflight.md`,
and a `requires:` claim gate in both queue workers blocks
embedding/render packs until the preflight verdict is pass|warn.

## Changed

- `scripts/colab/pack-preflight.py` (new, canonical): deterministic
  validator — manifest, SHA-256/provenance (incl. project-id sha12
  binding + materialized-file rehash), required brief/scene/prompt/
  rights/qc docs, fact-vs-dream labels, symbolic-identity policy, Thai
  narration + Thai/English subtitle evidence, pack.yml contract,
  artifact globs, output privacy, gpu/disk/timeout declarations, paid/
  public-publish flag denylist. Emits byte-deterministic
  `preflight.json`/`.md` (no timestamps, atomic writes) with per-pack
  sha256 + `release_sha256`; exit 0 pass|warn, 2 fail.
- `scripts/colab/packs/kk-video-c9f99fee6146-preflight/` (new pack):
  `pack.yml` (gpu_gb:0, disk 2, timeout 600, fetch
  `projects/kk-video-c9f99fee6146/`), `policy.yml` (non-private check
  config), byte-copy of the validator.
- `scripts/colab/queue-runner.py`: `requires:` claim gate
  (`requires_unmet` — done marker; `*-preflight` reqs also need readable
  preflight.json verdict pass|warn, fail-closed on missing/unreadable/
  fail) + `order_packs` (Kahn requires-first ordering so CPU preflight
  drains before GPU dependents in one launch).
- `scripts/ada/nest-worker.py`: identical `requires:` gate for fleet
  workers (remote lsf/cat).
- `scripts/ada/nest-pack-submit.py`: `ram_gb` added to NEED_KEYS (embeds
  pack already used it), validation for `requires`/`fetch`/`publish`.
- `packs/kk-video-c9f99fee6146-{embeds,preview}/pack.yml`: `requires`
  added — embeds→preflight, preview→[preflight, embeds].
- `tests/colab/test_pack_preflight.py` (new, 36 tests): per-check
  pass/fail, determinism/idempotency, hash reference, real-release
  validation vs repo packs, nest-worker gate matrix, and real
  queue-runner e2e (ordering, pass→claim, fail→never-claimed).
- `docs/kb/colab-mcp-jobs.md`: `requires:` gate + preflight-pack contract.
- `docs/ssot/jobs/devnest/2026-10-27-kk-video-preflight-stage.yml`:
  runbook, verdict semantics, release/pack hash reference.

## Release hash reference (staged inputs only, 2026-10-27)

- embeds `cbedc925…`, preflight `6e120e44…`, preview `b9fa585f…`
- `release_sha256: b6e97c9f186a0cdec45c5662ba973060d77adfe73ccd72bc4f1ddaf2608eebb7`

## Verify

- `python3 -m unittest tests.colab.test_pack_preflight` — 36 OK
- `python3 -m unittest tests.colab.test_job_console tests.colab.test_runtime_registry tests.colab.test_gap_runner tests.colab.test_mcp_colab_control` — 39 OK, no regressions
- run_sh-equivalent smoke: verdict warn (unmaterialized source) → exit 0, real packs hashed.

## Not done (explicitly deferred — needs live Drive writes)

Staging is a release step for the next queue launch: mirror the project
docs to `gdrive:ada-nest/projects/kk-video-c9f99fee6146/` and re-submit
the three packs (`nest-pack-submit.py` or rclone copy). The running
queue snapshot is untouched by design — pack discovery happens once at
runner launch.
