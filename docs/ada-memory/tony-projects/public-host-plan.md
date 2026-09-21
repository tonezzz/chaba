---
kind: note
status: active
subject: public-host
attribute: plan-draft
---

# Public host = Ada deployment server — draft plan

Status: DRAFT v3b for review, 2026-09-21.
Decisions: all three Ada instances move; MDDB moves to the VPS as the
ONLY instance — no tony-dell standby initially. Data-security hardening
and a standby/follower are deferred (§10) until the VPS deployment is
proven. Memory data is currently mock/non-critical.

## 1. What Ada is today

Three instances of the same app — `pwa_server:app` (FastAPI + uvicorn),
differentiated only by env files:

| Service | Host | Port | Instance |
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
| ada-ha-tony / ada-ha-michael / ada-pi-pwa | **VPS** | systemd user units (podman optional) |
| Caddy edge + real domain + ACME | **VPS** | public ingress, replaces Funnel for Ada paths |
| MDDB (sole instance) | **VPS** | podman quadlet; :11023 tailnet+loopback only |
| Scheduled Ada jobs (sync/rollup/drift/backup) | **VPS** | repo checkout + timers |
| notebooklm-rest / notebooklm-mcp | tony-dell | master_token = whole-Google credential |
| Weaviate | tony-dell | home-internal dep (yomi/index jobs) |
| Open Notebook | tony-dell | eval stack; adopt-or-retire later |
| obsidian-vault | mn01 | tailnet-only write UI; see resolution below |
| Home Assistant ×2 | home | by definition |
| tony-dell mddb | **retired after cutover** | unit stopped/disabled; data dir archived as cold backup |
| Home Ada instances | standby | units stay installed, `disabled`; VPS dies → start + flip Caddy |

Resolved 2026-09-21: `apps/obsidian` stays tailnet-only by default. If it
is ever deployed on the public host it runs `ADA_DEPLOY=public` — all
`/api/*` reads require X-API-Key (startup refuses otherwise) and only
banks flagged `public: true` in ssot.apps.ada-memory-banks.yml are
served (deny-by-default; today only `github` is public).

## 4. MDDB migration (one-way)

1. On tony-dell: `GET /v1/backup` snapshot (consistent `mddb.db` while
   running) or stop → copy `~/.config/containers/mddb/data` + `vaults`.
2. rsync to VPS, start mddb quadlet, verify `/v1/stats` doc/revision
   counts match.
3. Repoint every consumer's `MDDB_BASE_URL` to `<vps>:11023`
   (Ada envs, Devin mcp config, sync/rollup scripts, HA event_recorder).
4. Soak ~1 week with tony-dell mddb stopped but data intact.
5. Archive `mddb.db` to cold backup (mn01 or GDrive), then disable unit.

**Backups become the only safety net** — no standby. Mandatory:
nightly `/v1/backup` on VPS + pull to mn01/tony-omen over tailnet
(extend existing backup-mddb-banks/mirror scripts). Also keep the
pre-migration tony-dell snapshot permanently as the last-known-good.

## 5. Embeddings — open decision

Existing vectors are `gemini-embedding-2` via gemini-ollama-proxy
(the `nomic-embed-text` name is an alias to gemini-embedding-2).

- A: run gemini-ollama-proxy on the VPS → vectors stay compatible.
- B: real local Ollama `nomic-embed-text` (CPU) → kills quota
  dependency, but all stored vectors become incomparable — full reindex
  via `scripts/mddb/reindex.py`.
- Recommendation: A at migration, evaluate B later.

## 6. Repo / stack / data structure

```
stacks/vps01/                    # in chaba repo, stacks/<host>/ convention
├── podman/                    # quadlets -> ~/.config/containers/systemd/
│   ├── caddy-edge.container + Caddyfile
│   ├── mddb.container         # sole instance; tailnet+lo bind
│   ├── mddb-panel.container   # tailnet-only (optional)
│   └── gemini-proxy.container # (option A) / ollama.container (B)
├── ada/                       # ada-ha-{tony,michael},ada-pi-pwa units
├── jobs/                      # timers: sync/rollup/drift/backup
├── deploy.sh                  # deploy-ada.sh contract: origin/main, ff-only, flock
└── README.md
```

