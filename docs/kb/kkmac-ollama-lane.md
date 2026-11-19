# docs/kb/kkmac-ollama-lane.md

## kk-mac Ollama Lane Documentation

### Overview
The kk-mac host runs Ollama services under the `adanest` account. Since ~2026-11-17 it binds `0.0.0.0` — reachable directly on tailnet `100.108.217.17:11434` (and LAN; narrowing to tailnet-only needs adanest plist access). The former loopback-only topology used `kkmac-ollama-tunnel.service` on idc03 (`ssh -L 127.0.0.1:11445 -> :11434`) — that unit is now **retired** (stopped+disabled after ~19k restart flaps) and kept on disk only as a documented fallback. The LiteLLM routes for these models are:

- `ollama-qwen32b-kkmac`
- `ollama-qwen38b-kkmac`
- `ollama-qwen25vl7b-kkmac`
- `ollama-llama32-3b-kkmac`

---

### Setup & Capabilities
From `docs/ssot/infrastructure/ssot.audit.hosts.yml`:
- **Account**: `adanest` (non-root)
- **Network**: tailnet `100.108.217.17:11434` direct (bind is `0.0.0.0` — LAN-reachable too)
- **Retired tunnel**: `kkmac-ollama-tunnel.service` on idc03 — disabled since
  2026-11-17; former `ssh -N -L 127.0.0.1:11445:127.0.0.1:11434 kkkakk@kk-mac`
  remains the documented fallback if the bind ever reverts to loopback
- **Admission gate**: `kkmac-admission-shim.service` on idc03 (`127.0.0.1:11447`)
  — THE front door for all fleet callers. Upstream repointed 2026-11-19 from
  the dead tunnel to `http://100.108.217.17:11434` (card
  kk-mac-embed-lane-verify). LiteLLM kk-mac api_base entries and the
  embed-pool kk-mac leg both point at :11447 — the shim returns 503
  instantly when the Ada Nest heartbeat is stale (>900s), `cpu_temp_c`>60,
  disk<20G, or the node is busy, so callers fail fast instead of queueing.
  `GET :11447/health` shows the live snapshot; drain switch is
  `touch $XDG_RUNTIME_DIR/kkmac-admission-shim.deny`.
- **Embed pool**: `embed-pool-shim.service` on idc03 (`100.102.134.91:11436`)
  races bge-m3 embeds across idc03/idc02/tony-omen/con01/kk-mac; the kk-mac
  leg is `http://127.0.0.1:11447` — embeddings only, admission-gated.

---

### Model Registration Requirements
Per `docs/kb/opencode-lane-model-notes.md` and `docs/ssot/infrastructure/ssot.audit.hosts.yml`:
1. **Register in idc02's opencode provider map**
2. **Add to a profile's `model.allowed` list**
3. **Verify model compatibility with LiteLLM routes**

---

### Operational Notes
- **Member device**: kk-mac travels/sleeps — offline is normal. The admission
  shim 503s while its heartbeat is stale, so callers never queue on it.
- **Security**: ollama binds `0.0.0.0` on kk-mac — tailnet AND home-LAN
  reachable. Fleet callers should still go through `:11447` (admission gate);
  narrowing the bind to the tailnet interface is the remaining delta on card
  `kkmac-ollama-durable-bind` (needs adanest plist access).
- **Model Usage**: Ensure models are registered in both the provider map and allowed lists before invocation.
