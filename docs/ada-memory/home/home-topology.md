---
key: home-topology
kind: fact
status: active
subject: home-topology
scope: shared
source: vault
written_by: tony
last_verified: 2026-09-25
---

Household hosts and roles. tony-omen (tony-omen.taila0626a.ts.net): dev/GPU host. tony-dell (tony-dell.taila0626a.ts.net, LAN 192.168.2.67): Home Assistant plus apps host — tony-ha on :8123, michael-dev on :8124, guest services on :8125/:8126. idc01 (idc01.taila0626a.ts.net): public VPS and primary Ada/memory host — ada-pi-pwa on :8001, ada-ha-tony backend on :8002, ada-ha-michael on :8003, MDDB on :11023, Ollama on :11434, gemini-ollama-proxy on :11435, obsidian-vault, open-notebook. mn01 (mn01.taila0626a.ts.net): mn-home node — Ada standby (units stopped/disabled since 2026-09-24) plus a legacy Caddy alias that proxies the Ada paths to idc01; tony-dell Caddy also proxies those paths as a LAN alias. michael-ha (michael-ha.taila0626a.ts.net): Michael's Home Assistant. All admin access is tailnet-only; tony-ha binds loopback, no LAN/plain-HTTP.
