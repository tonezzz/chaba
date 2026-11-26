---
category: operations
---

# Disk Space Management

## What it is

`/data` is the primary storage volume for Docker images, build cache, model weights, and HuggingFace downloads. It fills up faster than the OS disk. Two main reclaim targets: Docker build cache and HuggingFace model cache.

## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation.

## Overview

`/data` is the primary storage volume for Docker images, build cache, model weights, and HuggingFace downloads. It fills up faster than the OS disk. Two main reclaim targets: Docker build cache and HuggingFace model cache.

---

## Docker Build Cache Cleanup

### Command

```bash
docker builder prune --keep-storage 5GB --force
```

**What it does:** Removes cached build layers not referenced by any current image, keeping the most recent 5 GB of cache for faster rebuilds.

**Safety:** Safe to run at any time — only removes unreferenced cache layers. Running images and their layers are never touched.

**Expected reclaim:** Varies; freed **21.3 GB** in the first recorded run (2026-08-05), reducing `/data` from 70% → 63% used.

### When to run

- When `/data` usage exceeds ~75%
- Before a large `docker build` if space is tight
- Periodically (monthly is reasonable; build cache regenerates on next build)

### Check current cache size first

```bash
docker system df
```

Look for the "Build Cache" row.

---

## HuggingFace Model Cache

**Location:** `/data/cache/huggingface/` (~75 GB as of 2026-08-05)

### Active models (do not delete)

| Model     | Size  | Used by                                        |
| --------- | ----- | ---------------------------------------------- |
| SDXL-base | 13 GB | `imagen2-inference` service (active container) |

### Potentially removable (no active containers as of 2026-08-05)

| Model                        | Size   | Notes                                                                                      |
| ---------------------------- | ------ | ------------------------------------------------------------------------------------------ |
| LTX-Video-diffusers          | 27 GB  | No active container; largest reclaim opportunity                                           |
| Thai-Legal HF full-precision | 15 GB  | GGUF quantised version already at `/data/gguf` — this is the redundant full-precision copy |
| SDXL-Lightning               | 6.5 GB | No active container                                                                        |
| Juggernaut-XL                | 6.4 GB | No active container                                                                        |
| RealVisXL                    | 6.2 GB | No active container                                                                        |

**Total potentially removable: ~61 GB**

### Before deleting

1. Confirm no stopped containers are expected to restart using the model
2. Check GPU queue for pending jobs that reference it: `curl http://tony-omen.local:8080/api/gpu-queue/jobs | jq '.[] | select(.status == "pending") | .type'`
3. Deleting is permanent — models take hours to re-download

### Delete a specific model cache

```bash
# Find the exact subdirectory
ls /data/cache/huggingface/hub/

# Remove by model slug (example)
rm -rf /data/cache/huggingface/hub/models--stabilityai--sdxl-lightning
```

### GGUF models (separate location)

GGUF quantised models live at `/data/gguf/` and are managed independently from the HuggingFace cache. The Thai-Legal model at `/data/gguf/` is the active version; the HuggingFace full-precision copy at `/data/cache/huggingface/` is redundant.

---

## Ansible standard (2026-11-26)

For root-filesystem pressure, use the gated playbook rather than ad-hoc SSH
cleanup:

```bash
# 1. Verify (read-only) — always first
cd chaba/ansible
ansible-playbook -i inventory/hosts.yml playbooks/disk-remediate.yml \
  --check --diff --limit <host>

# 2. Fix only if needs_fix=true — --limit is mandatory
ansible-playbook -i inventory/hosts.yml playbooks/disk-remediate.yml \
  --limit <host> -e disk_remediate_apply=true
```

- Default is **dry run**; nothing is deleted without
  `-e disk_remediate_apply=true`.
- Thresholds come from `ssot.audit.hosts.yml` (`max_root_disk_percent`,
  default 90%) plus a 15 GiB absolute free floor.
- Cleanup candidates are rebuildable caches only: uv (8 GiB cap), pip (1 GiB
  cap), journal under `/var/log` (2 GiB cap). Never user documents; never
  personal caches on macOS member devices.
- If cleanup does not clear the threshold, escalate to the owner — there is
  no destructive fallback.
- Full procedure, safety rules and validation history:
  `docs/runbooks/disk-pressure-ansible-remediate.md`.

## Related Documentation

- **Ansible Disk Remediation Runbook**: `docs/runbooks/disk-pressure-ansible-remediate.md` - Assess / verify / fix SOP with dry-run defaults and SSOT thresholds
- **Home Directory Cleanup**: `home-directory-cleanup.md` - Partition migration cleanup methodology and root partition space recovery

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **2026**: 2026
