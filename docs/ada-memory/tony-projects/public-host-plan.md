---
kind: note
status: active
subject: public-host
attribute: plan-draft
---

# Public host = Ada deployment server — plan

Status: v3b — M0-M3 EXECUTED on idc01, 2026-09-21.
Decisions: all three Ada instances run on the VPS; MDDB moves to the VPS
as the ONLY instance — no tony-dell standby initially. Data-security
hardening and a standby/follower are deferred (§10). Memory data is
currently mock/non-critical.

## 0. What's live now (idc01)

- Host: VPS `idc01` — 157.85.110.99, tailnet `100.74.146.0`,
  Ubuntu 24.04 x86_64, 2 vCPU / 7.8 GB / 96 GB, KVM.
- Hardened: key-only SSH (password auth off — root pw was shared in
  chat), ufw 22/80/443, fail2ban, unattended-upgrades, rootless podman.
- Tailscale: joined, `--accept-routes`; all home hosts reachable except
  michael-ha (mn01 is not currently advertising its subnet route — fix
  on mn01 or use Nabu Casa URL for ada-ha-michael).
- Running (systemd user units, `tony` user, linger on):
  - `ada-pi-pwa` :8001, `ada-ha-tony` :8002, `ada-ha-michael` :8003 —
    all `127.0.0.1`-bound, healthy.
  - `mddb` — PRIMARY since 2026-09-22, bound to `100.74.146.0`
    (HTTP :11023, gRPC :11024, MCP :9000 with API-key auth). The old
    tony-dell primary is stopped/disabled (data kept for rollback).
  - `gemini-ollama-proxy` :11435 loopback — Gemini primary →
    `nomic-embed-text` Ollama fallback with circuit breaker; hourly
    `mddb-embed-space-check.timer` flips the corpus back to Gemini space
    on recovery and runs the recall canary (fails loudly on regression).
  - `ollama` container — nomic-embed-text + llama3.2 (as phi3-gguf alias).
  - `caddy-edge` quadlet (podman `Network=host`) — real ACME cert.
- Public URL: `https://157.85.110.99.sslip.io/` → ada-pi-pwa (canary).
- Tailnet URL: `https://idc01.taila0626a.ts.net/` → ada-pi-pwa via
  `tailscale serve` (tailnet-only for now — verified 200 from tony-omen).
- Also on idc01 (tailnet-only via serve): obsidian vault app :8443,
  OpenNotebook UI :8444 + API :8445, mddb-panel at 100.74.146.0:3002.
- Backups (all restore-verified): mddb nightly 02:30 → `~/mddb-backups`
  (pulled to home); open-notebook SurrealDB export nightly 02:45 →
  `~/open-notebook-backups` (import-tested, 518 sources); obsidian vault
  tar nightly 03:00 → `~/obsidian-backups`; monthly restore-check timer
  re-imports the newest SurrealDB export into a scratch container and
  fails loudly on <100 sources.
- Hardening pass 2026-09-22: SSH now tailnet-only (public :22 closed);
  mddb/panel bound to the tailnet IP (loopback closed); 21 devin-bank
  transcript docs redacted in place on idc01 (live Google API keys,
  HA JWTs, GOCSPX OAuth secret removed — revision history dropped via
  delete+re-add). Tokens still live → rotation remains user action.
- Domain plan (decided 2026-09-21): use the Tailscale address for now;
  Tony will add a **Cloudflare** service later for the real domain.
- Secrets copied host-to-host (env + keys JSON + calendar token).
- `deploy-ada.sh` gained an `idc01` case (committed 50a8dc37).
- SSH alias: `ssh idc01` (tony-omen `~/.ssh/config`).

## 1. What Ada is today

Three instances of the same app — `pwa_server:app` (FastAPI + uvicorn),
differentiated only by env files:

| Service | Home | Port | Instance |
|---|---|---|---|
| ada-ha-tony | mn01 | 8002 | tony |
| ada-ha-michael | mn01 | 8003 | michael |
| ada-pi-pwa | tony-dell | 8001 | tony |

`backend/main.py` (Hailo/camera/pironman) is the old Pi prototype — not
deployed, not needed on a VPS. `pwa_server` is nearly stateless: only
local state is the issued-keys JSON + logs.

