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
    all `127.0.0.1`-bound, healthy, 14 banks loaded, MDDB reachable
    over tailnet (still pointing at tony-dell:11023).
  - `caddy-edge` quadlet (podman `Network=host`) — real ACME cert.
- Public URL: `https://157.85.110.99.sslip.io/` → ada-pi-pwa (canary).
- Tailnet URL: `https://idc01.taila0626a.ts.net/` → ada-pi-pwa via
  `tailscale serve` (tailnet-only for now — verified 200 from tony-omen).
- Also on idc01 (tailnet-only via serve): obsidian vault app :8443,
  OpenNotebook UI :8444 + API :8445, mddb-panel at 100.74.146.0:3002.
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
| MDDB (sole instance) | **idc01** | podman quadlet; tailnet+lo only — M4 pending |
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

## 4. MDDB migration (one-way) — M4, pending

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

## 5. Embeddings — open decision

Existing vectors are `gemini-embedding-2` via gemini-ollama-proxy
(the `nomic-embed-text` name is an alias to gemini-embedding-2).

- A: run gemini-ollama-proxy on idc01 → vectors stay compatible.
- B: real local Ollama `nomic-embed-text` (CPU) → kills quota
  dependency, but stored vectors become incomparable — full reindex
  via `scripts/mddb/reindex.py`.
- Recommendation: A at migration, evaluate B later.

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
- `MDDB_AUTH_ENABLED=true` + per-consumer keys (unauthenticated today).
- `public:` bank flag enforcement end-to-end.
- Disk encryption / provider threat model before real personal data.
- notebooklm-rest move, only if dedicated Google account adopted.

## 11. Phases

- M0 done — provision + harden idc01 (SSH keys, ufw, fail2ban, podman)
- M1 done — tailnet join + accept-routes (michael-ha subnet route pending)
- M2 done — Caddy edge + sslip.io + ACME; ada-pi-pwa proxied + healthy
- M3 done — ada-pi checkout + env/keys + rendered banks; all 3 up
- M4 pending — MDDB migration per §4
- M5 pending — home Ada units → standby; move public URLs off Funnel
- M6 pending — scheduled jobs; SSOT registration; health endpoints
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
