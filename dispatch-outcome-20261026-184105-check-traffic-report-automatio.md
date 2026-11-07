# Dispatch outcome — check-traffic-report-automatio (2026-10-26 18:41)

Card: `check-traffic-report-automation-a9645b` (KNB-0429) — "Tony forwarded
traffic alert in conversation. Is the traffic report generation working?"

## Verdict

**Yes — traffic report generation is working.** The camwall traffic pipeline
is live and fresh; what is degraded is the majority of upstream camera feeds
(DOH-side outage), which the report correctly surfaces as down/stale cams
rather than failing to generate.

## What was verified (by surface, not by service)

Producer proof:
- `cam-wall-pull-vps.timer` ticking every 30s on **idc02** (last 18:43:30)
  and **idc03** (last 18:43:36); services exit `Result=success`.
- `cam-wall-cms-vps.timer` on **idc03** every 15 min (last 18:32:00,
  success) — renders `camwall-<zone>` pages into MDDB `ada-cms-pages`.
- `camwall-edge.service` on idc02 active 3w3d (caddy on tailnet :8380).

Consumer proof:
- MDDB `ada-cms-pages|camwall-traffic|en` (`http://100.102.134.91:11027`)
  meta.updated = `2026-10-26T11:32:01Z` (18:32 +07) — refreshed on the
  15-min tick.
- `https://tony-dell.taila0626a.ts.net/apps/camwall/?zone=traffic` → 200;
  `/data/traffic/montage.jpg` → 200 (232KB, written 18:37).
- Page honestly reads "4/11 cams live · 2 stale · 5 dead" with per-cam
  status cards — the guaranteed-image contract is doing its job.

Upstream state (root cause of the degraded report):
- ~8/43 traffic-zone cams live: traffic 3–4/11, rama9 2/6, burapha 2/11,
  chonburi 0/9, dohweb 0/6.
- Direct probe: `http://180.180.242.207:1935/<Phase>/<PER_*>` → **404 in
  7ms** for every stream (server up, streams gone); `…242.208` times out.
  iTIC `pass/` proxy mirrors the 404; iTIC `jpeg2.php` returns 403 for
  rama9 stills. This is an upstream DOH/iTIC outage — same failure class
  noted in the traffic-cam README, but broader today.

Other findings:
- `traffic-snap.service` (:8378) is installed on mn01/idc03/tony-dell but
  **inactive** — standby by design (Ada uses in-process
  `backend/traffic_camera.py`; shim integration is a pending follow-up).
- Ada voice path is fine: today's audit job
  (`2026-10-26-no-result-ada-camera-snapshot.yml`) already reclassified
  `no_result:ada_camera_snapshot` as a session-teardown signature, not a
  tool bug.
- **Gap:** kk lane `ada-cms-pages-kk|camwall-traffic` is stale since
  2026-10-20 — `cam-wall-cms-kk` was retired on tony-dell but never
  re-armed on idc02/idc03 (ssot.jobs.yml note claims it moved there; no
  unit exists). `ssot.apps.camwall.yml` still documents the dell twin —
  stale doc. Needs a re-arm-or-retire decision.
- Still true from prior checks: no standalone traffic-alert → digest
  automation exists; Tony parked that as a backlog feature on 10-11.

## Artifacts

- Trail: `docs/ssot/jobs/infrastructure/2026-10-26-traffic-report-check.yml`
- Card comment posted via board-api summarizing the verdict + kk gap.

## How to verify

```
curl -s -X POST http://100.102.134.91:11027/v1/get -H 'Content-Type: application/json' \
  -d '{"collection":"ada-cms-pages","key":"camwall-traffic","lang":"en"}' | grep -o '"updated":[^]]*'
ssh idc03 'systemctl --user list-timers cam-wall-pull-vps.timer cam-wall-cms-vps.timer'
curl -I https://tony-dell.taila0626a.ts.net/apps/camwall/data/traffic/montage.jpg
```
