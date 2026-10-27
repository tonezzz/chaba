# dispatch-outcome — line-wp-site-manager (2026-10-27)

## What changed / found

**P0 — WP live + REST reachable: VERIFIED.** `boards.surf-thailand.com/wp/`
= 200, `/wp/wp-json/` = 200 (site "Chaba web boards", 219 routes,
chaba/v1 + cptui + wp/v2 + wp-abilities namespaces). The 2026-10-14/15
watcher alerts (301 loop, timeouts) are resolved — the idc02 edge
rewrite is working. Side finding: `/wp/v2/users` is anonymously
enumerable (admin id=1 slug exposed) — WP-default posture, flagged as
an optional follow-up, not urgent.

**P1 — app password: already done 2026-10-14** (Option A identity-based —
backend holds `~/.config/secrets/wp-boards.env` with
WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD; members never see creds; the
5-min idc03 heartbeat writer exercises it continuously). No master
creds anywhere near LINE.

**P2 — new `wp_read` tools.d drop** (staged, not deployed):
`integrations/ada-voice/backend/tools.d/wp_read.py` — action=list
posts/pages/CPT rows with status/person-tag/search/limit filters;
action=get by id or slug returns title + body TEXT as the draft
preview (members have no wp-admin login, so draft permalinks can't be
their preview surface). Read-only tag lookup via GET tags — never
ensure_tag. Manifest `policy: read`, `secondary_allowed: true`, 30s.

**P3 — new `wp_update` tools.d drop** (staged, not deployed):
`tools.d/wp_update.py` — id + title/content/status on posts+pages only
(CPT records keep their writer tools' slug/meta contract). GET-then-
POST reports the transition ("draft -> publish") and honest 404s.
Manifest `policy: confirmed` — the dispatch layer enforces
confirmed=true / bound confirm_token before run() is reached; the
DECLARATION lists `confirmed` as a property (never required — the gate
pops it pre-validation). Publish flow composes: wp_post publish=false
→ wp_read get → member yes → wp_update status=publish.

**Support files:** manifest.wp_read.yml + manifest.wp_update.yml
(tools.d/), tool_guide.wp_read.yml + tool_guide.wp_update.yml
(backend/), tests/ada/test_wp_read_update_drop.py (18 tests, all
green), persons include lists (tony + kk), ssot.wp-boards.yml writers
entries, design doc docs/ssot/jobs/ada/2026-10-27-wp-read-update-tools.yml.

## Open question raised

Board request on the card: which lane fronts a real customer site and
whether the customer gets a dedicated LINE group (proposal: dedicated
group per customer-site, per-site wp-<customer>.env app password —
Option A identity map).

## Result

Commit `d0c6034c3` on `dispatch/20261027-140223-p0-wp-live-on-plesk-boards-sit`
— 10 files, +1094. NOT pushed (dispatch rule). The drops land on
ada-voice via the normal drop-apply + deploy-ada.sh path on idc03.

## How to verify

- `python -m pytest tests/ada/test_wp_read_update_drop.py` → 18/18
  (uvx --with pytest --with pyyaml --with httpx)
- `curl -sI https://boards.surf-thailand.com/wp/` → 200;
  `.../wp/wp-json/` → 200
- After ada-voice merge + deploy-ada.sh on idc03: kk lane "what is on
  my site" → wp_read list; "publish the draft" → wp_update denied
  until confirmed=true.
