# Dispatch outcome — gaussian-splatting-nest-video-poc

Session: dispatch-wt-20261124-163842 (tony-dell). Card:
`gaussian-splatting-nest-video-poc`. Commit `413aab25948` on
`dispatch/20261124-163842-research-and-prototype-the-sma` (not pushed).

## What was done

**Two nest-packs written, validated, submitted to `gdrive:ada-nest/packs/`:**

- `gaussian-splat-ply-orbit` — renders a known PLY to an orbit MP4 +
  still + timing/VRAM report via gsplat. `fetch`es the kk-mac-hibiscus-7k
  PLY cross-pack; only egress need is pip installs.
- `gaussian-splat-hibiscus-recon` — full photo→PLY lane on the pack
  contract: pycolmap 4.x (SIFT → exhaustive match → incremental mapping)
  → gsplat training (L1+SSIM, DefaultStrategy densify, SH schedule) →
  held-out PSNR/SSIM → `export_splats` PLY + orbit MP4 + metrics.json +
  report.md. Reads `datasets/gaussian/hibiscus-v1` from the Drive store.

**Colab was unavailable** — every managed T4 runtime stale ~18 days,
queue heartbeat dead, tunnel returns 403. Instead of idling, both packs
were prototyped end-to-end on **tony-omen (GTX 1650 4GB)** with a fresh
venv (torch 2.14.1+cu130 + `nvidia-cuda-nvcc` cu13 wheel + gsplat 1.5.3
JIT build):

- ply-orbit: 842,786-GS kk-mac PLY → 48f 640×384 MP4 in **2.75s**,
  0.51GB peak CUDA, non-black verified (luma 52–131 across orbit).
- recon: 14/14 COLMAP registration (10,111 pts, 145s) → 1500 steps →
  100,522 GS, held-out **PSNR 15.15dB / SSIM 0.420**, 584s wall,
  0.17GB peak — near the KK-Mac 7000-step full-res baseline
  (16.47/0.475) at 1/8 res on a 4GB card. 23.7MB PLY exported.

**Published to durable Drive storage**:
`gdrive:ada-nest/packs/gaussian-splat-poc-omen-20261124/` — README,
ply-orbit/ (mp4+png+reports), recon/ (ply+mp4+png+metrics+report),
eval/ (LTX-EVAL.md + consistency.json).

**LTX shot-consistency eval** (`eval/LTX-EVAL.md`): inter-frame metrics
show the comparison is not rankable by SSIM/flow (orbit = real camera
motion, LTX = near-static generation). Verdict: **promising, unproven** —
GS plates are geometrically consistent by construction; the real A/B
(i2v plate conditioning vs t2v baseline, cross-shot identity distance)
needs a live T4 and an i2v-conditioning pack that doesn't exist yet.
Protocol documented in the eval doc.

**Trail**: `docs/ssot/jobs/nest/2026-11-24-gaussian-splat-poc.yml`
(results, contract notes, gotchas). Card comms posted.

## How to verify

- Packs queued: `rclone lsf gdrive:ada-nest/packs/gaussian-splat-ply-orbit/`
  and `.../gaussian-splat-hibiscus-recon/`; they claim on the next live
  nest worker (`nest-pack-submit.py --list` shows queued).
- Evidence: `rclone lsf -R gdrive:ada-nest/packs/gaussian-splat-poc-omen-20261124/`
- Local repro on omen: `~/gs-poc-test/run_ply_orbit.sh`, `run_recon.sh`
  (venv `~/gs-poc-venv`, data `~/gs-poc-data`).
- `python3 -m py_compile` both pack scripts; `nest-pack-submit --dry-run`
  validated both; SSOT validation passed on commit.

## Not done / blocked

- Colab T4 runs of both packs (queue dead — no worker to claim).
- The LTX plate-conditioning A/B (needs live GPU + new i2v pack).
- 4 pre-existing `test_kk_mac_image_render_poc` failures on this branch
  (approved request template + truncated model revision in
  `inputs/render-request.json`) — unrelated to this change.

lessons:
- nvidia-cuda-nvcc/cu13 PyPI wheels give a full CUDA toolkit layout but ship `libcudart.so.13` without the `libcudart.so` dev symlink — `ln -sf` it (and libcublas*) inside `nvidia/cu13/lib` before torch cpp_extension links.
- pycolmap 4.x dropped `SceneManager`; use `incremental_mapping -> dict[int, Reconstruction]`, poses via `image.cam_from_world().matrix()` (3x4 w2c), intrinsics via `camera.calibration_matrix()` + a `model_name`→dist-params table.
- gsplat `export_splats` wants raw params (log scales, logit opacities, wxyz quats, sh0 (N,1,3), shN (N,K,3)) and flattens shN channel-major = PLY `f_rest` order — matches a `channel`-order reader.
- Two processes hitting gsplat's lazy `load_extension` concurrently race the ninja build dir and kill each other — serialize first CUDA use.
- Do not pre-place files under a queued pack's `artifacts` globs — `verify_artifacts` would false-pass if the run fails early; publish local evidence under a separate pack dir instead.
