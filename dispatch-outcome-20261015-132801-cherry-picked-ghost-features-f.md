# Dispatch outcome — cmssurface-render-digest

**Card:** cmssurface-render-digest · **Runner:** idc02 · **Branch:** dispatch/20261015-132801-cherry-picked-ghost-features-f
**Result:** both components built, tested against live MDDB, staged for deploy. No commits, no pushes, no deploys per worktree mode.

## What was built

**Component 1 — chaba-cms-render** (`apps/cms-render/`)

Single-file FastAPI app (`server.py`, ~630 lines) + Jinja2 `templates/` per kind
(base, page, report, digest, trip, place-report, timeline, media-inbox,
house-rules, automation, doc, index, listing, feed.xml).

- Reads LIVE from `ada-cms-pages`, `ada-cms-pages-kk`, `chaba-docs`,
  `ada-cms-automation` on mddb-cms :11027 — fetch-on-request, no rebuild.
- Page HTML cached keyed by `(collection, key, lang, updatedAt)`; collection
  listings cached `CMS_LIST_TTL_S=120` for slug→key resolution, lang variants,
  index sections.
- Routes: `/` index grouped by nav section (meta kind/role/domain derivation —
  note: on real data meta.kind is only page|report|archive, so the useful
  "kind-grouped" index is the ssot.cms.yml nav derivation; flagged in the jobs
  file), `/p/{slug-or-id}` (kind-dispatched template, `?c=` collection hint,
  `?lang=` pick + toggle when variants exist), `/k/{kind}`, `/feed/{kind}.xml`
  RSS, `/healthz`.
- kk collection → Thai UI strings; main → EN. Mermaid + ` ```media ` fences,
  `#/slug` → `/p/slug` rewriting, superseded/moved_to banner, relay-img/www
  media pass through linked (never copied). Automation docs render JSON config.

**Component 2 — line-digest** (`scripts/ada/line-digest.py`, stdlib only)

Weekly per-member LINE push via relay `/send {to, instance, text, message_id}`.
Sources: house-timeline leaves, media-inbox additions (addedAt in window,
extracts+rollup excluded), refreshed `*-digest` rollups, kanban done-count
(cards whose close comm landed in window — plain `updated` counts every touch,
not completions), WP render_job posts (skipped without wp-boards.env).
Idempotent `line-digest-<member>-<ISOweek>` persisted in
`~/.local/share/ada/line-digest.json`. `--dry-run`, `--members`, `--force`.

**Deploy artifacts (staged, not applied)**

- `systemd/chaba-cms-render.service` — idc03, tailnet `100.102.134.91:8010`,
  venv `~/.venvs/cms-render` (requirements.txt provided).
- `systemd/ada-line-digest.{service,timer}` — Mon 09:00, `LINE_DIGEST_MEMBERS=tony`
  until rollout approved.
- `stacks/idc02/cms.surf-thailand.com.caddy` — `tls internal` → `http://100.102.134.91:8010`,
  ready to append to the idc02 edge Caddyfile.
- `ssot.routes.yml` cms-render service entry; `ssot.audit.hosts.yml` idc03
  census entries (service + timer).
- `docs/ssot/jobs/cms/2026-10-15-cms-render-line-digest.yml` — full trail.

## Verification (done in session)

- `pytest tests/ada/test_cms_render.py tests/ada/test_line_digest.py` — **31 passed**
  (cms-render suite skips cleanly where app deps aren't installed).
- Live smoke vs real MDDB: `/healthz` ok (610+159+40+67 docs); eyeballed
  index, `/p/media-inbox` (thumb grid + `#/` link rewrite), `/p/house-timeline`,
  `/p/ada-digest`, `/p/trip-southafrica` (kk Thai, mermaid gantt, superseded→boards banner),
  `/p/place-*` (th), `/p/api/health-endpoints.md` (chaba-docs path key),
  `/p/ada-debug-report?c=ada-cms-automation` (JSON view), `/k/trip`,
  `/k/media-inbox`, `/feed/digest.xml` + `/feed/report.xml` (well-formed XML),
  404 on unknown slug.
- `line-digest.py --dry-run` renders Tony's digest (~300 chars): 25 devices,
  15 media items, ada-digest +32, 344 cards done this week (real — merge-sweep
  closes 30-95/day).
- Pre-existing failures on this host (NOT this change): tests/ada ada-voice
  patch-drift tests (test_draft_hit_frame, test_line_image_delivery,
  test_line_reply_routing) — same failures blocked another dispatch earlier today.

## Remaining before production (needs operator)

1. On idc03: `python3 -m venv ~/.venvs/cms-render && pip install -r
   ~/CascadeProjects/chaba/apps/cms-render/requirements.txt`, install the unit,
   `systemctl --user enable --now chaba-cms-render`.
2. Append the caddy block to idc02 `~/.config/caddy/Caddyfile`, `caddy reload`
   (or restart caddy-edge container).
3. CF DNS + Access policy for `cms.surf-thailand.com` (dashboard step).
4. Digest: real send to Tony once (members=tony, not dry-run), eyeball, then
   widen `LINE_DIGEST_MEMBERS` and enable `ada-line-digest.timer`.
