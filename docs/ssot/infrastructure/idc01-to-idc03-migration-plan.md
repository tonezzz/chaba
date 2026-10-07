# idc01 → idc03 Migration Plan

> **HISTORICAL (executed 2026-10-05/06):** the migration is complete — idc03 is the primary VPS (mddb leader, Ada stack, public edge); idc01 is now warm-DR (mddb-follower :11123, standby edge, masked former-prod units). The `idc01` references below describe the pre-migration state and are intentionally preserved — do not rewrite them to idc03. Job record: `docs/ssot/jobs/infrastructure/2026-10-05-idc01-to-idc03-migration.yml`.

**Status:** Phase 1 — inventory + plan only. No production changes made.
**Date:** 2026-10-05 · **Card:** `idc01-to-idc03-migration` · **Scope decision (Tony, 2026-10-05):** migrate *everything* off idc01 to idc03.
**Method:** read-only SSH (`BatchMode`) on idc01/idc02; no service was stopped, moved, or modified.

---

## Host summary

| Host | Public IP | Tailnet IP | Provider | vCPU | RAM | Disk | Role |
|---|---|---|---|---|---|---|---|
| **idc01** (source) | 157.85.110.99 | 100.74.146.0 | Siamdata (AS56309, BKK) | 2 | **31 GiB** | 96 G, 60 G used (37 G free) | mddb leader + Ada stack + public edge |
| **idc02** (untouched) | 45.136.236.190 | 100.123.163.11 | other VPS | 4 | 15 GiB | 290 G, 226 G free | mddb follower, caddy-edge (*-ha.surf-thailand.com), vcast-real-6/7, camwall-edge, mddb-ops, offloaded timers |
| **idc03** (target) | 157.85.102.125 | 100.102.134.91 | Siamdata (same AS as idc01) | **?** | **?** | **?** | empty — joined tailnet 2026-10-05 ~13:15Z |

> SSOT drift note: `ssot.idc01.yml` says "2 vCPU, ~8 GB RAM" and `ssot.mysystem.home.yml` says "12G/100G" — the live box is 2 vCPU / **31 GiB** / 96 G. Update during Phase 2.

### ⚠ Phase-2 gate: idc03 ssh access
`tony@idc03` and `root@idc03` reject every key tried from tony-dell (`id_ed25519`, `id_cascade`, `chaba_tunnel`, `id_mcp_debug`, `michael-ha`), and idc01→idc03 / idc02→idc03 deny `tony` too. sshd answers on **both** tailnet:22 and **public :22** (unlike idc01/idc02 where ufw filters public 22 — idc03 is not yet hardened). Ports 80/443 closed.

**Needed from Tony (or a Phase-2 provisioning step):** authorize `tony-dell`'s ed25519 key on idc03 via the Siamdata panel console, then run the idc02-style baseline (ufw deny-in + tailscale0 + 80/443 + 22 tailnet-only, `loginctl enable-linger tony`, podman+uidmap, fail2ban, sysctl 90-tuning). Until then, idc03 **RAM/disk/vCPU are unverified** — the plan assumes the LG2SS+-class box (≥150 G disk); verify first.

---

## (a) Full idc01 inventory

Host: Ubuntu 24.04.5, kernel 6.8.0-142, QEMU guest (qemu-guest-agent), `tony` linger enabled, passwordless sudo, fail2ban active, WARP installed but **stopped+disabled** (2026-09-24 wedge incident — leave off), BBR+fq sysctl. Cron: none (user crontab empty; system cron.d stock only).

### Containers — 9 running, rootless podman, quadlets in `~/.config/containers/systemd/`

