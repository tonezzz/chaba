# Dispatch outcome — kkmac-ollama-durable-bind (2026-11-24)

## What I found (verified live, not from memory)

The card spec said "do (a) declared tunnel unit now; (b) OLLAMA_HOST bind
when adanest access is sorted." Live state had already moved past that:

- kk-mac ollama (adanest, `net.adanest.ollama.plist`) now binds `0.0.0.0`
  since 2026-11-19 — answers `http://100.108.217.17:11434/api/version`
  → 200 `{"version":"0.40.8"}` (verified from tony-omen), and also on LAN
  `192.168.0.101:11434`.
- idc03 `kkmac-admission-shim.service` (:11447) already upstreams
  `http://100.108.217.17:11434` directly; `GET /health` live and gating
  correctly (denied `load_high` at check time — owner-first working).
- `embed-pool-shim` `EMBED_POOL_UPSTREAMS` ends at `127.0.0.1:11447`;
  LiteLLM `ollama-*-kkmac` api_base entries all `:11447`. **Nothing
  consumes :11445** — the ssh tunnel is dead weight.
- `kkmac-ollama-tunnel.service` exists on idc03, disabled/inactive after
  ~19k restart flaps. Repo had **drifted**: `stacks/idc03/litellm/
  kkmac-admission-shim.service` still said `KK_SHIM_UPSTREAM=
  http://127.0.0.1:11445` + `After=kkmac-ollama-tunnel.service` while the
  live unit was hand-edited 2026-11-19.

Conclusion: option (a) as specced was moot — building a durable tunnel
for a port nobody consumes would just re-create the flap problem. The
durable-bind goal is already met by (b); what was missing was repo/SSOT
truth and the adanest-side tail.

## What changed (commit ffbd55a36c on dispatch branch)

- `stacks/idc03/litellm/kkmac-admission-shim.service` — synced to the
  live unit (tailnet upstream, no tunnel dep).
- `stacks/idc03/litellm/kkmac-ollama-tunnel.service` — NEW: declares the
  disabled fallback unit; `deploy.sh` `USER_UNITS` now installs it
  (never enables), with a comment noting the -L target must change if
  the bind is ever narrowed off loopback.
- `stacks/idc03/litellm/config.yaml` + `deploy.sh` comments — kk-mac
  block rewritten for the direct bind.
- `docs/ssot/infrastructure/ssot.llm-gateway.yml` — `ollama-kkmac`
  provider description updated.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — tunnel
  `expected_state: active→inactive` (was a live audit delta), shim +
  embed-pool notes, kk-mac `capabilities.ollama` (bind, LAN exposure,
  pending items).
- `docs/kb/kkmac-ollama-lane.md`, `docs/kb/opencode-lane-model-notes.md`
  — updated per card spec.
- `docs/ssot/jobs/devnest/2026-11-24-kkmac-ollama-durable-bind.yml` —
  job trail: verified state, changes, pending, rollback.

## Result / how to verify

- `curl http://100.108.217.17:11434/api/version` → 200 (from any
  tailnet host).
- `ssh idc03 'curl -s 127.0.0.1:11447/health'` → `upstream:
  http://100.108.217.17:11434`, live admission verdict.
- `ssh idc03 'systemctl --user is-enabled kkmac-ollama-tunnel'` →
  `disabled` (intentional; declared fallback).
- Repo: `git show ffbd55a36c`; YAML validated by pre-commit SSOT gate.

## Still open (board request raised on the card)

Needs **adanest access on kk-mac** (kkkakk can't read
`/Users/adanest/Library/LaunchAgents`, no passwordless sudo):
1. Verify `OLLAMA_HOST` is in `net.adanest.ollama.plist` so the
   `0.0.0.0` bind survives reboot — otherwise a reboot silently returns
   ollama to loopback and the lane dies.
2. Narrow the bind to the tailnet IP — LAN `192.168.0.101:11434` is
   currently exposed (SEC-0985 intent is tailnet-only). Caveat recorded
   in the job doc: `OLLAMA_HOST` takes one address, so narrowing to the
   tailnet IP also drops loopback — the disabled tunnel's `-L ...:127.0.0.1:11434`
   target would then need to become `100.108.217.17:11434`.

Side observation (not acted on): live `~/.config/litellm/config.yaml`
on idc03 lacks the `consult-flash/pro/claude` aliases present in
`stacks/idc03/litellm/config.yaml` — repo is ahead of live; next
`deploy.sh` run will install them. No live mutation was made this
session.

lessons:
- Card specs go stale between dispatch and run — always re-verify live
  state before implementing; here option (b) had already landed and the
  specced work would have rebuilt deliberately-disabled infra.
- User units hand-edited on-host drift from `stacks/` copies; the shim
  unit was live-edited 2026-11-19 with no repo sync until this commit.
- `expected_state: inactive` in ssot.audit.hosts.yml is the correct way
  to declare a deliberately-disabled unit — `expected_state: active`
  on a disabled unit is a permanent audit delta.
- systemd `Restart=always` + `RestartSec=15` against a sleeping member
  device = ~19k restart flaps; disabled fallback > enabled flap for
  ssh -L tunnels to intermittently-online hosts.
