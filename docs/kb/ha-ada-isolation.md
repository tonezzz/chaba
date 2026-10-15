# Ada → HA isolation standard

An Ada backend failure (quota storm, tool loop, token leak, bad deploy, host
exhaustion) must not damage or take down an HA instance. Written after the
2026-10-11 ada-ha-tony Gemini Live reconnect storm; tony-ha is prod, kk-ha is
KK's member node — both must survive any Ada meltdown. Live posture report:
CMS index `ha-ada-isolation` (generator `scripts/ada/ha-ada-isolation-cms.py`).

## Coupling map (verified 2026-10-15)

| Ada backend | host:port | upstream HA | HA credential | surface into HA |
|---|---|---|---|---|
| ada-ha-tony | idc03:8002 | tony-ha via tailnet :8123 | **svc-ada LLAT (non-admin)** — since 2026-10-15 | REST only: `/api/states`, `/api/services/*` for light/switch/fan/input_boolean/cover/button/media_player tools + `office_lights` ~5s poller |
| ada-pi-pwa | idc03:8001 | tony-ha via tailnet | **svc-ada LLAT (non-admin)** — separate token, same user | CMS/enroll frontend **+ full HA tool set** (only 2 exclusions) |
| ada-ha-michael | idc03:8003 | michael-ha via tailnet | **Michael OWNER LLAT** — Phase B pending approval | same tool set |
| ada-kk | idc03:8007 | **none — no `HOME_ASSISTANT_*` in env** | — | voice card dials browser→`/ada-ws/kk`; kk-ha unreachable from the backend |
| ada-kk-dev | idc03:8009 | none — dev twin of ada-kk | — | HA tools excluded |
| ada-dev | idc03:8005 | none (upstream removed) | — | HA tools excluded |

Shared-fate vectors (one failure hits every lane):