| Container | Image | Listen | Code / data | Notes |
|---|---|---|---|---|
| **mddb** | `localhost/mddb:2.15.4-allowlist` (patched `mddbd-patched` bind-mounted from `~/.config/containers/mddb/bin`) | tailnet :11023 http, :11024 gRPC, :9000 MCP, loopback :18026 | data `~/.config/containers/mddb/data` (**4.3 G**), vaults 12 K | `MDDB_REPLICATION_ROLE=leader`, `NODE_ID=idc01`. **Inline secrets in quadlet** (`MDDB_MCP_API_KEYS`, `MDDB_REPLICATION_SECRET`) — move to EnvironmentFile on idc03. Dropin: GOMEMLIMIT=22000MiB, MemoryHigh=16G, MemoryMax=20G (tuned for the 31 G box — **retune for idc03**). ExecStartPost → mddb-vector-reindex. Embedding → gemini-ollama-proxy :11435. |
| **ollama** | `ollama/ollama:latest` | tailnet :11434 | named volume `ollama-data` (~3.8 G): moondream 1.7 G, phi3/llama3.2 2.0 G, nomic-embed-text 274 M | serves mcp-llama + gemini-proxy fallback tailnet-wide |
| **gemini-ollama-proxy** | node:22-alpine | loopback :11435 | code `~/.config/containers/mddb/proxy` (28 K), env `mddb-gemini.env` | healthy; mddb's embedding endpoint |
| **caddy-edge** | caddy:2 | **public** 80/443 (bind 157.85.110.99) + tailnet :80 | `~/.config/caddy/Caddyfile`, certs `~/.config/containers/caddy/{data,config}` | routes below |
| **camwall-edge** | caddy:2-alpine | tailnet :8380 | serves `~/.local/share/camwall` (18 M) read-only | static thumbnail feed for /apps/camwall |
| **input-bridge** | node:22-alpine | **0.0.0.0:3010** ⚠ | code `~/apps/input-bridge` (deploy target), data `~/.local/share/input-bridge` | vcast WS relay + display registry; env `input-bridge.env`. **Deviation:** SSOT claims `INPUT_BRIDGE_BIND` pins tailnet IP, live binds wildcard — ufw is the only guard. Fix bind during migration. |
| **mddb-panel** | tradik/mddb:panel-latest | tailnet :3002 | host-patched `~/mddb-panel/server.js` bind-mounted | points at mddb :11023 |
| **vcast-headless-2** | node:22-alpine | — | `vcast-headless@2.service` (podman run --rm template, not a quadlet file) | deterministic test screen |
| **vcast-headless-4** | node:22-alpine | — | `vcast-headless@4.service` | same |

Unused images to NOT migrate: open_notebook 1.77 G, surrealdb, golang 912 M, old mddb 2.15.0/2.15.3 variants, panel dupes (~4 G reclaim). **~18 anonymous orphan volumes** — skip.

### Persistent user services (non-container)

| Unit | Listen | App dir / venv | Env (secrets) | Dropin |
|---|---|---|---|---|
| ada-pi-pwa | lo :8001 | `~/CascadeProjects/ada-pi` + `.venv` | ada-pi-pwa.env, notebooklm-rest-api.env | waits on mddb /health |
| ada-ha-tony | lo :8002 | same | ada-ha-tony.env, notebooklm | same |
| ada-ha-michael | lo :8003 | same | ada-ha-michael.env, notebooklm | same |
| ada-dev | lo :8005 | same | ada-dev.env, notebooklm | **running but unit `disabled`** (lab instance — decide migrate or retire) |
| ada-line-relay | lo :8912 | ada-pi `backend.line_relay` | ada-ha-tony.env, line-bot.env | owns ชบา bot's only webhook slot |
| ada-tg-relay | lo :8911 | ada-pi `backend.tg_relay` | ada-ha-tony.env, telegram-bot.env | |
| obsidian-vault | lo :8004 | `~/CascadeProjects/chaba-vault/apps/obsidian/server.py`, `~/jobenv` venv | obsidian.env | Ada Memory Vault web app |
| doc-archive | **tailnet :11025** ⚠ | `~/.local/share/doc-archive` venv, stacks/idc01/doc-archive | doc-archive.env | undocumented listener — not in security SSOT |
| jev-student | tailnet :8778 | `~/CascadeProjects/open-jev` venv, `serve:app` | — | distilbert confirm-gate; models `~/jev-student` (2.6 G, 5 ckpts) |
| open-jev | (disabled, would be :8777) | open-jev | — | retired in favor of jev-student |

### Timers (user) — 22 enabled of 24

| Cadence | Timers |
|---|---|
| every 30 s | **cam-wall-pull-vps** (heaviest cadence on the box) |
| hourly | doc-mirror (OnBootSec 3min + OnUnitActiveSec 1h), ada-memory-sync, ada-scenario-smoke, news-flood |
| 15 min | mddb-embed-probe, ops-health-report, cam-wall-cms-vps (:02+:17…) |
| 6 h | mddb-memory-standard (:37) |
| daily | ada-bench-casting 02:00, mddb-backup 02:30, obsidian-vault-backup 03:00 |
| weekly | ada-recall-canary Sun 04:30, mddb-restart Sun 05:00, ada-memory-drift Sun 09:00, -gaps 09:30, -distill 09:45, ada-scenario-research Mon, -cms Tue, -memory Wed, -reports Thu, -tools Fri, -casting Sat 04:30, ada-embed-bench Sat 06:00 |
| disabled (do not migrate) | jev-bench, report-distill, open-notebook-backup, open-notebook-restore-check, podman-auto-update, launchpadlib-cache-clean(stock) |

