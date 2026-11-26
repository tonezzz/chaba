# docs/kb/kkmac-ollama-lane.md

## kk-mac Ollama Lane Documentation

### Overview
The kk-mac host runs Ollama services under the `adanest` account. Since
2026-11-19 `net.adanest.ollama.plist` binds `0.0.0.0` — reachable directly
on the tailnet at `100.108.217.17:11434` (and on LAN `192.168.0.101:11434`
+ `192.168.2.90:11434` — verified answering 2026-11-24 — until the bind is
narrowed to the tailnet IP; needs KK sudo on kk-mac, card
`kkmac-ollama-durable-bind`). `OLLAMA_HOST=0.0.0.0:11434` is confirmed in
`/Library/LaunchDaemons/net.adanest.ollama.plist` EnvironmentVariables
(verified 2026-11-24 via `launchctl print system/net.adanest.ollama` —
system domain is readable as kkkakk, no adanest access needed), so the
bind survives reboot. The fleet path on idc03 is
`kkmac-admission-shim.service` (`127.0.0.1:11447`), an Ada Nest admission
gate that proxies to the tailnet bind. The older ssh tunnel
`kkmac-ollama-tunnel.service` (`127.0.0.1:11445 -> kk-mac:11434`) is
installed but **disabled** — kept only as a loopback-bind rollback; it
flapped ~19k restarts while enabled. The LiteLLM routes for these models are:

- `ollama-qwen32b-kkmac`
- `ollama-qwen38b-kkmac`
- `ollama-qwen25vl7b-kkmac`
- `ollama-llama32-3b-kkmac`

---

### Setup & Capabilities
From `docs/ssot/infrastructure/ssot.audit.hosts.yml`:
- **Account**: `adanest` (non-root)
- **Network**: `0.0.0.0` bind since 2026-11-19 — tailnet
  `100.108.217.17:11434` + LAN `192.168.0.101:11434` +
  `192.168.2.90:11434` (narrow-to-tailnet pending KK sudo —
  `OLLAMA_HOST` durability VERIFIED 2026-11-24 in the LaunchDaemon
  plist)
- **Admission gate**: `kkmac-admission-shim.service` on idc03 (`127.0.0.1:11447`)
  proxies to `http://100.108.217.17:11434` (added 2026-11-14, card
  kk-mac-gateway-admission-shim; upstream repointed off the tunnel
  2026-11-19). LiteLLM kk-mac api_base entries point at
  :11447, not :11445 — the shim returns 503 instantly when the Ada Nest
  heartbeat is stale (>900s), `cpu_temp_c`>60, disk<20G, or the node is
  busy, so the router fails fast to the paid leg. `GET :11447/health`
  shows the live snapshot; drain switch is
  `touch $XDG_RUNTIME_DIR/kkmac-admission-shim.deny`.
- **Tunnel (fallback, disabled)**: `kkmac-ollama-tunnel.service` on
  idc03 — `ssh -N -L 127.0.0.1:11445:127.0.0.1:11434 kkkakk@kk-mac`,
  `Restart=always`. Disabled 2026-11-17 after ~19k restart flaps while
  kk-mac slept; unit file now declared in `stacks/idc03/litellm/`
  (deploy.sh installs it, never enables). Re-enable only for a
  loopback-bind rollback: repoint shim `KK_SHIM_UPSTREAM` to
  `http://127.0.0.1:11445`, enable the tunnel, restart the shim.

---

### Model Registration Requirements
Per `docs/kb/opencode-lane-model-notes.md` and `docs/ssot/infrastructure/ssot.audit.hosts.yml`:
1. **Register in idc02's opencode provider map**
2. **Add to a profile's `model.allowed` list**
3. **Verify model compatibility with LiteLLM routes**

---

### Operational Notes
- **Tunnel Resilience**: N/A while the direct tailnet bind is primary —
  the disabled tunnel flapped ~19k restarts against a sleeping member
  device. If re-enabled for rollback, expect the same flap pattern.
- **Security**: ollama binds `0.0.0.0` — tailnet AND both home-LAN
  subnets reachable (verified 2026-11-24). Narrow `OLLAMA_HOST` to
  `100.108.217.17` in `/Library/LaunchDaemons/net.adanest.ollama.plist`
  with KK's sudo when available (SEC-0985 tailnet-only intent); note a
  single-address bind drops loopback too — the ssh-tunnel fallback then
  needs its `-L` target changed to the tailnet IP (comment in the unit
  file covers this).
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
  (shim 503s → paid leg). All decline paths fail closed
  to the next lane — rollback never strands a card.
- **Loopback-bind rollback** (only if the tailnet bind is lost):
  `systemctl --user enable --now kkmac-ollama-tunnel.service` on idc03,
  set shim `KK_SHIM_UPSTREAM=http://127.0.0.1:11445`, restart the shim.
