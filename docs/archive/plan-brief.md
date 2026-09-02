# chaba Lab Plan Brief

> **Note**: This is a historical planning document from 2026-08-05. Some information may be outdated, including TODO items, branch references, and infrastructure details. Current status should be verified in SSOT files and recent documentation. `chaba-omen` is now a stale/broken overlay; use `chaba` for Tony Omen host infrastructure.

## 1. Goal
Build and maintain a self-hosted lab on `tony-omen` that covers 3D Gaussian Splatting research, AI-powered IP-camera surveillance, a static Plesk web presence (`chaba.h3`), local LLM/AI endpoints, and a LINE conversation archive.

Keep responsibilities split between the three worktrees:
- `chaba` / `master` — generic baseline, shared documentation, and Frigate camera registry.
- `chaba-omen` / `chaba-omen` — host infrastructure: Caddy, status APIs, MCP servers, NVR runtime, AI/llama server.
- `chaba.h3` / `chaba.h3` — static-only Plesk site under `public/` (HTML, CSS, JS, YAML).

## 2. Worktrees & Sources of Truth

| Worktree | Branch | Purpose | Key Files |
|----------|--------|---------|-----------|
| `/home/tony/CascadeProjects/chaba` | `master` | Generic baseline + Frigate registry + shared docs | `frigate/cameras.json`, `stacks/web/`, `docs/plan-brief.md` |
| `/home/tony/CascadeProjects/chaba-omen` | `chaba-omen` | Host infrastructure: Caddy, APIs, NVR, MCP, AI | `stacks/`, `mcp/`, `frigate/` (runtime) |
| `/home/tony/CascadeProjects/chaba-h3` | `chaba.h3` | Static-only Plesk site | `public/` (HTML/CSS/JS/YAML) |

Rule: `chaba.h3` stays static-only. Do not commit Node/Docker backend files, `.env`, `inference/`, or `proxy-server.mjs` to `chaba.h3`.

## 3. Infrastructure (Deployed)

- **Host** `tony-omen.local`, Ubuntu/Debian, NVIDIA GPU, Docker 24+ with nvidia-container-toolkit.
- **Web**: Caddy on `8080` (`stacks/web`) and `8081` full-parity preview for `chaba-h3/public`. PHP dev server on `8123` for local Plesk-style tests.
- **NVR**: Frigate on `5000` with `frigate/cameras.json` as the single source of truth; `generate_config.py` produces `config.yml` and `camera-map.html`.
- **AI**: `mcp-llama` on `localhost:8008` (Phi-3-mini Q4_K_M, 2 GPU layers), exposed as OpenAI-compatible `/v1/chat/completions`.
- **Tooling**: Justfiles in both worktrees, slash workflows, `pre-commit` hook for `.js`/`.mjs`/`.py` syntax checks, Playwright e2e for `chaba.h3`.

## 4. Cameras & NVR

- 34 cameras in `cameras.json`, 4 groups, heading metadata for direction arrows on the map.
- VSTARCAM on `tony-dell.local:10554` (`/tcp/av0_0`) transcoded from H.265 to H.264; audio dropped.
- DOH Wowza streams use direct IPs `180.180.242.207/208` because the domain names fail TLS/SNI.
- Camera map (`camera-map.html`) has popup HLS/snapshot players, draggable pinned panels, fullscreen, follow-map, and off-screen hiding.
- Camera control panel runs at `:8090` for enable/disable/discover.

Status:
- [x] Camera registry in `cameras.json` with 34 cameras
- [x] Frigate `config.yml` generation via `generate_config.py`
- [x] Web map with pinned panels and heading arrows
- [ ] Upgrade detector from CPU to Coral / OpenVINO / TensorRT
- [ ] Tune detection zones / masks
- [ ] Add custom models for `animal` / `package` or remove those labels
- [ ] MQTT broker + Home Assistant integration
- [ ] Notifications / automations
- [ ] XMEye P2P DVR (blocked — no RTSP access)

## 5. Web Apps

### `chaba.h3` (Plesk static, `8081` preview)
- `/apps/track3/` and `/apps/track4/` — windsurfing course map, simulation, YAML course editor, PHP state persistence.
- `/apps/imagen2/` — SDXL-Lightning image generation UI, modular JS, queue, history.
- `/apps/reefriders/` and `/apps/reefriders-01/` — static WordPress mirror builders.
- `/apps/docs/` — data-driven docs.
- `/apps/overview/` — system status / plan page.

### `chaba-omen` / `8080` apps
- `/apps/yomi/` — LINE conversation viewer with AI summaries and media gallery.
- `/apps/camera-map.html` — served camera map.
- `/apps/chatllama/`, `/apps/chatlocal/`, `/apps/neo-chat/` — LLM/chat UIs.

Status:
- [x] `nav.js` shared navigation across `chaba.h3` and `8080` apps
- [x] Tailwind bright/dark themes and `apps.yml` data-driven landing page
- [ ] Commit the large `chaba.h3` WIP in logical chunks
- [ ] Remove transitional `imagen2.js` once browser-confirmed
- [ ] Add e2e coverage for `imagen2` and `track3`

## 6. AI / Automation

- `mcp-llama` provides OpenAI-compatible chat completions for Yomi summaries and MCP clients.
- `imagen2` uses SDXL-Lightning 4-step LoRA (`guidance_scale=0`, `num_inference_steps=4`) for ~49 s 1024×1024 images.
- Yomi media pipeline planned: image captioning, audio transcription (faster-whisper), video frame captioning.

Status:
- [x] `mcp-llama` running with GPU offload
- [x] `imagen2` modular frontend + Lightning backend
- [x] Yomi summaries and category filter chips
- [ ] Media caption / transcription for Yomi
- [ ] Update `imagen2` UI defaults for Lightning or offer a Lightning toggle

## 7. Verification / Health

- [x] Caddy `8080` and `8081` respond (`/`, `/apps/`, `/apps/track3/`, `/apps/docs/`, `/apps/imagen2/`)
- [x] Frigate Web UI on `5000`
- [x] `mcp-llama` `/health` and `/v1/chat/completions`
- [x] `imagen2` `/api/health`
- [ ] Full e2e pass via `just test-e2e` before each deploy
- [ ] Object detection visible in Frigate logs
- [ ] Home Assistant camera entities

## 8. Blockers

- **XMEye DVR** — P2P/QR-only, no RTSP without remote network access or credentials. Hold unless a VPN/tunnel or direct IP is obtained.
- **chaba.h3 working tree** — large uncommitted WIP (imagen2 modularization, track3/4, reef riders, docs move) must be committed in logical chunks before more parallel work.
- **Frigate detector** — still on CPU; 34 streams need hardware acceleration for reliable real-time detection.

## 9. Next Steps

1. Commit and push `chaba.h3` WIP in logical chunks (imagen2, track3/4, reef riders, docs relocation).
2. Add `inference/` and `inference2/` to `chaba-h3/.gitignore` or move them to `chaba-omen`.
3. Delete merged remote branches `docs/readme-update` and `sync-master-workspace`.
4. Fix `chaba-omen` submodule pointers for `chat-uis/ChatLocal` and `chat-uis/neo-chat`.
5. Install/switch Frigate to an accelerated detector (Coral / OpenVINO / TensorRT).
6. Add MQTT broker and Home Assistant camera/sensor integration.
7. Continue camera discovery through Longdo, Windy, and iTIC APIs.
8. Wire Playwright e2e (`just test-e2e`) into the `chaba.h3` deploy workflow.
9. Add image caption and audio transcription to the Yomi pipeline.
10. Keep `public/apps/overview/data.yml` in sync with this plan.
