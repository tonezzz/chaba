---
category: infrastructure
status: verified
created: 2026-11-25
source: auto-kb
title: "free_lane Offload Architecture (agent-local chain)"
tags: [litellm, gateway, freelane, offload, kkmac, ollama, routing]
---

# free_lane Offload Architecture (agent-local chain)

End-to-end wiring of the `free_lane` dispatch route to the `agent-local` alias on the LiteLLM gateway, offloading flash-lite traffic to kk-mac local models.

## Chain Topology

```
dispatch_repos.py:LANE_MODELS["free_lane"] = "litellm/agent-local"
       │
       ▼
~/.config/opencode/opencode.json  (provider.litellm.models["agent-local"])
       │
       ▼
LiteLLM Gateway (idc03:4000)  ── virtual key LITELLM_KEY_CHABA allowlist includes "agent-local"
       │
       ├──► kkmac shim (ollama-llama32-3b-kkmac)  @ :11447
       │
       ├──► ollama-qwen7b (ollama-qwen25vl7b-kkmac)  @ :11446
       │
       └──► idc03 local llama3.2  @ :11434
```

## Deployment Steps (verified 2026-11-25)

1. **Gateway config** (`/home/tony/.config/litellm/config.yaml`):
   - Added model `agent-local` → `ollama_chat/qwen2.5:32b` with fallback chain:
     - `ollama-llama32-3b-kkmac` (kkmac shim, :11447)
     - `ollama-qwen25vl7b-kkmac` (kkmac ollama, :11446)
     - `ollama/llama3.2:3b` (idc03 local, :11434)
   - Updated `LITELLM_KEY_CHABA` allowlist via `POST /key/update` to include `agent-local`

2. **opencode provider config** (`~/.config/opencode/opencode.json`):
   - Added `"agent-local": { "name": "agent-local (OPS-1363 free_lane offload alias, added 2026-11-25)" }` to `provider.litellm.models`

3. **Dispatch routing** (`scripts/board/dispatch_repos.py` line 166):
   - `LANE_MODELS["free_lane"] = "litellm/agent-local"`

4. **Gate quota** (`scripts/devnest/lane_gate.py`):
   - S1 quota raised 3 → 8 (commented: "raised 2026-11-25 (OPS-1363 repoint gate run)")

## Health Check (canonical)

```bash
ssh idc03 "for u in 'http://127.0.0.1:11447/health' 'http://127.0.0.1:11447/v1/models' 'http://127.0.0.1:11446/api/version' 'http://100.102.134.91:11434/api/tags'; do echo == \$u; curl -s -m 6 -o /dev/null -w '%{http_code}\n' \"\$u\"; done"
# All should return 200
```

## Live Test

```bash
source ~/.config/secrets/litellm-keys.env
curl -s -m 90 -H "Authorization: Bearer $LITELLM_KEY_BENCH" -H "Content-Type: application/json" \
  -d '{"model": "agent-local", "messages": [{"role": "user", "content": "Reply OK."}], "max_tokens": 10}' \
  http://100.102.134.91:4000/v1/chat/completions
# → HTTP 200, ~9s, "OK."
```

## Files Touched

- `/home/tony/.config/litellm/config.yaml` (gateway model + fallback chain)
- `~/.config/opencode/opencode.json` (provider models map)
- `scripts/board/dispatch_repos.py` (LANE_MODELS routing table)
- `scripts/devnest/lane_gate.py` (S1 quota)
- `evals/opencode-lane/profiles/ops-readonly/profile.yml` (model allowlist)
- `evals/opencode-lane/jobs/p1-ops-readonly-agent-local-idc02.yaml` (gate test job)

## Related

- OPS-1363 (kk-mac offload card)
- `docs/ssot/jobs/infrastructure/2026-11-25-kk-mac-flash-lite-offload.yml` (routing proposal)
- KB: LiteLLM Gateway Budget Guardrails