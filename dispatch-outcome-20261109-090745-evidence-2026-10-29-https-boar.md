# dispatch-outcome — boards-public-origin-502 (2026-11-09, idc02)

## What was found

The 2026-10-29 boards 502 incident **self-recovered**; the site is fully
green now and no duplicate board service was started (board-api on idc03
never entered the public chain — `:10000/health` = `{ok:true}`).

Chain: browser → Cloudflare → **idc02 caddy-edge** (45.136.236.190, tls
internal) → Plesk `boards.h3.gizmo-thailand.com` (ReadyIDC 103.99.11.249,
Host-rewritten; WP siteurl = public name).

**Root cause — two layers, both proven from idc02 journals:**

1. **Origin host distress (primary).** 2026-10-29 ~17:02 → 10-30 ~07:47
   +07 (brief relapse 15:31-15:36). Direct probes on 10-29 got an nginx
   502 page = Plesk nginx alive, application upstream (Apache/PHP-FPM)
   dead. Edge journal corroborates: explicit 502s at 18:26/20:37, 60s+
   read timeouts, h2 GOAWAY, connection resets, and TCP connect i/o
   timeouts to :443 concentrated 19:30-21:28 — host-level distress, not a
   WP app bug. Which upstream died / why (OOM, spike, provider
   maintenance) is **unknowable without h3 access** — no ssh/Plesk-panel
   path exists on ops hosts (follow-up carded).
2. **idc02 edge DNS flakiness (secondary, self-inflicted).** 126+ journal
   events `lookup boards.h3.gizmo-thailand.com: i/o timeout` via
   127.0.0.53 (systemd-resolved), burst 20:35-21:28 + sporadic hits
   10-28 → 11-07 — each blip is a public 502 even with origin healthy.
   Chronic low-grade issue (zone NS = lin3/lin4.readyidc.com).

"Cloudflare 502" in the evidence = the idc02 edge's own 502 (upstream
dial/DNS failure) proxied through Cloudflare — CF's origin is the edge,
not h3.

## Consumer proof (verified 2026-11-09 ~09:10 +07)

- Public: `/` 200, `/wp/` 200, `/wp/wp-json/` 200 (edge rewrite →
  `index.php/wp-json/`). `heartbeat-idc03` ops-event modified
  2026-11-09T02:09Z — idc03 WP writer live end-to-end.
- Origin: `/wp/` → 301 → public (expected WP siteurl redirect);
  `/wp/wp-json/` → 404 = **documented vhost limitation** (no try_files —
  `ssot.wp-boards.yml` `rest_route_style`); REST verified via
  `/wp/index.php?rest_route=/` → 200 and `/wp/index.php/wp-json/` → 200.
- wp-watch (5-min consumer probe on idc02): all clear every run today;
  origin TCP ~30-60ms, TTFB 0.35-1.1s.

## Artifacts / follow-ups

- RCA trail: `docs/ssot/jobs/infrastructure/2026-11-09-boards-origin-502-rca.yml`
- Board comment posted with the diagnosis; follow-up card
  `boards-502-residuals-dns-h3-access` (KNB-1245) filed for the DNS
  flakiness + missing h3 forensic access.
- Committed on `dispatch/20261109-090745-evidence-2026-10-29-https-boar`;
  not pushed (dispatch rule).

## How to verify

- `curl -sI https://boards.surf-thailand.com/wp/` → 200;
  `.../wp/wp-json/` → 200
- `curl -sk 'https://boards.h3.gizmo-thailand.com/wp/index.php?rest_route=/'` → 200 JSON
- `journalctl --user -u caddy-edge.service --since 2026-10-29 | grep '103.99.11.249\|boards.h3'` → the incident evidence
- `journalctl --user -u wp-watch.service -n 10` → all clear
