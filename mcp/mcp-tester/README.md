# mcp-tester

MCP-compatible FastAPI service that exercises critical HTTP endpoints in the Chaba stack and returns structured pass/fail summaries. It is intended to run alongside the rest of the `pc2-worker` stack so MCP clients (or humans via HTTP) can confirm the health of Glama/chat, meeting notes, Instrans, VAJA, and mcp0 before cutting previews or deploys.

## Features

- **Declarative test suites** – define HTTP checks (method, expected status, headers, retries, etc.) via JSON or environment variables. Built-in defaults cover the common `mcp-*` services.
- **Structured summaries** – every run captures latency, attempt count, HTTP status, and excerpts for failing services.
- **MCP tools** – expose the suite via `.well-known/mcp.json` with `list_tests` and `run_tests` tools so Claude Desktop or other MCP clients can invoke it hands-free.
- **History endpoint** – retrieve the latest run to share in runbooks or dashboards.

## Getting started

```bash
cd mcp/mcp-tester
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8330
```

`mcp-tester` reads the repository `.env` and the variables below. When running inside Docker, the compose stack passes `MCP_TESTER_PORT` and optionally a suite file.

### Key environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_TESTER_PORT` | `8330` | HTTP port exposed by FastAPI/uvicorn. |
| `MCP_TESTER_HOST` | `0.0.0.0` | Bind host. |
| `MCP_TESTER_ALLOW_ORIGINS` | `*` | Optional comma-separated CORS origins. |
| `MCP_TESTER_TARGETS` | _(unset)_ | Inline JSON array of test definitions. Useful for quick overrides during local runs. |
| `MCP_TESTER_SUITE_FILE` | _(unset)_ | Absolute path (inside the container) to a JSON file describing the suite. When provided, it augments or overrides inline targets. |
| `MCP_TESTER_DEFAULT_TIMEOUT_MS` | `5000` | Fallback timeout per request when a test omits `timeout_ms`. |
| `MCP_TESTER_VERIFY_TLS` | `true` | Toggle TLS verification for endpoints that rely on self-signed certs in dev. |

### Test definition schema

Each test entry supports the following fields (all optional except `name` and `url`):

```json
{
  "name": "glama-health",
  "url": "http://mcp-glama:8014/health",
  "method": "GET",
  "expect_status": 200,
  "description": "Glama gateway health endpoint",
  "timeout_ms": 5000,
  "retries": 2,
  "retry_delay_ms": 750,
  "allow_redirects": true,
  "verify_tls": true,
  "headers": {
    "X-Debug": "1"
  }
}
```

Placeholders such as `{{DEV_HOST_BASE_URL}}` are expanded with matching environment variables at load time, making it easy to reuse the same suite between dev-host and production mirrors.

See [`tests.example.json`](./tests.example.json) for a ready-made suite that targets the default `pc2-worker` stack.

### HTTP API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Service health plus metadata about the latest run. |
| `GET` | `/tests` | List all loaded test definitions. |
| `GET` | `/tests/latest` | Retrieve the most recent run summary (if any). |
| `POST` | `/tests/run` | Execute the suite. Body supports `tests`, `fail_fast`, `timeout_ms`, `retries`, and `retry_delay_ms`. |
| `GET` | `/tools` | Tool metadata for MCP clients. |
| `POST` | `/invoke` | Execute `list_tests` or `run_tests` tools. |

### Docker / Compose

The `pc2-worker` compose stack now ships with an `mcp-tester` service under the `mcp-suite` profile. Enable it alongside the rest of the MCP services:

```bash
docker compose --profile mcp-suite up -d mcp-tester
```

Override the suite by binding a JSON file into the container and pointing `MCP_TESTER_SUITE_FILE` to that path.

## MCP tools

| Tool | Description |
| --- | --- |
| `list_tests` | Returns every test definition the server loaded, including expanded URLs. |
| `run_tests` | Executes the suite (or a subset) and returns the structured summary shown by `/tests/run`. Arguments mirror the HTTP API body. |

Example invocation payloads:

```json
{ "tool": "list_tests", "arguments": {} }
```

```json
{
  "tool": "run_tests",
  "arguments": {
    "tests": ["mcp0-health", "glama-health"],
    "fail_fast": true
  }
}
```

## File layout

```
mcp/mcp-tester/
├─ Dockerfile
├─ main.py
├─ requirements.txt
└─ tests.example.json
```

Feel free to copy `tests.example.json` to `tests.pc2.json`, tweak the URLs, and mount it into the container for environment-specific suites.

## Automation & DevOps integration

- **Scripted runs:** `scripts/run-mcp-tester.ps1` posts to `/tests/run`, prints a per-test summary, and exits non-zero if any check fails. This makes it safe to gate deployments or local previews.

  ```powershell
  pwsh ./scripts/run-mcp-tester.ps1 `
    -TesterBaseUrl http://127.0.0.1:8330 `
    -FailFast `
    -Tests glama-health,meeting-health
  ```

  The script supports `-TimeoutSeconds` and `-Tests` filters, mirroring the HTTP body fields.

- **mcp-devops workflow:** `verify-mcp-suite` (defined in `mcp/mcp-devops/src/workflowCatalog.js`) automatically calls the script above using `MCP_TESTER_BASE_URL`. Add it to preview/deploy sequences so MCP services are verified before publishing UI updates.

- **History retention:** The compose stack binds `./data/mcp-tester` into the container and points `MCP_TESTER_HISTORY_FILE` at `/data/run-history.ndjson`. A `.gitkeep` file is committed so the directory always exists; clean up the NDJSON file if it becomes too large, but keep the folder for persistence.
