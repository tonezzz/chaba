# Imagen — Archive Report

**Date:** 2026-10-07
**Status:** archived — dell-edge remnants removed, omen worker still exists
**Supersedes:** `ssot.apps.imagen2.yml`, `ssot.apps.imagen3.yml`,
`/tony-omen/apps/imagen*` routes, `apps/imagen2/` placeholder

## What Imagen was

Self-hosted image generation — a Stable Diffusion inference worker behind
a small static web UI, in three generations:

| Gen | Model | Where | State at archive |
|---|---|---|---|
| imagen (v1) | `runwayml/stable-diffusion-v1-5` (`enable_model_cpu_offload`, `enable_vae_slicing` for small GPU) | `imagen-inference` container on tony-omen, `chaba-h3_default` net | retired when v2 specced |
| imagen2 | `stabilityai/stable-diffusion-xl-base-1.0` + `madebyollin/sdxl-vae-fp16-fix` | gpu-queue worker `imagen2` on tony-omen `:8000` | worker def exists, paused |
| imagen3 | v2 backend, prompt-first UI | specced only, never built | spec only |

## Timeline

- **2026-07-23** — v1 live on tony-omen: UI at
  `http://192.168.1.48:8080/tony-omen/apps/imagen/`, API
  `/tony-omen/apps/imagen/api/{health,generate}` — 512x512 in ~62s.
  Full runbook: `docs/kb/task-tony-omen-imagen-website-2026-07-23.md`.
- **2026-08-05** — gpu-queue analysis: 5 imagen2 jobs, 20% cancel rate
  (`docs/reports/gpu-queue-cancellation-analysis.md`).
- **2026-08-25** — gpu-queue migrated tony-omen→tony-dell; GPU workers
  (llama, imagen2, txt2vid) **stayed on omen** (`100.75.102.88`) because
  they need its GPU. They pause — jobs queue — whenever the laptop is
  off-net/asleep. No move target exists.
- **2026-10-07** — route-health triage found the dell Caddy edge still
  carried omen-layout routes (`/tony-omen/apps/imagen/*` → docker-net
  `imagen-inference:8000`) that could never resolve on dell. Archived.

## What was removed vs kept

**Removed (cargo-culted omen layout, dead on dell):**
- `imagen-api` route `/tony-omen/apps/imagen/api/*` → `imagen-inference:8000`
- `imagen` static route `/tony-omen/apps/imagen/*` (dir never existed here)
- `imagen2-inference` service in `stacks/web/docker-compose.yml`
  (stale build context `chaba-h3/inference2`, GPU service that can't run on dell)
- `stacks/web/public/apps/imagen2/` — one-file placeholder, title said
  "fix or remove"
- `docs/ssot/apps/ssot.apps.imagen{2,3}.yml` + generated copies in
  `stacks/web/public/` and `public/docs/overview/` — content folded
  into this report

**Kept (live relationships):**
- `gpu-queue` route + SSOT — the queue is the real entry point;
  `imagen2` is job type priority 2
- `apps/health-check/health-check.js` — probes
  `tony-omen.local:8000/health` (the actual worker endpoint)
- `ssot.services.yml` gpu-queue note — authoritative worker topology
- `docs/kb/task-tony-omen-imagen-website-2026-07-23.md` — v1 runbook

## The v3 spec (preserved — never built)

Prompt-first UI, one-click presets; quality tags auto-appended
(`"masterpiece, best quality, highly detailed, sharp focus"`), negative
presets appended when missing; history-reuse; LLM-assisted prompt
improvement. Planned presets:

| Preset | Mode | Size | Steps | Notes |
|---|---|---|---|---|
| Quick | txt2img | 512² | 4 | test an idea |
| Improve | txt2img | 768² | 4 | higher quality, still fast |
| Best | txt2img | 1024² | 4 | best quality |
| ChangeClothes | img2img | 1024² | 12 | strength .65, guidance 8.5, prefix "change the clothes to " |
| BlueSkyScene | img2img | 1024² | 12 | strength .50, guidance 8.5, prefix "blue sky, clear sky, " |

## To revive

1. Start the worker on tony-omen: `docker compose -f
   chaba-h3-tony-dell/inference2 up -d --build` — needs the inference2
   dir recreated (mounts were removed; model weights under
   `~/.cache/huggingface` on the GPU host).
2. Submit jobs through gpu-queue (`imagen2` type) — the queue already
   schedules GPU workers with memory-awareness.
3. If a UI is wanted, build the v3 spec above as a static app under
   `/apps/imagen3/` hitting gpu-queue — not a direct worker proxy.

## Lesson embedded

Routes copied host-to-host by hand rot silently — the dell edge carried
omen's layout for months after the inference topology moved to
gpu-queue. `check-routes.py` + `expect_down` flags now catch this class;
the archive report keeps the knowledge so deletion is safe.