System timers: stock + podman-auto-update only.

### Ports / exposure (live `ss`, verified)

- **Public 157.85.110.99:** 80, 443 (caddy-edge). Nothing else — ufw denies all other inbound incl. public :22.
- **Tailnet 100.74.146.0:** 22 (ssh), 80/443/8443 (tailscale serve), 3002, 3010(wildcard), 8380, 8443, 8778, 9000, 11023, 11024, 11025, 11434, 47516 (unidentified, likely tailscaled-internal).
- **Loopback:** 8001–8005, 8911, 8912, 11435, 18026, 2019 (caddy admin), 53 (resolved).
- **ufw:** deny-in default; allow 80/tcp, 443/tcp, all on tailscale0, 22 on tailscale0; deny 22 elsewhere.

### TLS / HTTP routes

| Route | Backend | Notes |
|---|---|---|
| `https://157.85.110.99.sslip.io/*` | ada-pi-pwa :8001 | IP-derived name — dies with the IP |
| `https://api.surf-thailand.com/*` | ada-pi-pwa :8001 | **Cloudflare-proxied** (resolves 172.67/104.21) → origin 157.85.110.99 |
| `…/webhook/tg` → :8911, `…/webhook/line` + `/relay-img/*` → :8912 | relays | both hostnames; Telegram/LINE webhook URLs point at the domain — DNS repoint covers them |
| `…/cms*` on public names | 404 | intentionally closed |
| `http://idc01.taila0626a.ts.net/cms*`, `/api/cms*` (caddy tailnet :80) | ada-ha-michael :8003 | consumed by **idc02 caddy-edge → tony-ha.surf-thailand.com/cms** |
| tailscale serve | / → :8001, /apps/ha/ada-tony → :8002, /apps/ha/ada-michael → :8003, :8443 → :8004 | funnel: none |

### Data to move (~30 G total, ~12 G essential)

| Path | Size | Migrate? |
|---|---|---|
| `~/.config/containers/mddb/data` | 4.3 G | **yes** — via replication follower→promote (preferred) or rsync of stopped DB |
| `~/mddb-backups` | 17 G | partial — retention keeps last 4+4 anyway; rsync latest 2–4 only |
| podman `ollama-data` volume | ~3.8 G | yes (or `ollama pull` fresh — models are public) |
| `~/jev-student` | 2.6 G | `ckpt` (deployed) + `ckpt-v2-20261002`; older ckpts optional |
| `~/CascadeProjects/ada-pi` | 1.7 G | yes (clean repo + .venv — rebuild venv instead of rsync if faster) |
| `~/CascadeProjects/open-jev` | 1.2 G | yes |
| `~/CascadeProjects/chaba` | 385 M | yes |
| `~/CascadeProjects/chaba-vault` | 125 M | yes — **41 dirty files; reconcile/commit before rsync** |
| `~/.local/share/ada` | 508 M | yes (audio 501 M, transcripts, jev corpus, events) |
| `~/.local/share/doc-archive` | 77 M | yes (venv + state) |
| `~/.local/share/{camwall,input-bridge,ada-pi}` | ~25 M | yes |
| `~/.config/secrets/` (17 env files) | 76 K | yes — full dir + `~/.config/camwall.env`, `~/.ssh/camwall-push` |
| `~/apps/input-bridge`, `~/mddb-panel/server.js`, `~/mddb-backup.sh`, `~/obsidian-vault-backup.sh`, `~/jobenv`, `~/.venvs/camwall`, `~/chaba-scripts`, `~/obsidian-backups` | ~70 M | yes |
| open-notebook-backups 69 M + retire-archive 24 M + `obsidian-app-retired tar` | ~95 M | **retire/archive** — approved-retired service residue; cold-copy or drop |
| `~/mddb-bench` 41 M, `~/open-notebook-*`, `~/oom` | — | drop |

### Secrets inventory (`~/.config/secrets/`)
`ada-dev.env, ada-google-calendar-token.json, ada-ha-michael.{env,keys.json}, ada-ha-tony.{env,keys.json}, ada-pi-pwa.env, cloudflare.env, doc-archive.env, home-assistant-token.env, input-bridge.env, line-bot.env, mddb-gemini.env(+bak), notebooklm-rest-api.env, obsidian.env(+bak), telegram-bot.env` + `~/.config/camwall.env` + `~/.ssh/camwall-push` keypair. Plus inline secrets in `mddb.container` to relocate.

### Outbound dependencies (things idc01 reaches, or that reach idc01)