- **Gemini keys are now pool-split** (approved decision: "two pools —
  tony-lane vs member/dev"). Live hashes 2026-10-15: tony pool
  `{ada-ha-tony, ada-pi-pwa}` share one key; member lanes each hold their
  own (`ada-kk` = kaewta-paid dedicated, `ada-ha-michael` own key);
  `{ada-dev, ada-kk-dev}` share the dev pool. No key spans both pools — a
  tony-lane storm can no longer starve kk/michael. Remaining gap: the kk
  Live-layer key mint is Tony's GCP-console action (card `kk-gemini-key`).
- **One `ada-voice` checkout + one `.venv` on idc03** serves every backend.
  `deploy-ada.sh` restarts the whole set — a bad commit can kill every Ada
  at once. Deploy order is now the documented canary ladder (dev → relays →
  member → tony last) and the set is explicit: `ada-dev, ada-kk-dev,
  ada-line-relay, ada-tg-relay, ada-tg-relay-kk, ada-kk, ada-ha-michael,
  ada-pi-pwa, ada-ha-tony`.
- **All backends + mddb + kk-ha + michael-dev co-locate on idc03.** Cgroup
  caps now applied to every ada unit (`MemoryMax=2G`, `CPUQuota=150%`;
  `ada-bankq-student` gets `CPUQuota=200%` for inference headroom), plus
  journald rate caps (`30s/1000`). A runaway process can no longer starve
  the HA containers.
- **Old Tony OWNER LLAT is still live** — it remains in
  `chaba-guest.env`, `nodered-ha.env`, `home-assistant-token.env` on
  tony-dell (verified 2026-10-15). Ada lanes no longer use it; revoking it
  is a separate follow-up — it must not happen until those consumers get
  their own svc tokens.
- **HA→Ada direction is clean** (verified in tony-ha config: no
  rest_command/shell_command to Ada). Voice cards and chaba-nest CMS
  iframes fail soft — blank card, not a control-plane failure.

## Isolation standard — per Ada↔HA pair

- [x] **Dedicated non-admin HA user** (`svc-ada`, `svc-kaewta`, …) with its
  own long-lived token. Never a person's account, never owner/admin.
  Buys: admin APIs unreachable, per-action attribution in logbook
  ("by svc-ada"), instant kill via token revoke without touching Tony's
  sessions. HA has no per-entity ACL — service calls stay possible, which
  is what Ada needs anyway.
  *tony-ha lanes done 2026-10-15 (per-lane LLATs: `ada-ha-tony`,
  `ada-pi-pwa`); michael-ha pending approval; kk-ha n/a (no creds).*
- [x] **Per-pool `GEMINI_API_KEY`** — tony lane vs member/dev (Tony's
  decision, 2026-10-11). Done per the pools above; per-lane key for kk's
  Live layer still needs a minted key. `GEMINI_API_KEY_` fallback var
  exists for rotation.
- [x] **Cgroup caps on every ada unit** — `MemoryMax=2G`,
  `CPUQuota=150%` (200% for `ada-bankq-student`), applied via
  `~/.config/systemd/user/<unit>.service.d/isolation.conf` on idc03,
  2026-10-15. Covers backends, relays, bankq-student.
- [x] **Deploy membership explicit** — every long-running ada unit on
  idc03 is in `deploy-ada.sh` `SERVICES`; restart order = canary ladder
  ada-dev → member lanes → ada-ha-tony last.
- [x] **Actuation allowlist per instance** — `ADA_EXCLUDED_TOOLS` is set
  on every env file; `upstream_ha: none` wherever the backend doesn't need
  control (ada-kk, ada-kk-dev, ada-dev).
- [x] **Journal caps** on ada units (`LogRateLimitIntervalSec=30s`,
  `LogRateLimitBurst=1000`) — same `isolation.conf` drop-ins.

## What-if table

| scenario | blast before standard | after standard (2026-10-15 state) |
|---|---|---|
| Gemini quota/reconnect storm | all 5 instances starved on the shared key | contained to the offending pool — tony-lane storm can't starve kk/michael/dev; `ada-gemini-quota-breaker` stops the storm itself |
| tool-call / actuation loop | toggled real devices on prod tony-ha with **owner** perms | tony lanes use non-admin svc token; allowlisted domains; logbook attributes every call. michael lane still owner — pending Phase B |
| ada HA token leak / rotation | owner token = full prod admin; revoking breaks anything else sharing it | svc token only; revoke kills Ada, nothing else. NB: the old owner LLAT still lives in chaba-guest/nodered envs — revoke is a follow-up, see below |
| bad ada-voice deploy | all backends restarted onto broken code together; ada-kk silently stayed old | canary order hits dev lanes first; all units in SERVICES |
| ada mem/cpu leak on idc03 | starved kk-ha + michael-dev + mddb | cgroup caps contain it (2G / 150%) |
| ada log storm | could fill idc03 disk → everything on host | per-unit journald caps (30s/1000) |
| idc03 host dies | kk-ha dies anyway (co-located) — accepted risk | same; tony-ha unaffected (on tony-dell) |
| tony-dell / tailnet down | ada-ha-tony orphaned; bounded retries (httpx 5s timeout; poller min 5s) | same — harmless error churn, no damage |
| ada stopped / killed | voice card + CMS iframes blank; HA control plane untouched | verified 2026-10-15: both tony lanes stopped, `/api/` answered 401 (auth required — HA alive) throughout |

## Execution order

Phase 0 — stop the bleeding (done 2026-10-11): `ada-ha-tony` stayed stopped
until the quota breaker (`ada-gemini-quota-breaker`) and text-lane fix landed.

Phase A — no-prod-touch quick wins (**done 2026-10-15**):
1. Split Gemini keys — done to the approved pool standard; kk Live-layer
   key mint remains Tony's (card `kk-gemini-key`).
2. cgroup drop-ins on all `ada-*.service` units — done (`isolation.conf`,
   `MemoryMax=2G`, `CPUQuota=150%`, bankq-student 200%).
3. ada-kk deploy membership — decided "add" 2026-10-11, in SERVICES since;
   `ada-kk-dev` + `ada-tg-relay-kk` added 2026-10-15 on the same rationale.
4. `LogRateLimitIntervalSec=30s LogRateLimitBurst=1000` drop-ins — done.

Phase B — prod-gated (explicit approval — touches tony-ha):
1. Create user `svc-ada`, non-admin — **done 2026-10-15**
   (`config/auth/create` + `config/auth_provider/homeassistant/create`;
   tool: `scripts/ada/ha-svc-user.py`).
2. Mint long-lived tokens for `svc-ada`, one per lane — **done**
   (`auth/long_lived_access_token`, client_name=lane id).
3. `~/.config/secrets/ada-ha-tony.env` + `ada-pi-pwa.env`
   `HOME_ASSISTANT_TOKEN` swapped, units restarted; `auth/current_user`
   verifies `svc-ada` / `is_admin=false` — **done 2026-10-15**.
4. Revoke the old Tony LLAT — **deferred**: the same token is also in
   `chaba-guest.env`, `nodered-ha.env`, `home-assistant-token.env` on
   tony-dell. Follow-up card: give those consumers their own svc tokens,
   then revoke.
5. Same pattern on michael-ha — **pending Tony approval** (request on the
   card); kk-ha gets `svc-kaewta` if/when ada-kk ever receives HA creds.

Phase C — verify isolation (run after each phase, and after any incident):
```bash
# HA survives ada death — 401 means "auth required": HA alive, just protected
ssh idc03 'systemctl --user stop ada-ha-tony ada-pi-pwa'
curl -s https://tony-dell.taila0626a.ts.net:8123/api/   # expect 401, not timeout
# revoke path works — expect 401 on the ada side and bounded error logging
# caps hold — watch `systemd-cgtop` while ada runs
```
Verified 2026-10-15: with both tony lanes stopped, tony-ha `/api/`
responded 401 and michael-ha 401 — HA control planes untouched.

## Kill switch (fastest first)

1. `ssh idc03 'systemctl --user stop ada-ha-<lane>'` — seconds, reversible.
2. tony-ha UI → the svc user's token list → delete the LLAT — hard sever,
   survives ada restarts.
3. Blank `HOME_ASSISTANT_URL`/`HOME_ASSISTANT_TOKEN` in the lane env file +
   restart — config sever, keeps the assistant alive with HA tools dead.
4. `systemctl --user disable --now` — survives reboots.
