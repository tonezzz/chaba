# KK-Mac Capacity Summary

**Host:** kk-mac — Apple Silicon Mac Studio (M4 Max 14-core, 36 GB), Tailscale `100.108.217.17`

**Ollama models (verified live):** `qwen2.5:32b`, `qwen3:8b`, `qwen2.5vl:7b` (vision), `llama3.2:3b`, `bge-m3` (embeddings)

**Capacity path:** Ollama serves loopback-only on the Mac under the `adanest` account; the fleet reaches it via a declared SSH tunnel on idc03 (`kkmac-ollama-tunnel.service`, `127.0.0.1:11445`) → LiteLLM routes `ollama-{qwen32b,qwen38b,qwen25vl7b,llama32-3b}-kkmac` → consumers (idc02 OpenCode, embed-pool-shim).

**Access caveat:** member device — sleep/offline-prone (`offline_ok: true` in ssot.audit.hosts); JevNest procedure additionally requires an owner permission window, heartbeat ≤900s, load_1m ≤4.0, disk ≥20GB free, and queue depth limits (see `docs/kb/jevnest-kk-mac-capacity-procedure.md`).

*Corrected 2026-11-03 (devin): the dispatched artifact listed an invented model inventory — source-grounded version above.*
