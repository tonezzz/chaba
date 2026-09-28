# mn01 relocation → Michael's home: service disposition plan (Devin)

Date: 2026-09-23 · Author: Devin · Status: **v3 — Phase 1 EXECUTED 2026-09-24**
Companion: `idc01-ha-ada-url-migration-devin.md` (URL/pros-cons analysis)

## Executed 2026-09-24 (decisions: ada-michael → idc01; tailnet-only; leftovers → dell)

- **idc01 serve routes (tailnet-only)**: `/apps/ha/ada-tony` → :8002,
  `/apps/ha/ada-michael` → :8003. Health, PWA page, and **WS verified**
  (`{"type":"ready"}` through `wss://idc01…/apps/ha/ada-tony/ws`).
- **mn01 caddy bridges live**: both `/apps/ha/ada-*` paths now proxy to
  `https://idc01.taila0626a.ts.net` — the public mn01 funnel URLs transparently
  terminate on idc01 (verified via public health + WS).
- **mn01 adas → standby**: `ada-ha-tony` + `ada-ha-michael` stopped+disabled.
- **google-home-mcp → tony-dell**: image transferred via `podman save|load`,
  quadlet installed (`BIND_HOST=100.68.142.13:8004`), `/mcp` answers; mn01 unit
  stopped+disabled.
- **mcp-link-monitor → tony-dell**: `mcp-link-monitor.service` enabled+running
  against `~/CascadeProjects/chaba`.
- **ada-memory jobs → idc01** (canonical M6 partially done): `chaba-vault`
  rsynced to `~/CascadeProjects/chaba-vault` on idc01; all 4 timers
  (sync/drift/gaps/obsidian-vault-sync) enabled — obsidian-vault-sync rewritten
  to local rsync → `~/obsidian-app/vault`. First sync ran; exits non-zero only
  on a legit content conflict (`extract-2026-09-21-a41866e664-0`).
- **Retired on mn01**: obsidian-vault(+sync), notebooklm-mcp, playlived,
  playlive-chrome, chaba-audit(-watchdog) timers — all stopped+disabled.
- **yolo-xiaomi → tony-omen**: deployed at `~/CascadeProjects/chaba/
  experiments/ultralytics-yolo-ha`, `opencv-python-headless` added to venv,
  unit env `GO2RTC_BASE=http://192.168.2.67:1984` +
  `HA_BASE=https://tony-dell…:8123`. Live on `192.168.2.86:8780`; HA config
  retargeted (`configuration.yaml`, `templates.yaml`) and live-reloaded via
  `rest.reload`/`rest_command.reload`/`template.reload` — **no HA restart**.
  `sensor.yolo_person_count` verified reading omen. dell's unit disabled;
  `/apps/yolo/` page patched to `192.168.2.86:8780`.
- **idc01 SSH host key** changed (rebuild ~15:00 09-23); verified via omen,
  re-accepted on dell.

## Still open

- Public Ada URL cutover to a permanent edge (mn01 funnel bridge is temporary;
  re-pair devices when the final URL is chosen — tailnet-only serve is already
  usable by tailnet clients *today*).
- `ada-memory-sync` conflict doc on idc01 (manual resolve or `--take-remote`).
- idc01 `tailscale0` MTU fix via console (DF >~1030B still dies; TCP copes).
- michael-dev dedup (dell vs omen), gpu-queue placement, dev/ephemeral
  retirements on dell, funnel `/` exposing bserver publicly.

---

> **v2 — reconciled with `chaba/docs/ada-memory/tony-projects/public-host-plan.md`
> (canonical, v3c) + live state verified 2026-09-23 ~15:30.**
>
> The canonical plan is further along than this doc originally assumed:
> - **All three Ada backends already run on idc01** (:8001/:8002/:8003, systemd
>   user units, healthy — verified). Home units are meant to become *standby*,
>   not the primary home. → "move ada-ha-tony to tony-dell" below is SUPERSEDED.
> - **MDDB already migrated to idc01:11023** (1.47 GB db, live; mn01 Ada envs
>   repointed; tony-dell mddb stopped).
> - **obsidian-vault already on idc01** (:8443 tailnet-only) — no dell move needed.
> - Direction is **Option C** (idc01 edge, real domain later via Cloudflare) —
>   the re-pair churn is being paid regardless, so B (tony-dell funnel) is now
>   the less attractive of the two.
> - idc01 was rebuilt ~15:00 (uptime 2:38 at check) → new SSH host key; verified
>   legit via tony-omen's trusted path and re-accepted on dell.
> - **Open infra issue:** tailnet MTU blackhole to idc01 persists for DF packets
>   >~1030B (ping -M do 1400 dies); TCP is clamped and works fine now — multi-KB
>   fetches + MDDB OK, mn01 memory errors stopped. Still worth fixing
>   `tailscale0` MTU on idc01 when console access is available.
> - ada-ha-tony/-michael on idc01 are **loopback-only** — no serve route yet;
>   cutover needs serve entries or caddy-edge routes added.