## 2. Runtime dependencies of pwa_server

| Dependency | Required? | Without it |
|---|---|---|
| Gemini API (`GEMINI_API_KEY` — Live, summaries, decision_check) | hard | no voice/chat/checks |
| MDDB (:11023) | hard-ish | banks/summaries/events/checks fail; health=degraded |
| Home Assistant (URL+token) | per-instance | no entity tools, no chaba_event; chat works |
| NotebookLM REST (:3011, scoped key) | soft | deep-recall tier gone; MDDB tier still works |
| `ADA_MEMORY_BANKS_FILE` (rendered JSON) | hard | banks fail loudly by design |
| env + keys JSON | hard | no identity/auth |
| Caddy edge (TLS + routing) | hard for public | plain HTTP |

## 3. Target placement

| Component | Where | Notes |
|---|---|---|
| ada-ha-tony / ada-ha-michael / ada-pi-pwa | **idc01** | systemd user units — done |
| Caddy edge + domain + ACME | **idc01** | done on sslip.io interim |
| MDDB (sole instance) | **idc01** | podman quadlet — migrated, all consumers repointed |
| Scheduled Ada jobs (sync/rollup/drift/backup) | **idc01** | phase M6 |
| notebooklm-rest / notebooklm-mcp | tony-dell | master_token = whole-Google credential |
| Weaviate | tony-dell | home-internal dep (yomi/index jobs) |
| Open Notebook | tony-dell | eval stack; adopt-or-retire later |
| obsidian-vault | mn01 | tailnet-only write UI; see resolution below |
| Home Assistant ×2 | home | by definition |
| tony-dell mddb | **retired after cutover** | stop → archive cold → disable |
| Home Ada instances | standby | units stay installed, `disabled` |

Resolved 2026-09-21: `apps/obsidian` stays tailnet-only by default. If it
is ever deployed on the public host it runs `ADA_DEPLOY=public` — all
`/api/*` reads require X-API-Key (startup refuses otherwise) and only
banks flagged `public: true` in ssot.apps.ada-memory-banks.yml are
served (deny-by-default; today only `github` is public).

## 4. MDDB migration (one-way) — M4, done 2026-09-23

> Done: MDDB live on idc01; every Ada env already used
> `MDDB_BASE_URL=http://100.74.146.0:11023/v1`; tony-dell local MDDB
> stopped. 2026-09-24: verified durable + serving after the WARP
> incident below.

### Post-mortem: tailnet MTU blackhole (2026-09-23)

Cloudflare WARP (`warp-svc`) was enabled on idc01 ~14:54 +07 and
shrank the effective path MTU to ~1030 bytes with no ICMP
fragmentation-needed returns (classic PMTUD blackhole): SSH stalled
at KEX_ECDH_REPLY, tailnet HTTPS and MDDB responses >1KB died, and
mn01 Ada logged mddb search/vector/add failures. Stopping warp-svc
restored everything. **Keep warp-svc disabled** (`systemctl disable
warp-svc`) or it re-breaks on next boot.

Original migration procedure follows for the record:

1. On tony-dell: `GET /v1/backup` snapshot (consistent `mddb.db` while
   running) or stop → copy `~/.config/containers/mddb/data` + `vaults`.
2. rsync to idc01 `~/.config/containers/mddb/`, start mddb quadlet
   (tailnet+loopback bind), verify `/v1/stats` doc/revision counts.
3. Repoint every consumer's `MDDB_BASE_URL` to `100.74.146.0:11023`
   (Ada envs, Devin mcp config, sync/rollup scripts, HA event_recorder).
4. Soak ~1 week with tony-dell mddb stopped but data intact.
5. Archive `mddb.db` cold (mn01 or GDrive), then disable the unit.

**Backups become the only safety net** — no standby. Mandatory:
nightly `/v1/backup` on idc01 + pull to mn01/tony-omen over tailnet.
Keep the pre-migration tony-dell snapshot permanently as
last-known-good.

