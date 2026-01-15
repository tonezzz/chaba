# mcp-playwright

Model Context Protocol (MCP) service that wraps [Microsoft Playwright](https://playwright.dev/) to provide screenshot capture, browser diagnostics, and scripted smoke tests for our preview environments.

## Features

- `capture_screenshot` — navigate to a URL and emit both a PNG/JPEG file plus timing metadata.
- `browser_probe` — load a page and return HTTP status, duration, console logs, and failed network requests.
- `run_scenario` — execute JSON-defined flows (goto, waits, clicks, screenshots) from the `scenarios/` directory.

## Local development

```bash
cd mcp/mcp-playwright
npm install
npm run start   # binds to PORT (defaults 8025)
```

Environment variables are read from the repo `.env` plus anything you export. Key overrides:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8025` | HTTP port. |
| `PLAYWRIGHT_BROWSER` | `chromium` | Default engine (`chromium`, `firefox`, `webkit`). |
| `PLAYWRIGHT_HEADLESS` | `true` | Toggle headless/headful mode. |
| `PLAYWRIGHT_TIMEOUT_MS` | `15000` | Default action timeout in milliseconds. |
| `PLAYWRIGHT_SCENARIOS_DIR` | `./scenarios` | Where `.json` scenario files are read from. |
| `PLAYWRIGHT_OUTPUT_DIR` | `./output` | Where screenshots/artifacts are written. |

## Docker image

The `Dockerfile` extends the official Playwright Jammy image so browsers + dependencies arrive pre-installed. Build via the pc2 stack:

```bash
cd stacks/pc2-worker
docker compose --profile mcp-suite build mcp-playwright
docker compose --profile mcp-suite up -d mcp-playwright
```

Scenario files are mounted read-only from the repo (`../../mcp/mcp-playwright/scenarios`) and outputs are persisted under `./data/mcp-playwright/output`.

## MCP0 registration

`MCP0_PROVIDERS` now includes:

```
mcp-playwright:http://mcp-playwright:${MCP_PLAYWRIGHT_PORT}|health=/health|capabilities=/.well-known/mcp.json|tools=capture_screenshot+browser_probe+run_scenario
```

After the stack is up, hit `http://localhost:8025/health` (or the mapped port) to confirm readiness, then refresh MCP0 providers (`/providers?refresh=true`) so downstream agents can use the new tools.
