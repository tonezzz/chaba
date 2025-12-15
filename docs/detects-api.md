# Detects vision API (`/test/detects`)

- **Source layout**: UI lives in `sites/a1-idc1/test/detects/`; the Glama vision proxy/API is `sites/a1-idc1/api/detects/` with its `.env` (GLAMA_URL/KEY, model, prompt, etc.).@sites/a1-idc1/api/detects/src/server.js#1-184
- **Health probes**: `GET /health` on the API process reports `status`, `model`, and `glamaReady`. Caddy forwards `/test/detects/api/*` to whatever listens on port `4120` (@sites/a1-idc1/config/Caddyfile#17-27).
- **Model selection**: the backend reads `GLAMA_MODEL_VISION` for the default and `GLAMA_VISION_MODEL_LIST` (comma-separated) for alternates. The UI calls `GET /test/detects/api/models` to populate the dropdown and sends the chosen model with each `/analyze` request. Update both env vars + restart the service whenever we add/remove models (currently `gpt-4o-mini-2024-07-18` default + `gpt-4.1-2025-04-14` alt).

## Local/dev-host workflow

1. `cd sites/a1-idc1/api/detects && npm install`.
2. Run with PM2 using the bundled ecosystem file: `pm2 start ecosystem.config.cjs --env development`. PM2 home: `C:\Users\hp\.pm2`; manage via `pm2 list`, `pm2 logs detects-api`, `pm2 restart detects-api`.
3. Dev-host proxy (`http://127.0.0.1:3100/test/detects/*`) points to `http://host.docker.internal:4120` by default, so once the PM2 process is up you can test end to end.
4. **Hands-off preview (detects-only):** `powershell -File scripts/preview-detects.ps1` brings up Docker (if needed), installs pm2, launches the detects API, waits for `/health`, validates `http://dev-host.pc1:3000/test/detects/api/health`, and prints the preview URL.
5. **Full /test preview (chat + agents + detects):** `powershell -File scripts/preview-test.ps1` boots the dev-host container, starts the Glama/chat API (4020), agents API (4060), and detects API (4120) via PM2, verifies each `/health` plus the proxied dev-host endpoints, then confirms the `/test` landing page before printing `http://dev-host.pc1:3000/test/`.

> **Current state (Dec 6 2025)** – Detects API is running under PM2 on the Windows workstation only; production `a1.idc1` still needs its own daemon before the public URL returns data.

## Production runbook (a1.idc1 VM)

1. Sync `sites/a1-idc1/api/detects/` plus its `.env` to `/var/www/a1/api/detects` (or similar).
2. `cd` into that directory, `npm install --production`.
3. Option A: run via PM2 (`pm2 start ecosystem.config.cjs --env production && pm2 save && pm2 startup`). Option B: create a systemd unit (patterned after `glama.service`) that sets `WorkingDirectory`, exports the env file, and runs `/usr/bin/node -r dotenv/config src/server.js`. Enable + start it (`sudo systemctl enable --now detects.service`).
4. Confirm port `4120` is listening (`ss -ltnp | grep 4120`), then hit `https://a1.idc1.surf-thailand.com/test/detects/api/health`.
5. If Caddy returns 404, it means nothing is bound to `127.0.0.1:4120` on the VM—double-check the service status (`journalctl -u detects.service -f`).

Keep the doc updated when the production daemon is live (and capture unit files under `sites/a1-idc1/config/` for version control).
