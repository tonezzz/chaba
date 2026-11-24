# Jack LLM stack — operator runbook (disposable)

## Architecture

```
opencode (provider: jack-litellm)
    │  OpenAI-compatible /v1/chat/completions
    ▼
LiteLLM gateway  ── alias jack-chat ──►  Ollama (qwen2.5:3b)
   :4000  loopback                        :11434 loopback
```

Single-node, loopback-only, no external providers. The whole stack is
disposable: `rollback.sh` returns it to pre-deploy state.

## Model choice

`qwen2.5:3b` (Q4_K_M, ~2 GB). Jack's M2 has 8 GB unified memory; a 3B
Q4 model leaves headroom for macOS + the LiteLLM proxy (~1 GB) while
still handling light coding/chat. Do NOT exceed 4B without re-checking
memory pressure.

## Deploy (container host)

1. `cp env.example .env` and set `LITELLM_MASTER_KEY` + `JACK_LITELLM_API_KEY`
   to freshly minted placeholders/real dev keys — never commit `.env`.
2. `docker compose up -d`
3. `docker exec jack-ollama ollama pull qwen2.5:3b`
4. `./healthcheck.sh` — all checks must PASS.

## Verify

`./verify.sh` runs unit tests + the mock failure-injection/rollback
drill. On a live host, `./healthcheck.sh` checks Ollama, LiteLLM
liveliness, a real chat round-trip, and the OpenCode provider config.

## Rollback

`./rollback.sh` — idempotent. Stops the mock or `docker compose down -v`,
removes generated `.env`, restores pre-deploy state. Run it any time;
running twice is safe.

## Health signals

- Ollama: `GET /api/tags` lists `qwen2.5:3b`
- LiteLLM: `GET /health/liveliness` → 200
- Chat: `POST /v1/chat/completions` model `jack-chat` returns content
- Config: `opencode/opencode.json` baseURL ends with the LiteLLM `/v1`

## Failure modes

- Ollama down → litellm chat fails (no fallback by design); healthcheck
  FAIL on layer 1+3.
- LiteLLM down → healthcheck FAIL on layers 2+3; opencode unusable.
- Wrong model name → litellm 404; fix `JACK_OLLAMA_MODEL` in `.env` and
  `litellm/config.yaml` together.

## Changing the model

1. Edit `JACK_OLLAMA_MODEL` in `.env` and the `${JACK_OLLAMA_MODEL}`
   reference stays valid — keep `litellm/config.yaml` unchanged.
2. Update this runbook's model section + `tests/test_stack.py` regex.
3. `ollama pull <new-model>`, restart litellm, re-run `./verify.sh`.
