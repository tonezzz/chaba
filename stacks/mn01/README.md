# mn01 Ada HA stack

Versioned, reproducible deployment of the Ada HA (Tony + Michael) voice PWA backends on `mn01`.

## Files

- `ada-ha-tony.service` — systemd user unit on `0.0.0.0:8002`
- `ada-ha-michael.service` — systemd user unit on `0.0.0.0:8003`
- `Caddyfile.mn01` — Caddy reverse proxy for `https://mn01.taila0626a.ts.net/apps/ada_ha_{tony,michael}/`
- `install.sh` — one-command install/refresh on `mn01`
- `verify.sh` — quick health/websocket check

## Secrets required

`/home/tony/.config/secrets/` must contain:

- `ada-ha-tony.env` — `GEMINI_API_KEY`, `HOME_ASSISTANT_URL=https://tony-dell.taila0626a.ts.net:8123/`, `HOME_ASSISTANT_TOKEN`, `ADA_INSTANCE_ID=tony`, `NOTEBOOKLM_REST_API_KEY` (the scoped `ada-tony` key), `NOTEBOOKLM_NOTEBOOK_IDS_JSON`, etc.
- `ada-ha-michael.env` — `GEMINI_API_KEY`, `HOME_ASSISTANT_URL=http://michael-ha:8123/`, `HOME_ASSISTANT_TOKEN`, `ADA_INSTANCE_ID=michael`, `NOTEBOOKLM_REST_API_KEY` (the scoped `ada-michael` key), etc.
- `notebooklm-rest-api.env` — optional shared NotebookLM REST config (e.g. `NOTEBOOKLM_REST_BASE_URL`). **Must NOT contain `NOTEBOOKLM_REST_API_KEY`** — it is loaded after the per-instance env files, so a key here silently overrides the scoped per-instance keys and every call fails `401 Invalid API key` (hit on 2026-09-17 when a stale pre-scoping key lived here).

These are **not** in git. Back them up via `scripts/backup-mn01.sh`.

## Install

```bash
ssh mn01
bash /home/tony/CascadeProjects/chaba/stacks/mn01/install.sh
```

Or from another host:

```bash
ssh mn01 'bash /home/tony/CascadeProjects/chaba/stacks/mn01/install.sh'
```

## Verify

```bash
ssh mn01 'bash /home/tony/CascadeProjects/chaba/stacks/mn01/verify.sh'
```

## Recovery

If `mn01` is down, use `chaba/scripts/recover-mn01.sh <target-host>` to recreate the services on `tony-dell` or `tony-omen`.
