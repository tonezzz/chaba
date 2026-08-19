---
title: tony-omen Software Environment
description: Software environment, runtimes, and active projects on tony-omen machine
tags: [hardware, software, environment, tony-omen]
created: 2026-07-08
updated: 2026-08-11
category: troubleshooting
status: active
---

# tony-omen — Software Environment

**Scanned:** 2026-07-08
**Last Updated**: 2026-08-11

---

## Core Runtimes

| Tool | Version |
|---|---|
| Python | 3.14.4 |
| pip | 25.1.1 |
| Docker | 29.6.1 |
| Docker Compose | v5.2.0 |

---

## GPU / CUDA

| Item | Value |
|---|---|
| NVIDIA Driver | 595.71.05 (Open Kernel Module) |
| CUDA Version | 13.2 |
| GPU | GeForce GTX 1650 Mobile / Max-Q — 4 GB VRAM |

---

## Active Projects (as of 2026-08-11)

| Path | Description |
|---|---|
| `~/CascadeProjects/gaussian-splatting-docker` | Dockerised 3D Gaussian Splatting pipeline (3DGS, COLMAP, NeRFStudio). Renamed to `chaba` on GitHub: `https://github.com/tonezzz/chaba.git` |
| `~/CascadeProjects/chaba-kbman/mcp-kbman` | MCP server for KB management with search and workflow integration |
| `~/CascadeProjects/chaba` | Main Chaba project repository |

---

## Notes

- No conda environment detected (pure system Python)
- No Tailscale installed
- `~/GoogleDrive` mount directory exists and is mounted at `/home/tony/GoogleDrive`
- `~/post-install.sh` — bootstrap script for setting up a new Ubuntu machine (see `scripts/post-install.sh`)
- mcp-kbman provides KB management and search capabilities
- Personal KB at `/home/tony/GoogleDrive/Tony AI/KB/` for knowledge management