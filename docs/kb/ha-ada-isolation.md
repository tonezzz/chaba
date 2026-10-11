# Ada → HA isolation standard

An Ada backend failure (quota storm, tool loop, token leak, bad deploy, host
exhaustion) must not damage or take down an HA instance. Written after the
2026-10-11 ada-ha-tony Gemini Live reconnect storm; tony-ha is prod, kk-ha is
KK's member node — both must survive any Ada meltdown. Live posture report:
CMS index `ha-ada-isolation` (generator `scripts/ada/ha-ada-isolation-cms.py`).

## Coupling map (verified 2026-10-11)

| Ada backend | host:port | upstream HA | HA credential | surface into HA |
|---|---|---|---|---|
| ada-ha-tony | idc03:8002 | tony-ha via tailnet :8123 | **Tony OWNER LLAT** | REST only: `/api/states`, `/api/services/*` for light/switch/fan/input_boolean/cover/button/media_player tools + `office_lights` ~5s poller |
| ada-ha-michael | idc03:8003 | michael-ha via tailnet | **Michael OWNER LLAT** | same tool set |
| ada-kk | idc03:8007 | **none — no `HOME_ASSISTANT_*` in env** | — | voice card dials browser→`/ada-ws/kk`; kk-ha unreachable from the backend |
| ada-dev | idc03:8005 | none (upstream removed) | — | HA tools excluded |
| ada-pi-pwa | idc03:8001 | tony-ha via tailnet | **Tony OWNER LLAT** | CMS/enroll frontend **+ full HA tool set** (only 2 exclusions) |

Shared-fate vectors (one failure hits every lane):

- **One `GEMINI_API_KEY` across all five `ada-*.env` files** (hash-identical).
  A quota storm in any instance starves them all — the observed storm burned
  Tony's key, which is also KK's, Michael's, dev's, and pwa's.
- **One `ada-pi` checkout + one `.venv` on idc03** serves every backend.
  `deploy-ada.sh` restarts the whole set — a bad commit can kill every Ada
  at once. `ada-kk` is NOT in the default `SERVICES` restart set, so it
  drifts on old code until manually restarted (accidental, undocumented
  isolation).
- **All backends + mddb + kk-ha + michael-dev co-locate on idc03.** No
  `MemoryMax`/`CPUQuota` on any ada unit — a runaway process can starve the
  HA containers. Default `StartLimitBurst=5/10s` bounds crash-loops only.
- **HA→Ada direction is clean** (verified in tony-ha config: no
  rest_command/shell_command to Ada). Voice cards and chaba-nest CMS
  iframes fail soft — blank card, not a control-plane failure.

## Isolation standard — per Ada↔HA pair

- [ ] **Dedicated non-admin HA user** (`svc-ada`, `svc-kaewta`, …) with its
  own long-lived token. Never a person's account, never owner/admin.
  Buys: admin APIs unreachable, per-action attribution in logbook
  ("by svc-ada"), instant kill via token revoke without touching Tony's
  sessions. HA has no per-entity ACL — service calls stay possible, which
  is what Ada needs anyway.
- [ ] **Per-instance `GEMINI_API_KEY`** (or GCP project per persona). No
  shared quota pool across personas. `GEMINI_API_KEY_` fallback var already
  exists for rotation.
- [ ] **Cgroup caps on every ada unit** (`MemoryMax`, `CPUQuota` drop-ins)
  so a runaway backend can't starve co-located HA containers on idc03.
- [ ] **Deploy membership explicit** — each instance is either in
  `deploy-ada.sh` `SERVICES` or documented as pinned. Deploy order is a
  canary ladder: ada-dev → member lanes → ada-ha-tony last.
- [ ] **Actuation allowlist per instance** — `ADA_EXCLUDED_TOOLS` +
  `upstream_ha: none` wherever the backend doesn't need control (ada-kk,
  ada-dev already do this; keep it that way).
- [ ] **Journal caps** on ada units (`LogRateLimitIntervalSec`/`Burst`) so
  a log storm can't fill the idc03 disk.

## What-if table

| scenario | blast today | after standard |
|---|---|---|
| Gemini quota/reconnect storm | all 5 instances starve on the shared key | only the offending instance; `ada-gemini-quota-breaker` stops the storm itself |
| tool-call / actuation loop | can toggle real devices on prod tony-ha with **owner** perms | non-admin svc token; allowlisted domains; logbook attributes every call |
| ada HA token leak / rotation | owner token = full prod admin; revoking breaks anything else sharing it | svc token only; revoke kills Ada, nothing else |
| bad ada-pi deploy | all backends restart onto broken code together; ada-kk silently stays old | canary order catches it on ada-dev first; membership explicit |
| ada mem/cpu leak on idc03 | starves kk-ha + michael-dev + mddb | cgroup caps contain it |
| ada log storm | can fill idc03 disk → everything on host | per-unit journal caps |
| idc03 host dies | kk-ha dies anyway (co-located) — accepted risk | same; tony-ha unaffected (on tony-dell) |
| tony-dell / tailnet down | ada-ha-tony orphaned; bounded retries (httpx 5s timeout; poller min 5s) | same — harmless error churn, no damage |
| ada stopped / killed | voice card + CMS iframes blank; HA control plane untouched | same — verify below |

## Execution order

Phase 0 — stop the bleeding (done 2026-10-11): `ada-ha-tony` stays stopped
until the quota breaker (`ada-gemini-quota-breaker`) and text-lane fix land.

Phase A — no-prod-touch quick wins (safe to run any time):
1. Split Gemini keys — at minimum tony vs kk/michael/dev pools; update env
   files on idc03, restart the units. (needs GCP console — see card request)
2. cgroup drop-ins on all `ada-*.service` units: `MemoryMax=2G`,
   `CPUQuota=150%` (tune to observed baseline).
3. Decide ada-kk deploy membership → add to `SERVICES` or record "pinned"
   in `ssot.services.yml`.
4. `LogRateLimitIntervalSec=30s LogRateLimitBurst=1000` drop-ins.

Phase B — prod-gated (explicit approval — touches tony-ha):
1. tony-ha UI → Settings → People → add user `svc-ada`, non-admin.
2. Mint a long-lived token for `svc-ada`; put it in
   `~/.config/secrets/ada-ha-tony.env` (`HOME_ASSISTANT_TOKEN`).
3. Start `ada-ha-tony`; verify `auth/current_user` = svc-ada / is_admin
   false; verify one harmless service call (e.g. toggle an input_boolean).
4. Revoke the old Tony LLAT from tony-ha (check nothing else uses it first).
5. Same pattern on michael-ha; kk-ha gets `svc-kaewta` if/when ada-kk ever
   receives HA credentials.

Phase C — verify isolation (run after each phase, and after any incident):
```bash
# HA survives ada death
ssh idc03 'systemctl --user stop ada-ha-tony'
curl -sf https://tony-dell.taila0626a.ts.net:8123/api/ && echo "tony-ha ok"
# revoke path works — expect 401 and bounded ada-side error logging
# caps hold — watch `systemd-cgtop` while ada runs
```

## Kill switch (fastest first)

1. `ssh idc03 'systemctl --user stop ada-ha-<lane>'` — seconds, reversible.
2. tony-ha UI → the svc user's token list → delete the LLAT — hard sever,
   survives ada restarts.
3. Blank `HOME_ASSISTANT_URL`/`HOME_ASSISTANT_TOKEN` in the lane env file +
   restart — config sever, keeps the assistant alive with HA tools dead.
4. `systemctl --user disable --now` — survives reboots.
