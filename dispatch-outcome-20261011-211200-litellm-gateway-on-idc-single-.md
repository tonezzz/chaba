# Dispatch outcome — LiteLLM gateway on idc (llm-gateway-litellm)

## Result: deployed + verified on idc03 (all acceptance items met)

LiteLLM (`ghcr.io/berriai/litellm:main-stable`) + Postgres 16 sidecar run as
rootless podman quadlets on idc03. Gateway binds **tailnet-only**
(`100.102.134.91:4000`), Postgres loopback-only (`127.0.0.1:5432`).
All provider keys ride env files on the host — nothing in git.

## What changed

**Deployed on idc03**
- `litellm.service` + `litellm-db.service` (quadlets in
  `~/.config/containers/systemd/`); config at `~/.config/litellm/config.yaml`
- Secrets generated once: `~/.config/secrets/litellm.env` (master/salt/pg/ui)
  and `litellm-keys.env` (virtual keys: ada $10/30d, chaba $5/30d, bench
  $2/30d; proxy cap $50/30d). `LITELLM_URL`/`LITELLM_KEY` appended to
  `mddb-gemini.env` so `ada-embed-bench.service` picks up the gateway leg.

**In this branch (commit `610aa3e3`)**
- `stacks/idc03/litellm/` — quadlets, `config.yaml` (19 deployments: real
  Gemini names paid+free+OR, ollama legs, 7 job classes), `deploy.sh`,
  `litellm-ledger.service/.timer` (disabled until merge), `stack.yml`
- `docs/ssot/infrastructure/ssot.llm-gateway.yml` — canonical routing
  table: job class → ordered model list w/ fallbacks (paid → free-tier →
  OpenRouter → ollama for text classes; embeddings stay in the gemini
  vector space only — ollama never chains)
- `scripts/litellm/` — `bench.py`, `daily-ledger.py`, `mint-key.sh`
- `scripts/ada/embed-bench.py` — gateway leg when `LITELLM_URL`/`LITELLM_KEY`
  set (ada-embed-bench proof lane)
- `scripts/ada/session-report.py` — `GEMINI_BASE_URL` env override
  (chaba proof lane, verified end-to-end)
- `scripts/ops/rotate-or-key.sh` — restarts litellm (it mounts
  `mddb-gemini.env` for `OPENROUTER_API_KEY`)
- `ssot.health.home.datastore.yml` health entry, `ssot.index.yml`
  registration, jobs trail `docs/ssot/jobs/infrastructure/2026-10-11-litellm-gateway.yml`

## Verified live

- `/health/liveliness` 200; `/v1/chat/completions` for all chat classes;
  `/v1/embeddings` returns correct 768d vectors with `dimensions` mapped;
  `/v1beta/...generateContent` and the real `google.genai` SDK via
  `GOOGLE_GEMINI_BASE_URL` both route + spend-log
- Fallback fired live: vision OR upstream failed → ollama moondream
  answered (then OR primary fixed to `google/gemma-4-31b-it:free` — the
  old llama-3.2-vision:free id is dead in OR's catalog)
- Virtual-key model ACLs enforced (403 out-of-list); spend metered
- **Bench:** gateway p50 ~1–2.4s/class vs ~1.1s direct OR; spend delta
  $0.000108/run. Embedding leg: **1.99s per 10-doc batch vs 15.6s
  sequential-OR direct** — LiteLLM batches arrays that OR's Vertex route
  rejects as raw calls; cosine 1.0 vs direct space
- **Ledger:** `daily-ledger.py --publish` →
  `ada-cms-pages/llm-gateway-spend-ledger` (psql source,
  `LiteLLM_SpendLogs`)

## Proof lanes

- ada: `ada-embed-bench.service` env armed — next weekly `--publish` run
  (post-merge) routes its embedding leg through the gateway
- chaba: `session-report.py` via `GEMINI_BASE_URL` + `LITELLM_KEY_CHABA`
  verified; `daily-ledger.py`/`bench.py` are standing gateway jobs

## Open items

- **Board request raised:** full ada cutover is blocked on
  `GOOGLE_GEMINI_BASE_URL` being process-global — it also reroutes
  Live-API voice websockets, which LiteLLM does not proxy. Recommended:
  patch ada-pi to pass `http_options.base_url` only on non-live clients,
  migrate ada-dev first.
- `litellm-ledger.timer`: enable post-merge —
  `ssh idc03 'systemctl --user enable --now litellm-ledger.timer'`
- mddb's `gemini-ollama-proxy` deliberately left direct (it hard-fails
  correctly on vector-space grounds); revisiting = spend visibility vs
  extra hop.
- Cosmetic: litellm logging-worker "httpx_response is None" noise on
  gemini native calls — calls + spend fine; upstream bug.

## How to verify

```bash
curl -sf http://100.102.134.91:4000/health/liveliness
KEY=$(ssh idc03 'grep -oP "^LITELLM_KEY_BENCH=\K.*" ~/.config/secrets/litellm-keys.env')
curl -s http://100.102.134.91:4000/v1/chat/completions -H "Authorization: Bearer $KEY" \
  -d '{"model":"tool-call","messages":[{"role":"user","content":"say ok"}]}'
ssh idc03 'systemctl --user status litellm litellm-db'
# CMS: ada-cms-pages/llm-gateway-spend-ledger, admin UI http://100.102.134.91:4000/ui
```