- `tony-dell-m2m` ssh alias → 100.68.142.13:8222 — doc-mirror rsync target, ada_doc_print.
- `camwall-idc02` ssh alias → idc02 via `~/.ssh/camwall-push` — camwall lane.
- **idc02 mddb follower** pulls from leader idc01:11024 → repoint to idc03.
- **idc02 caddy-edge** proxies `…/cms` → idc01.taila0626a.ts.net → repoint to idc03 hostname.
- **mn01 Caddy** reverse-proxies legacy ada paths → idc01:8002/8003 → repoint or drop.
- Consumers pinned to `100.74.146.0`/`idc01.taila0626a.ts.net`: mcp-llama `LLAMA_URL :11434`, omen `ssot-mddb-sync`, devin tools `llama_url`, ada dropin health-checks, `VCAST_REDEEM_HOSTS`, MDDB_BASE_URL in quadlets/timers, jev-bench target, doc-mirror `MDDB_BASE`. **Every hardcoded 100.74.146.0 must be rewritten to 100.102.134.91** — this is the bulk of Phase-2 diff work; grep `~/CascadeProjects/chaba` on idc01 + this repo for `100.74.146.0|idc01` when executing.

---

## (b) Per-item decision + dependency order

Legend: **M** = migrate, **R** = retire/drop, **A** = needs Tony approval.

| # | Item | Decision | Depends on |
|---|---|---|---|
| 0 | idc03 access + baseline hardening | **M — GATE** (A: Tony adds ssh key or approves provision run) | — |
| 1 | **mddb** (leader) | **M** — follower-on-idc03 → verify → promote → idc02 repoints leader | 0, secrets, embed proxy for cold-start? (no — promote works without) |
| 2 | `~/.config/secrets` + all env files | **M** — rsync first, everything needs them | 0 |
| 3 | gemini-ollama-proxy | **M** — small, mddb embed dep | 2 |
| 4 | ollama + models | **M** — phi3/nomic/moondream; can re-pull instead of copying | 0 |
| 5 | ada-pi repo + venv; ada-pi-pwa, ada-ha-tony, ada-ha-michael | **M** — core Ada | 1 healthy (dropins block on mddb), 2 |
| 6 | ada-line-relay, ada-tg-relay | **M** — webhook target is domain → safe before DNS flip (both ends live briefly) | 5 |
| 7 | obsidian-vault + chaba-vault + obsidian-vault-backup timer | **M** | 2, chaba-vault reconcile (A if dirty files ambiguous) |
| 8 | input-bridge + vcast-headless@2,@4 | **M** — fix :3010 wildcard→tailnet bind | 2, secrets |
| 9 | camwall-edge + cam-wall-pull/cms timers | **M** — verify camwall-idc02 key still wanted | 2 |
| 10 | doc-archive + doc-mirror timer | **M** — recreate tony-dell-m2m alias on idc03 | 2 |
| 11 | jev-student (+ckpt) | **M** — open-jev stays retired | 2 |
| 12 | mddb-panel | **M** — repoint MDDB_SERVER to idc03 tailnet IP | 1 |
| 13 | 22 enabled timers | **M** — enable only after their services verified | all |
| 14 | caddy-edge + TLS + CF DNS repoint api.surf-thailand.com → 157.85.102.125 | **M — LAST** (A: public cutover) | 5,6 + everything verified |
| 15 | tailscale serve config | **M** — recreate on idc03 after services up | 5,7 |
| 16 | ada-dev (:8005) | **A** — running-but-disabled lab; migrate or stop? | — |
| 17 | mddb-backups 17 G | **A** — rsync latest 4 only vs all | — |
| 18 | open-notebook residue, old jev ckpts, orphan volumes/images | **R** — drop (approved retired) / archive to dell if wanted | — |
| 19 | WARP, :47516, launchpadlib stock units | **R** — do not recreate | — |

**Dependency waves:** `0 → 2 → {1,3,4} → {5,6,7,8,9,10,11,12} → 13 → {14,15} → soak 24–48 h → idc01 shutdown decision.`

---

## (c) idc03 capacity check

| Check | Result |
|---|---|
| Reachability | tailnet 100.102.134.91 online; sshd on tailnet:22 **and public:22 open** (pre-hardening) |
| vCPU / RAM / disk | **UNKNOWN — ssh denied, see gate §0.** Expectation per `idc-vps-game` card: LG2SS+ class, ~150 G disk. Must verify ≥ 4 G RAM and ≥ 40 G free disk before starting; comfortable target ≥ 8 G RAM / 60 G free. |
| Minimum footprint | ~12 G essential state + ~5 G images + OS ≈ 25–30 G; with full backups ≈ 45 G |
| RAM sizing | mddb dropin caps at MemoryHigh=16G/Max=20G/GOMEMLIMIT=22G — **retune to idc03's real RAM** (it ran on 8 G historically) |
| Fallback if undersized | put `mddb-backups` archive + ollama image-volume on idc02 (226 G free) — but services themselves must fit on idc03 |

