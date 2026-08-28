# chaba

A multi-purpose homelab stack: 3D Gaussian Splatting research, Frigate NVR traffic-camera surveillance, and the chaba.h3 static web/apps server.

- **master** branch (this repo) — 3DGS research stack, Frigate NVR, and web/Caddy stack
- **chaba.h3** branch — Plesk static site served at https://chaba.h3.gizmo-thailand.com/
- **chaba-omen** branch — omen host infrastructure (mcp-llama, ChatLocal/Neo Chat, NVR extras)

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
| `frigate` | Frigate NVR (AI-powered surveillance) | blakeblackshear/frigate |

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

## System Overview

### Hosts

| Host | Hostname | Role |
|------|----------|------|
| tony-omen | tony-omen.local | Docker host, GPU/NVR/web server |
| tony-dell | tony-dell.local | Secondary workstation / Barrier client |

### Stacks

| Stack | Compose file | Ports |
|-------|--------------|-------|
| 3DGS / Research | `docker-compose.yml` | 7007 (nerfstudio), 8888 (jupyter) |
| Frigate NVR | `frigate/docker-compose.yml` | 5000, 8554, 8555 |
| Web (Caddy) | `stacks/web/docker-compose.yml` | 8080, 8081 |
| AI (llama-server) | `chaba-omen/stacks/ai/docker-compose.yml` | 8008 |
| ChatLocal | `chaba-omen/chat-uis/ChatLocal` | 3000 |
| Neo Chat | `chaba-omen/chat-uis/neo-chat` | 3001 |

### Web Apps (chaba.h3)

Track/Track2/Track3/Track4, Imagen/Imagen2, Cameras, Reef Riders, Yomi, Docs — see https://chaba.h3.gizmo-thailand.com/apps/

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

### 10. Google Drive integration

Run `scripts/setup_gdrive.sh` once on the Docker host. It installs `rclone`,
creates a Google Drive remote, and either mounts or syncs a Drive folder into
`./data/gdrive`. Every container already bind-mounts `./data:/data`, so the files
are visible inside at `/data/gdrive`.

```bash
# Interactive setup (creates rclone remote named 'gdrive')
chmod +x scripts/setup_gdrive.sh
./scripts/setup_gdrive.sh            # foreground mount at ./data/gdrive

# Or sync a specific Drive folder to ./data/gdrive
GDRIVE_SYNC_DIR=MyScene ./scripts/setup_gdrive.sh
```

Variables in `.env`:

- `GDRIVE_REMOTE_NAME` — rclone remote name (default: `gdrive`)
- `GDRIVE_MOUNT_POINT` — local mount target for the host script (default: `./data/gdrive`)
- `GDRIVE_SYNC_DIR` — optional remote folder to sync instead of live-mounting

### 11. Frigate NVR (IP Camera Surveillance)

Frigate runs as a separate Docker Compose stack in `frigate/` with local AI object detection.

```bash
cd frigate
docker compose up -d
# Open: http://localhost:5000
```

**Cameras:** `frigate/cameras.json` is the single source of truth for 34+ traffic and local cameras. Run `python3 frigate/generate_config.py` to regenerate `frigate/config.yml` and `camera-map.html`.

Config files:
- `frigate/docker-compose.yml` — container definition
- `frigate/config.yml` — Frigate configuration (cameras, detection, recording)

Ports:
- `5000` — Web UI
- `8554` — RTSP restream
- `8555` — WebRTC (TCP/UDP)

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
chaba/
├── docker/                 # 3DGS container Dockerfiles
│   ├── base/
│   ├── 3dgs/
│   ├── nerfstudio/
│   ├── variants/
│   └── colmap/
├── docker-compose.yml      # Main 3DGS + research stack
├── frigate/                # Frigate NVR stack
│   ├── docker-compose.yml
│   ├── cameras.json        # Single source of truth for cameras
│   ├── generate_config.py  # Generates config.yml + camera-map.html
│   └── config.yml          # Generated (do not edit)
├── stacks/web/             # Caddy web server + status-api + camera-control
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── public/             # Static files for 8080 apps
├── scripts/                # Build/train/gdrive helpers
├── notebooks/              # JupyterLab notebooks
├── data/                   # Input datasets
├── outputs/                # Training outputs
├── docs/                   # Project notes
└── .env                    # Default environment variables

Related worktrees:
- ../chaba-h3/   — chaba.h3 branch (Plesk static site)
- ../chaba-omen/ — chaba-omen branch (host infrastructure: mcp-llama, chat UIs)
```

---

## Disaster Recovery Plan

DR runbooks, backup sources, secrets inventory, and bootstrap checklist are maintained in the chaba.h3 docs app.

- Rendered: https://chaba.h3.gizmo-thailand.com/apps/docs/
- Source: `chaba-h3/public/apps/docs/data.yml` (and `tony-omen/data.yml`, `tony-dell/data.yml`) in the `chaba.h3` branch

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
