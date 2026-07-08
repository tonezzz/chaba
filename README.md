# Gaussian Splatting Docker

A multi-container Docker environment for experimenting with **3D Gaussian Splatting** variants side-by-side.

## Included Implementations

| Container | Method | Repo |
|-----------|--------|------|
| `3dgs` | Original 3DGS (Kerbl et al. 2023) | graphdeco-inria/gaussian-splatting |
| `nerfstudio` | gsplat / splatfacto | nerfstudio-project/nerfstudio |
| `variants` (VARIANT=2dgs) | 2D Gaussian Splatting | hbb1/2d-gaussian-splatting |
| `variants` (VARIANT=mip) | Mip-Splatting | autonomousvision/mip-splatting |
| `variants` (VARIANT=gof) | Gaussian Opacity Fields | autonomousvision/gaussian-opacity-fields |
| `colmap` | COLMAP SfM preprocessing | — |
| `john` | John the Ripper (Jumbo) | openwall/john |
| `jupyter` | JupyterLab research notebook | — |

---

## Prerequisites

- **Docker** 24+
- **NVIDIA Container Toolkit**
- GPU with CUDA 11.8+ support (≥8 GB VRAM recommended)

```bash
# Install nvidia-container-toolkit (Ubuntu)
sudo apt install nvidia-container-toolkit
sudo systemctl restart docker

# Verify
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

---

## Quick Start

### 1. Build all images

```bash
chmod +x scripts/*.sh
./scripts/build_all.sh
```

### 2. Prepare your scene

**From images:**
```bash
./scripts/prepare_scene.sh --images /path/to/your/images --output ./data/my_scene
```

**From video:**
```bash
./scripts/prepare_scene.sh --video /path/to/video.mp4 --output ./data/my_scene --fps 2
```

### 3. Train

```bash
# Original 3DGS
docker compose run 3dgs train -s /data/my_scene -m /outputs/my_scene --iterations 30000 --eval

# Nerfstudio splatfacto
docker compose run nerfstudio train --data /data/my_scene

# 2D Gaussian Splatting
docker compose run -e VARIANT=2dgs variants train -s /data/my_scene -m /outputs/2dgs_scene

# Mip-Splatting
docker compose run -e VARIANT=mip variants train -s /data/my_scene -m /outputs/mip_scene
```

### 4. Train all variants (benchmark)

```bash
./scripts/train_all.sh /data/my_scene /outputs
```

### 5. Compute metrics (PSNR / SSIM / LPIPS)

```bash
./scripts/benchmark.sh /outputs
# Results → /outputs/benchmark_results.csv
```

### 6. Render

```bash
docker compose run 3dgs render -m /outputs/my_scene
```

### 7. John the Ripper (Jumbo)

```bash
# Build only the John image
docker build -t gaussian-splatting-john:latest docker/john/

# Run self-test
docker compose run john test

# Crack a password hash file placed in ./data/hashes.txt
docker compose run john --wordlist=/usr/share/dict/words /data/hashes.txt

# Open a shell inside the John container
docker compose run john shell
```

### 8. Nerfstudio web viewer

```bash
docker compose run nerfstudio train --data /data/my_scene
# Open: http://localhost:7007
```

### 9. Export .splat / .ply

```bash
docker compose run nerfstudio export --load-config /outputs/nerfstudio/.../config.yml
```

---

## Research / Development

Mount source code as a volume for live editing:

```bash
# Clone the source you want to modify
git clone --recursive https://github.com/graphdeco-inria/gaussian-splatting src/gaussian-splatting

# The docker-compose.yml already mounts ./src/gaussian-splatting → /workspace/gaussian-splatting
docker compose run 3dgs shell
# Now edit files locally in your IDE, changes reflect immediately in the container
```

### JupyterLab

```bash
docker compose up jupyter
# Open: http://localhost:8888
# Notebooks are in ./notebooks/
```

---

## Directory Structure

```
gaussian-splatting-docker/
├── docker/
│   ├── base/           # Shared CUDA + Python base image
│   ├── 3dgs/           # Original 3DGS image
│   ├── nerfstudio/     # Nerfstudio + gsplat image
│   ├── variants/       # 2DGS + Mip-Splatting + GOF image
│   └── colmap/         # COLMAP SfM preprocessing image
├── docker-compose.yml
├── .env                # Default environment variables
├── data/               # Input scenes (bind-mounted)
├── outputs/            # Training results (bind-mounted)
├── notebooks/          # JupyterLab notebooks
├── src/                # Source code mounts for dev (gitignored)
└── scripts/
    ├── build_all.sh        # Build all images
    ├── prepare_scene.sh    # COLMAP pipeline helper
    ├── train_all.sh        # Train all variants on one scene
    └── benchmark.sh        # Compute PSNR/SSIM/LPIPS
```

---

## Benchmark Reference (Mip-NeRF360)

| Method | PSNR ↑ | SSIM ↑ | LPIPS ↓ | Train Time |
|--------|--------|--------|---------|------------|
| 3DGS   | ~27.2  | ~0.815 | ~0.214  | ~35 min    |
| Mip-Splatting | ~27.5 | ~0.820 | ~0.205 | ~40 min |
| 2DGS   | ~26.9  | ~0.802 | ~0.230  | ~45 min    |

*Results vary by GPU and scene.*

---

## Troubleshooting

**CUDA out of memory**: Reduce `--densify_until_iter` or lower `--resolution`

**COLMAP fails with few images**: Use at least 30–50 overlapping photos. Try `CAMERA_MODEL=SIMPLE_PINHOLE` for simple captures.

**X11 / SIBR viewer not working**: Use nerfstudio web viewer (`localhost:7007`) instead, or export `.ply` and open in [SuperSplat](https://playcanvas.com/supersplat/editor).