## (d) Cutover + rollback (per item)

Global safety: **idc01 stays fully running until soak passes** — every item's rollback is "repoint back to idc01 / restart idc01 unit". Nothing is deleted on idc01 during migration.

| Item | Cutover | Verify | Rollback |
|---|---|---|---|
| mddb | run `mddb:2.15.4-blrotate`/allowlist fork on idc03 as `role=follower, leader=idc01:11024`; when converged, promote idc03 to leader (role=wr), repoint idc02 follower's leader addr to idc03:11024 | `/health`, `/v1/stats` docs count parity, follower lag=0 | keep idc01 leader untouched until promotion verified; if follower fails, drop idc03 container — zero impact |
| secrets | rsync `~/.config/secrets`, `camwall.env`, ssh keys | file count + perms 600 | n/a (copy only) |
| ada-pi stack | rsync repo (+ rebuild .venv), install units+dropins, start on idc03 loopback | curl :8001-8003 /health tailnet-side | services still live on idc01 |
| relays | start on idc03; webhooks still hit idc01 via DNS until flip | relay logs ok | stop idc03 units |
| ollama | `podman pull` image + `ollama pull` models (or `podman volume export`→import) | `ollama list` + test embed | n/a |
| input-bridge/vcast | rsync `~/apps/input-bridge`, fix `INPUT_BRIDGE_BIND=<idc03-tailnet-ip>`, start @2/@4 | :3010 on tailnet only; displays reconnect | old instance still up |
| doc-archive/jev/mddb-panel | rsync state + start | probe tailnet ports | idc01 copies intact |
| timers | install units, `enable` in batches after services verified | `list-timers` + first runs green | disable on idc03 |
| **DNS/edge** | stage caddy-edge on idc03 (`bind 157.85.102.125`), then repoint CF `api.surf-thailand.com` → idc03 public IP | `curl -H 'Host: api.surf-thailand.com' https://157.85.102.125`, then real-DNS 200 on `/` + webhook paths | **flip CF DNS back to 157.85.110.99** — idc01 edge untouched; CF TTL ~5min |
| tailscale serve | `tailscale serve` config on idc03 mirrors idc01's | https://idc03.taila0626a.ts.net/ renders | reset serve config |
| consumer repoint | update mcp-llama LLAMA_URL, ssot-mddb-sync, mn01 aliases, idc02 cms route, VCAST_REDEEM_HOSTS, ada dropin health URLs → 100.102.134.91 | end-to-end Ada request + mddb search from dell | sed-back / git-revert configs |

Soak: 24–48 h with both hosts up; then Phase 3 = idc01 decommission decision.

## (e) What stays / doesn't move

- **idc01 keeps nothing running** per Tony's "everything to idc03". After soak: provider cancel vs keep-as-standby = **Tony decision**.
- **idc02 unchanged** except: mddb follower leader-address repoint, caddy-edge cms upstream repoint.
- **mn01** legacy ada-path aliases → repoint to idc03 or drop (**A**).
- **Retired (not carried):** open-notebook stack+archives, open-jev, disabled timers, orphan podman volumes (~18), stale images, WARP.

## Flagged for Tony approval (Phase 2+)

1. **idc03 ssh authorization** — hard blocker; Siamdata panel or password.
2. **CF DNS repoint** `api.surf-thailand.com` → 157.85.102.125 (public cutover).
3. **mddb leader promotion** on idc03 + idc02 follower repoint.
4. `~/CascadeProjects/chaba-vault` **41 dirty files** on idc01 — commit/stash decision before rsync.
5. `ada-dev` :8005 — migrate or leave off.
6. `mddb-backups` — latest-N vs full 17 G.
7. mn01 alias endpoints — repoint or retire.
8. Post-soak: keep renting idc01 as standby or cancel.
9. Fixes to fold in while moving: input-bridge wildcard bind, doc-archive :11025 → security SSOT, mddb.container inline secrets → EnvironmentFile, mddb memory dropin retune.

---

*Inventory method: `podman ps/images/inspect/stats`, `systemctl --user list-units/-files/list-timers`, `ss -tlnp`, `ufw status`, `tailscale serve/funnel status`, `du/df`, unit+quadlet+Caddyfile reads — all read-only on 2026-10-05 ~20:55 +07.*
