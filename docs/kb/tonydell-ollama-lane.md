# docs/kb/tonydell-ollama-lane.md

## tony-dell Ollama Lane Documentation

### Overview
The tony-dell host (8c/14G batch host) runs Ollama as a **system** service
(`ollama.service`, enabled, `127.0.0.1:11434` loopback-only). Access from
idc03 is tunneled via `tonydell-ollama-tunnel.service` (user unit on
idc03), which forwards idc03 loopback port **11446** to tony-dell
`127.0.0.1:11434` — same pattern as `kkmac-ollama-tunnel.service`
(11445). LiteLLM routes (config: `stacks/idc03/litellm/config.yaml`):

- `chat-local` — `ollama_chat/qwen2.5:7b-instruct` @ `127.0.0.1:11446`
- `ollama-qwen7b` — same model, same tunnel
- `ollama-nomic-embed` — LB leg @ `127.0.0.1:11446`
  (other leg: idc03 ollama `100.102.134.91:11434`)

Deployed 2026-11-07 (card SYS-1082 `idc02-capacity-rearrangement`,
option `ollama-on-tony-dell`): idc02 was overcommitted — chat-local and
the second embed leg moved off it. idc02 ollama stays running for
direct/local consumers, clamped (`OLLAMA_MAX_LOADED_MODELS=1`,
`KEEP_ALIVE=5m`, `NUM_PARALLEL=2`).

---

### Setup & Capabilities
- **Service**: system `ollama.service` on tony-dell (not a user unit)
- **Network**: loopback-only (`127.0.0.1:11434`)
- **Tunnel**: `tonydell-ollama-tunnel.service` on idc03
  - `ssh -N -L 127.0.0.1:11446:127.0.0.1:11434 tony@tony-dell`
    (BatchMode key auth, `Restart=always`, `RestartSec=15`)
- **Models**: `qwen2.5:7b-instruct` (~4.7GB), `nomic-embed-text` (~0.3GB),
  `llama3.2:3b` (pre-existing)

---

### Operational Notes
- **Host sleep**: tony-dell is a desktop — if it sleeps, the tunnel and
  all `*:11446` routes die. chat-local keeps its `llama3.2:3b@ollama`
  (idc03) fallback; a dead nomic leg surfaces as LiteLLM LB errors on
  ~half of embed calls — watch `ollama-nomic-embed` error rates if
  embeds start failing.
- **Throughput**: 8 cores vs idc02's 4 — qwen7b should eval faster;
  `chat-local` consumers keep their deterministic/gemini fallbacks
  (`litellm_chat.py` callers) so a dead lane never stalls a job.
- **idc02 direct consumers**: anything hitting
  `http://100.123.163.11:11434` directly (not via LiteLLM) is
  unaffected — only LiteLLM routing moved.