## Host roles after the move

| Host | Role | Capacity |
|---|---|---|
| tony-dell | LAN core: tony-ha, cameras, casting, data stores, light apps | 8c / 14Gi — already loaded (LA ~6.8, disk 81%) |
| tony-omen | Compute/GPU node, server-role services | 12c / 30Gi — headroom |
| idc01 | Public edge / offsite always-on | 2c / 7.8Gi VPS — small; WARP egress quirks |
| mn01 @ Michael's | Michael-local edge: ada-ha-michael + michael-side tools | 8c / 7.1Gi |
| michael-ha | HA host only — don't pile on | — |
| kk-macbook | Client | — |

## mn01 service dispositions

| Service | Port | Disposition | Notes |
|---|---|---|---|
| ada-ha-michael | 8003 | **mn01 (co-located) or idc01 — open** | idc01 already runs it, but idc01 **can't reach michael-ha** today (no subnet route advertised; open question in the canonical plan). Once mn01 lands at Michael's it becomes the natural home — co-located with michael-ha, no route needed. Recommend: keep it on mn01 post-move unless centralization on idc01 is preferred. |
| ada-ha-tony | 8002 | **idc01 (already running)** | Primary = idc01:8002 (healthy); mn01 unit → standby after URL cutover. See "Ada Tony URL" below. |
| caddy-mn01 | 8080 | Stays, trimmed | Keeps serving while mn01 lives at Michael's — as bridge (see URL options) and/or ada-michael funnel. Drop ada-tony + obsidian routes after cutover. |
| google-home-mcp | 8004 | **→ tony-dell (or omen)** | `CAST_HOSTS=192.168.2.85` is a *Tony-LAN* cast device — must stay on Tony's LAN regardless of where the box lives. |
| obsidian-vault | 8004 lo | **Already on idc01 :8443** (tailnet-only) | Deployed per canonical plan; just retire the mn01 unit + sync timer. |
| playlived + playlive-chrome | 9230/9223 | **Retire or → omen** | tony-dell and omen both already run playlived; confirm nothing targets mn01:9230 specifically, then retire. |
| notebooklm-mcp | — | **Retire on mn01** | tony-dell already runs an instance with its own auth profile. |
| mcp-link-monitor-mn | — | **→ tony-dell** | Host-connectivity monitor; fold into dell's monitoring set or run same script there. |
| timer: ada-memory-sync/drift/gaps | — | Split | Tony-instance memory jobs → tony-dell; michael's stay on mn01. |
| timer: obsidian-vault-sync | — | → tony-dell (with the vault) |
| timer: chaba-audit(-watchdog) | — | **Retire on mn01** | tony-dell already runs chaba-audit timers. |
| timer: launchpadlib-cache-clean, ubuntu-insights | — | Stays | Host-local OS maintenance. |

## Ada Tony public URL — the unavoidable change

Today: `https://mn01.taila0626a.ts.net/apps/ha/ada-tony/` (funnel on mn01 → :8002).
The canonical plan already decided the direction: **public URLs move off Funnel
onto the idc01 edge** (real domain via Cloudflare later). Options now:

