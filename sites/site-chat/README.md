# site-chat

Glama-backed chat panel served directly from node-1. Front-end is a simple static UI; back-end proxies requests to Glama using your API key.

## Environment variables (see `.secrets/node-1/site-chat.env`)

- `PORT` (default 3020)
- `GLAMA_API_URL` or `GLAMA_URL`
- `GLAMA_API_KEY`
- `GLAMA_MODEL` / `GLAMA_MODEL_LLM` / `GLAMA_MODEL_DEFAULT`
- `GLAMA_TEMPERATURE` (optional)
- `GLAMA_MAX_TOKENS` (optional)
- `SYSTEM_PROMPT` (optional custom instructions)

## Local development

```bash
npm install
npm run dev
```

Go to http://localhost:3020 and chat. `/api/health` reports readiness.

## Deployment

1. Add real env values under `.secrets/node-1/site-chat.env`.
2. Ensure `APPS` includes `site-chat` when running `scripts/deploy-node-1.sh` or in GitHub Actions.
3. After deploy, access the panel at `https://node-1.h3.surf-thailand.com/chat` (set Document Root/startup file accordingly in Plesk).