SSOT: new `ssot.apps.vps01.yml`, host in `ssot.audit.hosts.yml`,
`ssot.networks.yml`, health endpoints.

On-host layout (mirrors tony-dell):

```
~/CascadeProjects/ada-pi/      # origin/main checkout
~/CascadeProjects/chaba/
~/.config/containers/systemd/
~/.config/containers/mddb/{data,vaults}/
~/.config/ada/memory-banks.json
~/.config/secrets/*.env        # 600, never committed
~/.local/share/backups/        # staging before pull home
```

## 7. Secrets on the VPS

- `GEMINI_API_KEY`, `ADA_API_KEYS` + keys JSON, `HOME_ASSISTANT_TOKEN`
  (dedicated HA user, scoped), `NOTEBOOKLM_REST_API_KEY` (scoped).
- `~/.config/secrets/*.env` mode 600; nightly pull to mn01 — it's the
  only unique state on an otherwise git-rebuildable box.
- NOTE (2026-09-21 incident): GEMINI_API_KEY + HA token currently live
  inside a devin-bank transcript doc in MDDB — rotate both before or
  during migration so the VPS never receives live-but-leaked creds.

## 8. Network/security (baseline)

- VPS = tagged tailnet node. ACLs: VPS→HA ports + tony-dell:3011;
  home hosts→VPS:11023 (consumers), VPS→home for backup pushes.
- Public firewall: 80/443/SSH only, key-only SSH, fail2ban.
- MDDB binds tailnet iface + loopback — never public.
- Caddy rate-limit `/api/*` + `/ws`.
- Sizing: ~3-4 GB RAM (mddb + 3× Ada + Caddy; +ollama if option B).
  `tradik/mddb` ships linux/arm64 → Oracle free tier viable;
  else ~$8-12 x86 SG.

## 9. Write-outage handling

Home uplink down → home writers (event_recorder, syncs) can't reach the
VPS leader. Phase-2 mitigation: local spool/outbox on home writers,
flush on reconnect (same pattern as notebooklm-rest's write queue).
Ada-side writes are local on the VPS — unaffected.

## 10. DEFERRED backlog (after VPS deployment is proven)

- **Standby replica**: MDDB has native leader-follower replication —
  `MDDB_REPLICATION_ROLE=leader` on VPS, `follower` on a home host,
  `MDDB_REPLICATION_SECRET` shared secret, gRPC :11024, <50ms lag,
  embeddings replicate via binlog (follower needs no embedding
  provider). Promotion is manual (restart as standalone). Also gives
  home consumers a local read replica.
- `MDDB_AUTH_ENABLED=true` + per-consumer keys (unauthenticated today).
- `public:` bank flag enforcement end-to-end.
- Disk encryption / provider threat model before real personal data.
- notebooklm-rest move, only if dedicated Google account adopted.

## 11. Phases

- M0 provision + harden VPS (SSH keys, ufw, fail2ban, podman, host-tools)
- M1 tailnet join + ACLs; verify reachability matrix both directions
- M2 Caddy edge + domain + ACME; proxy one Ada instance; browser test
- M3 ada-pi checkout + env/keys + rendered banks file; canary instance
- M4 MDDB migration per §4 (snapshot → verify → repoint consumers)
- M5 home Ada units → standby; public URLs on VPS; Funnel stays fallback
- M6 scheduled jobs move; audit hosts + health SSOT + chaba_event
- M7 soak ~1 week → archive tony-dell mddb.db cold → disable unit

## 12. Open questions for Tony

1. Domain: buy / free subdomain / reuse existing?
2. Provider: Oracle free ARM vs paid x86?
3. Embeddings: proxy→Gemini (A) vs local nomic + reindex (B)?
4. Ada on VPS: systemd units or podman quadlets?
5. HA token on VPS (dedicated user) vs relay through tony-dell?
6. VPS hostname (for stacks/<host>/ + SSOT)?

## 13. Ada review path

Vault file → `sync-ada-memory-to-mddb.py` → `ada-ha-bank-projects-tony`.
Ask Ada-Tony: "review the public host plan" — `ada_memory_search` finds
it; review notes return via `ada_remember` → `docs/ada-memory/inbox/`
on next `--export-inbox`.