Observed 2026-09-21 (live): MDDB cold start on tony-dell took ~40 min
for HTTP to come up, and the **vector index kept loading ~25+ min more —
writes FAIL during that window** (add/update error out because MDDB
embeds on write) while `ada_remember` still reported success to the
caller — silent memory loss. Plan cold-start windows deliberately; the
deferred follower replica (§10) also covers this gap.

## 5. Embeddings — DECIDED 2026-09-23: hybrid (B-aware A)

Gemini stays canonical; local Ollama `nomic-embed-text` is the outage
fallback. gemini-ollama-proxy tries Gemini → alternate model → Ollama,
with a circuit breaker (1h cooldown after 429s) so bulk loads don't pay
retry cost per chunk. Mixed-space hazard is handled by
`mddb-embed-space-check.timer`: hourly probe, tracks corpus space in
`~/mddb-embed-space`, and on Gemini recovery force-reindexes all
collections back to gemini space then runs the recall canary (timer
fails on regression). Recall during the first outage: 10/10 canary in
nomic space. Open Notebook uses the same local nomic for retrieval;
generation still needs Gemini quota or a faster local model (deferred —
phi3-gguf on tony-omen's 4GB GPU is >300s/question, unusable live).

## 6. Repo / stack / data structure

```
stacks/idc01/                    # in chaba repo, stacks/<host>/ convention
├── podman/                    # quadlets -> ~/.config/containers/systemd/
│   ├── caddy-edge.container + Caddyfile   (deployed)
│   ├── mddb.container         # M4; tailnet+lo bind
│   ├── mddb-panel.container   # tailnet-only (optional)
│   └── gemini-proxy.container # (option A) / ollama.container (B)
├── ada/                       # ada unit files (deployed)
├── jobs/                      # timers: sync/rollup/drift/backup (M6)
└── README.md
```

SSOT TODO: new `ssot.apps.idc01.yml`, host entry in
`ssot.audit.hosts.yml`, `ssot.networks.yml`, health endpoints.

On-host layout (deployed):

```
~/CascadeProjects/ada-pi/      # origin/main checkout
~/CascadeProjects/chaba/       # scripts + render targets
~/.config/containers/systemd/  # quadlets (caddy-edge)
~/.config/containers/mddb/{data,vaults}/  # ready for M4
~/.config/ada/memory-banks.json  # rendered
~/.config/secrets/*.env          # 600
~/.local/share/backups/          # staging dir ready
```

## 7. Secrets on idc01

- `GEMINI_API_KEY`, `ADA_API_KEYS` + keys JSONs, `HOME_ASSISTANT_TOKEN`,
  `NOTEBOOKLM_REST_API_KEY` (scoped), `ada-google-calendar-token.json`.
- `~/.config/secrets/*.env` mode 600; nightly pull to mn01 pending.
- NOTE (2026-09-21 incident): GEMINI_API_KEY + HA token live inside a
  devin-bank transcript doc in MDDB — rotate before/during M4 so the
  VPS never holds live-but-leaked creds.

## 8. Network/security (baseline — done)

- Tailnet node; ACLs TODO: scope idc01 to HA ports + tony-dell:3011,
  home hosts→idc01:11023 for consumers.
- Public firewall: 80/443/22 only; key-only SSH; fail2ban.
- MDDB will bind tailnet iface + loopback — never public (M4).
- Caddy `rate_limit` needs a plugin build — deferred; Ada auth is
  device-key based anyway.

## 9. Write-outage handling

Home uplink down → home writers (event_recorder, syncs) can't reach the
VPS leader. Phase-2: local spool/outbox on home writers, flush on
reconnect (same pattern as notebooklm-rest's write queue). Ada-side
writes are local on the VPS — unaffected.

## 10. DEFERRED backlog (after VPS deployment is proven)

- **Standby replica**: MDDB has native leader-follower replication —
  `MDDB_REPLICATION_ROLE=leader` on idc01, `follower` on a home host,
  `MDDB_REPLICATION_SECRET` shared secret, gRPC :11024, <50ms lag,
  embeddings replicate via binlog (follower needs no embedding
  provider). Promotion is manual (restart as standalone). Also gives
  home consumers a local read replica.
- `MDDB_AUTH_ENABLED=true` + per-consumer keys for HTTP/gRPC
  (MCP :9000 already key-gated; core ports still open on the tailnet).
- **Local generation for deep-tier** — phi3-gguf on tony-omen's 4GB GPU
  is >300s/question; a 7B-class card or accepting cloud dependence is a
  spend decision (deferred).
- `public:` bank flag enforcement end-to-end.
- Rotate Gemini API key + HA tokens (purge-only was chosen; the leaked
  values may still be valid and live in pre-rewrite backups — user action).
- Disk encryption / provider threat model before real personal data.
- notebooklm-rest move, only if dedicated Google account adopted.
- **ada_ask_open_notebook** (deep-tier tool — spec, unbuilt):
  read-only Ada tool calling `POST {OPEN_NOTEBOOK_URL}/api/search/ask/simple`
  `{question, strategy_model, answer_model, final_answer_model}` ->
  grounded answer + citations over the notebook corpus (517-source
  `chaba-kb-bench` lives there). Ada side: ToolRunner entry, no
  confirmation (read-only); invoke only when `ada_memory_search` top
  score is low or the user asks for a deep dive — same tier as
  NotebookLM today but self-hosted and API-clean. Latency budget
  ~20-70s/question on Gemini models; >300s on phi3-gguf/4GB GPU, so
  gate registration on a generation path under ~60s (Gemini quota
  recovery or a faster local model). Embeddings already local
  (nomic-embed-text on idc01).




## 11. Phases

- M0 done — provision + harden idc01 (SSH keys, ufw, fail2ban, podman)
- M1 done — tailnet join + accept-routes (michael-ha subnet route pending)
- M2 done — Caddy edge + sslip.io + ACME; ada-pi-pwa proxied + healthy
- M3 done — ada-pi checkout + env/keys + rendered banks; all 3 up
- M4 done — MDDB on idc01; all Ada envs point at it; tony-dell MDDB stopped
- M5 done 2026-09-24 — mn01 ada-ha-tony/ada-ha-michael stopped+disabled (standby);
  tailscale serve path-mounts /apps/ha/ada-{tony,michael} -> :8002/:8003 on idc01;
  mn01 Caddy proxies same paths to idc01 as legacy alias; consumers repointed to
  idc01 URLs (apps.yml, voice card, Lovelace iframe, health+services SSOT);
  cms-viewer shared key replicated on idc01; ws+http verified end-to-end
- M6 done 2026-09-24 — all job timers live on idc01: ada-memory-sync (hourly; one
  meta-churn conflict resolved via --take-remote), obsidian-vault-sync, mddb-backup
  (nightly, verified landing), open-notebook-backup, obsidian-vault-backup,
  ada-recall-canary, ada-memory-drift, ada-memory-gaps, ada-memory-distill
  (migrated off mn01 + smoke-tested — emitted 2 drafts). Known gap: distill's
  chaba-event-log emit does `ssh tony-dell` which idc01 can't reach — non-fatal,
  events just don't land in the HA log.
- M7 pending — soak ~1 week → archive tony-dell mddb.db → disable

## 12. Open questions for Tony

1. Domain — RESOLVED for now: tailscale address
   (`idc01.taila0626a.ts.net`) + sslip.io fallback; Cloudflare-backed
   real domain comes later (Tony will add the service).
2. Expose ada-ha-tony/ada-ha-michael publicly? Subdomains via
   `<name>.157.85.110.99.sslip.io` work today, or keep them tailnet-only.
3. michael-ha reachability: re-advertise mn01 subnet route, or point
   ada-ha-michael at the Nabu Casa URL?
4. Embeddings: proxy→Gemini (A) vs local nomic + reindex (B)?
5. HA token on VPS (current: copied) vs dedicated HA user later?

## 13. Ada review path

Vault file → `sync-ada-memory-to-mddb.py` → `ada-ha-bank-projects-tony`.
Ask Ada-Tony: "review the public host plan" — `ada_memory_search` finds
it; review notes return via `ada_remember` → `docs/ada-memory/inbox/`
on next `--export-inbox`.

NOTE: this file is canonical in the mn01 vault
(`~/CascadeProjects/chaba-vault/docs/ada-memory/tony-projects/`);
the repo copy gets overwritten by vault pulls — edit mn01 first.
