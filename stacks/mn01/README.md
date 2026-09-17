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

- `ada-ha-tony.env` — `GEMINI_API_KEY`, `HOME_ASSISTANT_URL=https://tony-dell.taila0626a.ts.net:8123/`, `HOME_ASSISTANT_TOKEN`, `ADA_INSTANCE_ID=tony`, etc.
- `ada-ha-michael.env` — `GEMINI_API_KEY`, `HOME_ASSISTANT_URL=http://michael-ha:8123/`, `HOME_ASSISTANT_TOKEN`, `ADA_INSTANCE_ID=michael`, etc.
- `notebooklm-rest-api.env` — shared NotebookLM REST API config

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