| Option | URL | Client churn | Trade-off |
|---|---|---|---|
| A. Keep mn01 funnel → proxy over tailnet to idc01:8002 | **unchanged** | none | Zero migration cost; perfect *transition bridge* while mn01 is alive at Michael's — but don't leave it permanent (public ingress depending on a box in someone else's home). |
| B. tony-dell funnel `/apps/ha/ada-tony/` → idc01:8002 | changes | re-pair devices | Fewest hops to the *edge*, but keeps funnel dependency and a second home-node public surface. Now superseded by C. |
| C. **idc01 edge → idc01:8002** (chosen direction) | changes | re-pair devices | Serve/funnel or caddy-edge route on idc01 itself — backend and edge on the same host, no home dependency at all. Needs: expose :8002 via serve or caddy-edge; pick public vs tailnet-only (canonical plan Q2). |

Cutover mechanics for C: on idc01 add `tailscale serve` for :8002/:8003
(tailnet-only, zero re-pair for tailnet clients) and/or a caddy-edge route +
funnel for public access. mn01's ada units then go `disabled` (standby).

## tony-dell service assessment

dell is a *desktop* doing server duty — overloaded (LA ~6.8, 81% disk, documented
crash/swap history). Triage:

**Keep on dell (LAN-tied, must stay home):**
`tony-ha`, `go2rtc`, `node-red`, `camera-monitor`, `xiaomi-token-refresh`,
`cam-frame-refresh`, `camera-panel`, `xmeye-vms-vnc`, `websockify-*`,
`cast-browser`/`cast-desktop`/`cast-ha-panel`, `mha-state-push`, `yomi-api`
(LINE cookie locality), `notebooklm-mcp`/`notebooklm-rest` (Chrome auth profile),
`trade-api`, `bserver`, `status-data-api`, `web` (caddy+funnel), `gev-*`,
`gods-eye-view-api`, `rview-*`, `gemini-ollama-proxy`, `redis`, `weaviate`,
`chaba-postgres-16`, `workflows-mcp`, `helm`, `raceman-*`, `mcp-*` glue,
`chaba-tunnel`, `dnsmasq-postgre`, `rclone-gdrive`, desktop-session services.

**Move candidates (off the desktop):**
- `yolo-xiaomi` → **tony-omen** — CPU-only YOLO on dell; omen has GPU + TensorRT
  already proven via WallDance. Clear win.
- `michael-dev` (:8124) → **consolidate** — a second michael-dev already runs on
  tony-omen (known duplicate). Pick ONE host; omen preferred (server-role, more
  RAM, frees ~480MB on dell) — but deploy scripts (`deploy-card.sh`, promote-*)
  target dell paths, so this is a workflow change, not just a service move.
- `gpu-queue(+processor)` → evaluate — the queue fronts GPU work; if consumers are
  on omen, move the queue there too.
- Dev/ephemeral: `dev-miniapp-v0`, `secrets-console`, `chaba-gemini-mic-test`,
  `mcp-debug-sse` — candidates to retire or consolidate; low value per service.
- `ada-pi-pwa` on dell (:8001) → **standby** per canonical plan — idc01 :8001 is
  now primary. Keep the unit installed but `disabled` once cutover is confirmed.

**Do NOT move:** tony-ha (must be on the home LAN for plugs/cameras/Chromecast),
go2rtc, casting, DVR VMS — anything that talks to 192.168.2.x devices.

## Phased plan (v2 — post-reconciliation)

**Phase 0 — prep:**
1. Decide ada-ha-michael's home: mn01@Michael's (co-located, recommended) vs
   idc01 (needs michael-ha reachable — Nabu Casa URL or mn01 subnet route).
2. On idc01: add `tailscale serve` for :8002/:8003 (tailnet-only) and/or
   caddy-edge routes for the public Ada paths — decide public vs tailnet-only
   (canonical plan Q2).
3. Grep SSOT/scripts for hardcoded `mn01:9230`, mn01 notebooklm, and
   `mn01.taila0626a.ts.net` references.

**Phase 1 — parallel run (before mn01 leaves):**
4. Repoint mn01 caddy `/apps/ha/ada-tony/*` → `idc01:8002` (Option-A bridge —
   existing public URL keeps working through the transition).
5. Move `google-home-mcp` to dell/omen (re-target BIND_HOST), `mcp-link-monitor`
   to dell. Retire mn01's `obsidian-vault`, `notebooklm-mcp`, `playlived`,
   `playlive-chrome`, duplicate audit timers.
6. Move `yolo-xiaomi` to omen.

**Phase 2 — cutover (mn01 ships):**
7. Switch Ada Tony public ingress to the idc01 edge (Option C); re-pair/reinstall
   devices (origin change is unavoidable now — pay it once).
8. mn01's ada-ha-tony (+ ada-ha-michael if centralized) → `disabled` standby.
9. At Michael's: mn01 keeps caddy funnel; either keeps serving ada-michael
   (recommended) or just bridges during transition.
10. Update SSOT: `ssot.apps.ada_ha.yml`, `ssot.services.yml`, `ssot.mysystem.*`,
    health targets.

**Phase 3 — rebalance/fixups:**
11. michael-dev dedup (omen vs dell) + deploy-script updates.
12. gpu-queue placement; retire dev/ephemeral services on dell.
13. tony-dell `ada-pi-pwa` (:8001) → standby per canonical plan (idc01 :8001
    is primary now).
14. Fix funnel `/` on tony-dell exposing bserver publicly.
15. Fix idc01 `tailscale0` MTU (~1280 or TCPMSS clamp) via console — the DF
    blackhole is still there even though TCP currently copes.

## Open questions

- ada-ha-michael home: mn01@Michael's (co-located, recommended) vs idc01
  (centralized but can't reach michael-ha today).
- Public or tailnet-only for the new idc01 Ada endpoints? (canonical plan Q2 —
  device keys mean public exposure is tolerable, but tailnet-only removes the
  re-pair requirement entirely for tailnet clients.)
- Whose google-home-mcp flow is canonical? (LAN cast target says Tony's —
  confirm before moving.)
- Does anything external hardcode `mn01:9230`, mn01 notebooklm, or
  `mn01.ts.net` paths besides the Ada PWAs? (grep SSOT before Phase 1.)
- Keep mn01 powered at Michael's? Determines how long Option-A bridge can live
  and whether ada-michael funnel stays the public path.
- michael-dev consolidation target: omen (cleaner) vs dell (workflow-compatible)?
