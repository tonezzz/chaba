---
title: "tony-omen local Imagen website"
date: 2026-07-23
tags: [tony-omen, caddy, imagen, docker, ai]
status: completed
---

## Context

`tony-omen` (`192.168.1.48` via `tony-omen.local`) already runs a Caddy container (`web`) on port `8080`. It serves static files from `chaba/web/public` and proxies several paths to backend containers. There was no KB record of this local website setup or how the new `chaba-h3` Imagen app should be exposed.

## Goal

Serve the `chaba-h3/public/apps/imagen` UI and the `imagen-inference` Docker API under `http://192.168.1.48:8080/tony-omen/apps/imagen/`.

## Decisions / why

| Date | Decision | Reason |
|------|----------|--------|
| 2026-07-23 | Use the Caddy container (`web`) for `/tony-omen/apps/imagen` | It is the existing web server on `:8080`; `chaba-h3/proxy-server.mjs` was not the live process |
| 2026-07-23 | Mount `chaba-h3/public/apps/imagen` into `web` at `/srv/public/tony-omen/apps/imagen` | Caddy's `root` is `/srv/public`; the URL path mirrors the container path |
| 2026-07-23 | Connect the `web` container to the `chaba-h3_default` network | `imagen-inference` lives on that network, so `reverse_proxy imagen-inference:8000` works |

## Notes

- Caddy container: `web` (`caddy:2-alpine`)
- Caddyfile: `/home/tony/CascadeProjects/chaba/web/Caddyfile`
- Compose file: `/home/tony/CascadeProjects/chaba/web/docker-compose.yml`
- Static mount inside `web`:
  - Host: `/home/tony/CascadeProjects/chaba-h3/public/apps/imagen`
  - Container: `/srv/public/tony-omen/apps/imagen`
- API proxy path: `/tony-omen/apps/imagen/api/*` → strip `/tony-omen/apps/imagen/api` → `reverse_proxy imagen-inference:8000`
- Static URL: `http://192.168.1.48:8080/tony-omen/apps/imagen/`
- Health API: `GET /tony-omen/apps/imagen/api/health` (tested, 200 OK)
- Generate API: `POST /tony-omen/apps/imagen/api/generate` (tested 512x512 in ~62s)
- Inference model: `runwayml/stable-diffusion-v1-5` with `enable_model_cpu_offload()` and `enable_vae_slicing()` for small GPUs
- Start inference: `docker compose -f /home/tony/CascadeProjects/chaba-h3/docker-compose.yml up -d --build`
- Start/recreate Caddy: `docker compose -f /home/tony/CascadeProjects/chaba/web/docker-compose.yml up -d`
- Public Chaba status site (`chaba.h3.gizmo-thailand.com`) is a separate Plesk/nginx deployment

## Verification

- 2026-07-23: UI at `http://192.168.1.48:8080/tony-omen/apps/imagen/` returned `200` with `Server: Caddy`.
- Health API returned `200` `{"status":"ok","model":"runwayml/stable-diffusion-v1-5"}`.
- Generate API returned `200` with a base64 PNG (512×512, 10 steps).
- Confirmed separation from `chaba.h3.gizmo-thailand.com`, which returned `200` with `Server: nginx` and `X-Powered-By: PleskLin`.

## Blockers

None.

## Next steps

- Add Caddy basic auth or Plesk-style protection if `tony-omen/apps/imagen` should be private.
- Swap `MODEL_ID` in `chaba-h3/docker-compose.yml` if 512x512 generation is too slow on the small GPU.
