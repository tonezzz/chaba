---
key: home-topology
kind: fact
status: active
subject: home-topology
scope: shared
source: vault
written_by: tony
last_verified: 2026-09-23
---

Household hosts and roles. tony-omen (tony-omen.taila0626a.ts.net): dev/GPU host. tony-dell (tony-dell.taila0626a.ts.net, LAN 192.168.2.67): Home Assistant plus apps host — tony-ha on :8123, michael-dev on :8124, guest services on :8125/:8126. mn01 (mn01.taila0626a.ts.net): Ada and memory host at mn-home — ada-ha-tony backend on :8002, ada-ha-michael on :8003. idc01 (idc01.taila0626a.ts.net): public VPS — MDDB on :11023, Ollama on :11434, gemini-ollama-proxy on :11435, obsidian-vault, open-notebook. michael-ha (michael-ha.taila0626a.ts.net): Michael's Home Assistant. All admin access is tailnet-only; tony-ha binds loopback, no LAN/plain-HTTP.
