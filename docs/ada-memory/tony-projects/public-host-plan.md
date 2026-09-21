---
kind: note
status: active
subject: public-host
attribute: plan-draft
---

# Public host = Ada deployment server — draft plan

Status: DRAFT v2 for review. Scope changed 2026-09-21: the VPS is the
deployment server that *runs* Ada, not just an edge proxy.

## 1. What Ada is today

Three instances of the same app — `pwa_server:app` (FastAPI + uvicorn),
differentiated only by env files:

| Service | Host | Port | Instance |
|---|---|---|---|
| ada-ha-tony | mn01 | 8002 | tony |
| ada-ha-michael | mn01 | 8003 | michael |
| ada-pi-pwa | tony-dell | 8001 | tony |

`backend/main.py` (Hailo/camera/pironman vision stack) is the old Pi
prototype — not deployed on servers, not needed on a VPS.

## 2. Runtime dependency assessment

What `pwa_server` actually needs to operate:

| Dependency | Required? | What breaks without it |
|---|---|---|
| Gemini API (`GEMINI_API_KEY`, Live + `ADA_SUMMARY_MODEL` + decision_check grounding) | **hard** | No voice, no chat, no summaries, no decision check |
| MDDB (`MDDB_BASE_URL`, :11023) | **hard-ish** | Memory banks, session summaries, decision checks, event log all fail; `/api/health` goes degraded |
| Home Assistant (`HOME_ASSISTANT_URL` + token) | per-instance | No entity/sensor/dashboard tools, no `chaba_event` transport; chat still works |
| NotebookLM REST (:3011 + scoped key) | soft | Deep-recall/archive tier gone; MDDB-first recall still works |
| `ADA_MEMORY_BANKS_FILE` (rendered JSON) | **hard** | Bank resolution fails loudly by design |
| `~/.config/secrets/ada-ha-<inst>.env` + keys JSON | **hard** | No instance identity, no auth |
| Caddy edge for TLS + path routing | **hard** for public | Plain HTTP otherwise |

`pwa_server` itself is nearly stateless: the only local state is the
issued-keys JSON (`~/.config/secrets/ada-ha-<inst>-keys.json`) and logs.
No sqlite/habits DB in the PWA path.

## 3. Adjacent services (not in-process, run on timers)

Sync/rollup/backup scripts (`sync-ada-memory-to-mddb.py`,
`rollup-summaries.py`, `sync-devin-summaries.py`, `recall-drift-report.py`,
`backup-mddb-banks.py`, `render-memory-banks.py`, `consolidate-memory.py`)
— plain Python + systemd timers; need a repo checkout and MDDB
reachability. `obsidian-vault` web UI on mn01 is optional.

## 4. Placement recommendation

| Component | VPS? | Why |
|---|---|---|
| `pwa_server` instances | **Yes** | Stateless, light (~FastAPI + websockets), designed for env-based relocation |
| Caddy edge (real domain + ACME) | **Yes** | The point of the public host |
| Scheduled Ada jobs | Yes (phase 2) | Centralizes ops on the deployment server |
| MDDB | **Keep home** (revisit) | Stateful 346MB store of personal memory; tailnet hop adds only ~10-50ms to recall; moving it drags embedding-proxy deps + data migration |
| notebooklm-rest | **Keep home** | `master_token.json` is a whole-Google-account credential — putting it on a public VPS widens the blast radius badly |
| Home Assistant | No | By definition |

Key property of this split: if the home uplink dies, the public Ada
endpoint still answers — `/api/health` reports degraded and voice/chat
still work, only memory + HA tools fail.

## 5. Secrets that must live on the VPS

- `GEMINI_API_KEY` (required)
- `ADA_API_KEYS` + per-instance keys JSON (device auth)
- `HOME_ASSISTANT_TOKEN` — sensitive: controls the house. Mitigate with
  a dedicated HA user/token, and Tailscale ACLs limiting the VPS to HA
  port only.
- `NOTEBOOKLM_REST_API_KEY` — scoped key only (already per-instance).
- All in `~/.config/secrets/*.env`, mode 600, never committed.

## 6. Network/security

- VPS joins tailnet as a tagged node; ACLs allow only: tony-dell:11023
  (MDDB), tony-dell:3011 (NLM REST), HA ports (8123 / michael-ha),
  mn01 if needed. Nothing else.
- Public firewall: 80/443/SSH only; key-only SSH.
- Public surface: Ada PWA paths only. Never proxy HA admin, MDDB, MCP.
- Caddy rate-limit on `/api/*`; auth unchanged (device-key → cookie).
- Sizing: 1-2 GB RAM, 1-2 vCPU is ample. No GPU needed (Gemini is
  remote; the Hailo stack isn't part of pwa_server). Python 3.11+ venv.
- Bandwidth: voice audio is server-side to Gemini Live — modest.

## 7. Provider candidates (unchanged)

- Oracle free tier — free, but arm64 (venv deps are pure-Python/fastapi,
  so likely fine; litert/hailo wheels not needed by pwa_server).
- Hetzner CX22 ~EUR 4/mo x86, or DO/Vultr ~$4-6, prefer SG region.

## 8. Phases

- M0 — provision VPS, harden, rootless podman OR plain systemd user
  units (Ada currently runs as systemd units, not containers — decide;
  podman gives parity with other quadlets, systemd units are simpler
  and match deploy-ada.sh today).
- M1 — tailnet join + ACLs; verify VPS can reach MDDB/NLM/HA and nothing
  else.
- M2 — Caddy + domain + ACME; proxy one Ada instance; browser test.
- M3 — replicate ada-pi checkout (origin/main, deploy-ada.sh contract),
  render memory-banks file, copy env+keys files, run one Ada instance
  alongside the home one (canary).
- M4 — migrate public Ada URLs to the VPS; keep mn01/tony-dell instances
  as fallback during soak.
- M5 — move scheduled jobs; register VPS in ssot.audit.hosts.yml +
  health SSOT; chaba_event on deploys.

## 9. Open questions for Tony

1. Domain: buy one / free subdomain / reuse existing?
2. Provider: free ARM (Oracle) vs ~$4-5 x86?
3. Which Ada instances move: just `ada-pi-pwa` (the public-facing one),
  or ada-ha-tony/michael too?
4. Containers (podman quadlets) vs systemd units for Ada on the VPS?
5. OK with `HOME_ASSISTANT_TOKEN` living on the VPS (dedicated HA user),
  or should HA calls hairpin through a relay instead?
6. Should MDDB eventually move too, or permanently stay home?

## 10. Ada review path

This file lives in the vault (`docs/ada-memory/tony-projects/`).
`python3 scripts/ada/sync-ada-memory-to-mddb.py` pushes it into
`ada-ha-bank-projects-tony`, so Ada-Tony can recall it via
`ada_memory_search(bank="tony-projects")` when asked to "review the
public host plan". Review notes come back via `ada_remember` and land
in `docs/ada-memory/inbox/` on the next `--export-inbox` run for human
review.
