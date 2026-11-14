# Dispatch outcome — kk-mac-image-render-poc pack

Card: `adobe-stock-kk-mac-render-poc` · Branch: `dispatch/20261114-105957-build-the-first-bounded-image-`

## What was found

- The card's earlier implementation (branch `feat/adobe-stock-render-poc`, commits `40d04803c` + `97e62f5ec`) was **never pushed** and its objects are not in this clone, so the pack was rebuilt from the card spec plus recorded evidence (artifact glob fix to `out/*.png`, SDXL revision `462165984030d82259a11f4367a4eed129e94a7b`, CPU-fp32 VAE decode on MPS, `limits.min_disk_free_gb=30`).

## What changed (2 commits: `d59fa5206d8`, `a795991bc80`)

- `scripts/colab/packs/kk-mac-image-render-poc/pack.yml` — worker contract: `needs gpu_gb:0 / disk_gb:30 / ram_gb:24`, `timeout_s:3600`, artifacts `out/preflight.json`, `out/*.png`, `out/render-manifest.json`, `out/verdict.json`; `run_sh` execs `$HOME/.local/share/kk-mac-image-renderer/bin/python render.py --pack-dir $PACK_DIR` (fixed argv, no arbitrary shell).
- `scripts/colab/packs/kk-mac-image-render-poc/render.py` — stdlib top level (torch/diffusers deferred into `render_one`); 16 ordered fail-closed gates recorded in `preflight.json`: request_parses, request_approved, owner_approved, approval_recorded, adobe_upload_disabled, single_render, render_bounds, output_name_safe, prompt_present, render_window, venv_isolated, manifest_pinned, model_pin_match, snapshot_present, disk_floor, load_limit. Gate fail → `verdict.json` fail + exit 2 (worker marks failed, nothing uploaded, no retry). Render: SDXL fp16 on MPS from the pinned local snapshot (HF offline + `local_files_only`), CPU fp32 VAE decode, one seeded image, atomic PNG write; `limits.max_wall_seconds` enforced via SIGALRM. `--preflight-only` arms a safe gate check without rendering.
- `scripts/colab/packs/kk-mac-image-render-poc/inputs/render-request.json` — disabled template (`status: template_disabled`, `owner_approved: false`, `adobe_upload: false`, lapsed `render_window`, model pin to SDXL base 1.0 @ `46216598…94a7b`, `limits.min_disk_free_gb: 30`, `max_load_1m: 4.0`, `output_name: render.png`); documents the arming steps and the venv `model-manifest.json` contract.
- `tests/colab/test_kk_mac_image_render_poc.py` — 8 stdlib tests: pack.yml passes `nest-pack-submit.validate`, template disabledness, gate matrix (every fail-closed condition), approved-request pass on synthetic facts, main() evidence + nonzero exit.
- `docs/ssot/jobs/nest/2026-11-14-kk-mac-image-render-poc.yml` — job trail: contract, gate ids, verification, next gates.

## Verified

- `python3 -m unittest tests.colab.test_kk_mac_image_render_poc` — 8/8 pass.
- `python3 -m unittest discover -s tests/colab` — 78 ran, 1 skipped, OK.
- `scripts/ada/nest-pack-submit.py … --remote gdrive:ada-nest-kk-llm --dry-run` — valid.
- Live CLI run against the checked-in template — exit 2, `preflight.json` + `verdict.json` written with all 16 checks (10 failing on a non-KK host); no PNG, no manifest.

## Not done (next gates, per card)

- Push the branch, stage ONE approved request to `gdrive:ada-nest-kk-llm` during an owner-idle window (needs KK consent per lane policy), verify artifacts + SHA-256, land accepted PNG/manifest into `gdrive:ada-nest-adobe-stock` (`land-render.py --lane kk-mac-nest`), then qwen2.5vl QC before metadata/submission.
- KK-Mac-side prerequisite: `~/.local/share/kk-mac-image-renderer/model-manifest.json` must exist with `{model_id, revision, snapshot_dir?, required_files?}` — contract documented in the request template.
