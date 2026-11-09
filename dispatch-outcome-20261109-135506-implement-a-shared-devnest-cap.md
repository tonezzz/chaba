# Dispatch outcome — devnest-capacity-aware-dispatch (OPS-1002)

**Session:** dispatch-wt-20261109-135506-implement-a-shared-devnest-cap (tony-omen)
**Commit:** `7f4e4a37d4` on `dispatch/20261109-135506-implement-a-shared-devnest-cap` (no push, no deploy)
**Result:** implemented — shared capacity loop v2: sealed staging, full spec envelope, dual-lane observation, capacity ledger.

## What changed

**Sealed pack staging (`ready` marker — the approved atomic-3-3 fix, re-implemented; the earlier fix branch `fix/kk-mac-capacity-stage-atomic-20261103` / b02d243e0 was local-only and never reached this worktree):**

- `scripts/ada/nest_pack_ready.py` (new) — shared contract: `ready` = `{v, manifest_sha256, files, staged_at, staged_by}`; manifest = sha256 over sorted `relpath\tsize` lines of the remote file set, excluding transient entries (ready/done/failed/claim/**/out/**). Helpers: `remote_manifest`, `verify_and_mark` (copy → `rclone check --one-way` → marker last).
- `scripts/devnest/kk_mac_capacity_producer.py` — **filename-derived task_id skip**: `cat` only happens for specs that actually need staging (the Oct-31 4m-timeout root cause: ~70 cat calls before reaching new work). Terminal/sealed/claimed packs are skipped listing-only; an **unsealed unclaimed pack dir is retried** (re-stage + re-seal). Depth/new args **hard-clamped to 3/3**. `live_depth` counts only worker-visible packs (sealed or claimed) — staging debris no longer inflates queue depth.
- `scripts/ada/nest-worker.py` — `--ready-policy auto|required|optional` (default `auto`): `required` on `*kk-llm` remotes (absent/invalid marker ⇒ never claimable), `optional` elsewhere (absent = legacy, corrupt = never claim). Marker files ride the batched meta fetch; one `lsf --format sp` per marked candidate. Degrades safely if `nest_pack_ready.py` is absent on old deployments.
- `scripts/ada/nest-pack-submit.py` — manual staging now seals identically.
- `scripts/colab/queue-runner.py` (canonical for Drive) — optional marker validation in `load_packs`; corrupt seal skipped, unmarked packs unchanged (no stranding).

**Shared broker v2 (`scripts/devnest/devnest_capacity_broker.py`):**

- `normalize_spec()` enforces the full envelope: task_id (must equal filename stem), task_class, evidence|prompt, lane, model (default qwen3:8b for kk), expect, artifact (allowed roots only), timeout_s (0,3600], fallback (default `jevteam_hold`). Violations rejected, never silently repaired.
- `route_kk` writes the **normalized** spec to `<task_id>.json`; `route_colab` validates `pack_source` against the nest-pack-submit contract and seals the staged pack.
- `colab_state()` observes queue heartbeat age, fresh managed runtimes (duplicate-runner signal), pending pack depth, and `queue/JOBS.py` drift vs the repo canonical copy — recorded, never acted on (no launches, no runner duplication).
- `record_cycle()` appends one JSON per cycle to `gdrive:ada-nest/devnest/capacity/<utc>-<rand>.json` (unique filenames, no read-modify-write race). Best-effort; never blocks routing. `--budget-s 240` self-limits.

**`scripts/devnest/devnest_report_feed.py`** — emits evidence/timeout_s/fallback so produced specs are already normalized.

**Docs:** `docs/kb/devnest-capacity-aware-dispatch-procedure.md` (envelope, sealed-staging contract, observation/ledger, remaining gap), `docs/kb/jevnest-kk-mac-capacity-procedure.md` (sealed staging step), `ssot.jobs.yml` notes for both units, job record `docs/ssot/jobs/devnest/2026-11-09-shared-capacity-loop.yml`.

## Guarantees kept

No synthetic filler (only explicit inbox specs route), no duplicate Colab runners (broker never launches), no owner/quota gate bypass (KK admission + `DEVNEST_KK_MAC_ENABLED` authoritative), concurrency 1, 3/3 hard watermark.

## Verify

```
python3 -m unittest tests.devnest.test_kk_mac_capacity_producer \
    tests.devnest.test_devnest_capacity_broker \
    tests.ada.test_nest_worker_ready tests.ada.test_nest_worker_scan \
    tests.devnest.test_gdrive_roots
# 38 focused tests green; tests/devnest 249 green; tests/colab 70 green.
```

## Deployment notes (not done — dispatch worktree)

- tony-dell exec units pick this up via chaba-repo-sync + merge; unit args already `--max-depth 3 --max-new 3 --budget-s 90`.
- KK-Mac LaunchAgent `net.adanest.kk-llm-worker` must sync **both** `nest-worker.py` and `nest_pack_ready.py` together; on `required` policy a missing helper fails closed (skips everything) rather than claiming unsealed packs.
- Drive `queue/runner.py` + `queue/JOBS.py` update via the normal rclone deploy.
- Existing unsealed live pack dirs on kk-llm are healed by producer retry; unmarked legacy packs on ada-nest keep claiming (optional policy).

## Open gaps

- Upstream feeds beyond durable reports (audits, service deltas, held-out evals) still unimplemented — the "start with read-only reports" scope held.
- Ledger is raw per-cycle JSON; weekly JevTeam rollup aggregation not built (per-pack metrics already collected by `kk_mac_metrics.py`).
