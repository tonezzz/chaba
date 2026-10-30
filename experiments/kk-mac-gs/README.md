# KK-Mac native Gaussian smoke

Prepared runbook for a supervised Apple-Metal Gaussian Splatting experiment.
This directory is preparation only: it does not install software, start
training, wake the Mac, or change KK's machine.

## Candidate

First candidate: `mpsplat` (Metal/MPS, COLMAP input, 3DGS/2DGS/3DGUT,
PLY/viewer). Compare later with `msplat`, `gsplat-mlx`, or `splatx-metal`.
Do not use the existing CUDA `graphdeco`, `gsplat`, or Nerfstudio containers.

## Safe preparation already completed

- KK-Mac identity: Apple M4 Max, 36 GB unified memory.
- Current remote Python probe: PyTorch is not installed.
- No training environment is assumed.
- Target session is bounded: synthetic smoke first, then a tiny real scene.

## Owner-window protocol

Run only while KK is present and has approved the install/training window.
The operator must say which step is authorized:

```text
preflight-only
install-and-smoke
small-real-scene
```

The default is `preflight-only`. A failed admission check stops the run.

## Session plan

1. Read-only preflight: host identity, macOS, free disk, power, load, existing
   model/download processes, and whether a compatible Python/uv/Homebrew/Colmap
   toolchain exists.
2. Create an isolated environment under a declared experiment directory.
3. Install the selected native Metal implementation; do not modify Ada/KK
   production services or the existing Ollama lane.
4. Run a 300-iteration synthetic smoke and save a PNG, timing, and memory
   report.
5. If the smoke gate passes, prepare 20–60 downscaled images and run a small
   COLMAP scene. Never start this step implicitly.
6. Publish PLY, preview, metrics, source hash, package versions, and licenses.

## Acceptance gates

- identity is Mac16,9/M4 Max and owner window is active;
- disk headroom is at least 30 GB;
- no unrelated training/render/download is active;
- native Metal backend is selected;
- synthetic smoke produces a non-black preview and finite metrics;
- real-scene run has a COLMAP bundle and non-empty PLY;
- all artifacts land in a durable experiment directory/Drive pack;
- rollback is deleting only the isolated experiment environment and cache.

## Artifacts

```text
manifest.json
preflight.json
smoke/preview.png
smoke/metrics.json
real-scene/scene.ply
real-scene/preview.png
report.md
```

See `manifest.json` for the exact time and resource budget.
