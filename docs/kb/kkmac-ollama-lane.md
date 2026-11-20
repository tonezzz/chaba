# docs/kb/kkmac-ollama-lane.md

## kk-mac Ollama Lane Documentation

### Overview
The kk-mac host runs Ollama services under the `adanest` account, bound to loopback (`127.0.0.1`). Access to these services is tunneled via `kkmac-ollama-tunnel.service` on idc03, which forwards idc03 loopback port 11445 to kk-mac loopback port 11434 (Ollama default). The LiteLLM routes for these models are:

- `ollama-qwen32b-kkmac`
- `ollama-qwen38b-kkmac`
- `ollama-qwen25vl7b-kkmac`
- `ollama-llama32-3b-kkmac`

---

### Setup & Capabilities
From `docs/ssot/infrastructure/ssot.audit.hosts.yml`:
- **Account**: `adanest` (non-root)
- **Network**: Loopback-only (`127.0.0.1`)
- **Tunnel**: `kkmac-ollama-tunnel.service` on idc03
  - SSH command: `ssh -N -L 127.0.0.1:11445:127.0.0.1:11434 kkkakk@kk-mac` (runs on idc03)
  - Tunnel has `Restart=always` but may fail if kk-mac (member device) is offline
- **Admission gate**: `kkmac-admission-shim.service` on idc03 (`127.0.0.1:11447`)
  sits between LiteLLM and the tunnel (added 2026-11-14, card
  kk-mac-gateway-admission-shim). LiteLLM kk-mac api_base entries point at
  :11447, not :11445 — the shim returns 503 instantly when the Ada Nest
  heartbeat is stale (>900s), `cpu_temp_c`>60, disk<20G, or the node is
  busy, so the router fails fast to the paid leg. `GET :11447/health`
  shows the live snapshot; drain switch is
  `touch $XDG_RUNTIME_DIR/kkmac-admission-shim.deny`.

---

### Model Registration Requirements
Per `docs/kb/opencode-lane-model-notes.md` and `docs/ssot/infrastructure/ssot.audit.hosts.yml`:
1. **Register in idc02's opencode provider map**
2. **Add to a profile's `model.allowed` list**
3. **Verify model compatibility with LiteLLM routes**

---

### Operational Notes
- **Tunnel Resilience**: The tunnel service restarts automatically but depends on kk-mac being online. Offline status is normal for member devices.
- **Security**: All Ollama services are bound to loopback; no external access without tunneling.
- **Model Usage**: Ensure models are registered in both the provider map and allowed lists before invocation.
- **Model sizing (benched 2026-11-20, `docs/reports/kk-mac-llm-bench-2026-11-20.md`)**:
  `qwen3:8b` is the lane default (~60 tok/s warm, 2/2 verified). 20B+
  footprints are not lane-safe under owner workloads — `gpt-oss:20b`
  (~14 GB) breached the 50% memory-abort floor at load; `qwen3:30b-a3b`
  (18.6 GB, fast at 92 tok/s but thinks aloud despite `think:false`)
  drove free memory to 20% on a second call. The MEM-1043 guard
  (60% pre-load / 50% abort) failed closed on every breach.
- **Quiet-hours gate (added 2026-11-20)**: the lane worker's `gate()`
  honors `DEVNEST_KK_MAC_QUIET_HOURS="HH:MM-HH:MM"` (kk-mac local time,
  wraps midnight; a malformed value fails closed). Opt-in — set it in
  the installed `net.adanest.kk-llm-worker` plist during an
  owner-approved window; suggested `23:00-07:00`.
- **One-shot rollback**: `touch ~/.cache/kk-llm-worker.drain` on kk-mac
  drains instantly; `launchctl bootout gui/$(id
  -u)/net.adanest.kk-llm-worker` + removing the plist unpersists the
  worker. Fleet side: `touch $XDG_RUNTIME_DIR/kkmac-admission-shim.deny`
  (shim 503s → paid leg) and `systemctl --user stop
  kkmac-ollama-tunnel.service` on idc03. All decline paths fail closed
  to the next lane — rollback never strands a card.
