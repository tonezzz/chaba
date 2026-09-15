# AI Playground v0.2

A minimal AI playground: provider registry, model-aware routing, auto-categorised prompts, and a per-category leaderboard.

## Run

```bash
cd /home/tony/CascadeProjects/chaba/apps/dev/v0
node server.js
```

Open `http://localhost:8005` in a browser.

### Public URL (tony-dell)

A stable deployment is available behind the tony-dell Caddy reverse proxy:

```text
https://tony-dell.taila0626a.ts.net/apps/dev/v0/
```

- Backend: `systemctl --user status dev-miniapp-v0`
- Caddy: `systemctl --user status caddy-tony-dell`

## Provider setup

Copy `.env.example` to `.env`, fill in the keys for the providers you want to use, and source it before running the server:

```bash
cp .env.example .env
# edit .env
source .env
node server.js
```

| Provider | Required env | Notes |
| --- | --- | --- |
| `devin-stub` | none | Always works; prints a canned response. |
| `openai` | `OPENAI_API_KEY` | Uses `gpt-4o-mini`. |
| `claude` | `ANTHROPIC_API_KEY` | Uses `claude-3-5-sonnet-20241022`. |
| `ollama` | none (local) | Set `OLLAMA_HOST` and `OLLAMA_MODEL` if not the defaults. |
| `gemini` | `GEMINI_API_KEY` | Uses `gemini-2.5-flash`. |

## What it does

- Three tabs: **Play**, **Leaderboard**, and **Providers**.
- `playground.json` defines providers, models, category tags, and default per-category scores.
- As you type, the prompt is auto-categorised (`/api/categorize`) into job types like `code`, `reasoning`, `summarize`.
- The **Leaderboard** shows the best model for each job type.
- `server.js` serves the registry and routes the WebSocket prompt to the selected provider/model.
- Provider scripts in `providers/` stream responses back in near real time.
- History with run details and sample seed data on first load.

## Notes / v0 limitations

- This is a one-shot prompt wrapper. Each submit starts a fresh provider call and streams the response.
- Real providers require their respective API keys in `.env`. The `devin-stub` provider works without any auth.
- `ollama` must be running locally on `OLLAMA_HOST` (default `localhost:11434`).
- The default port is `8005`; set `PORT` to change it.
