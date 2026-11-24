# Dispatch outcome — rename Educations CPT label to Lessons

Card: `rename-educations-cpt-label-to-lessons-w-0014fb` (OPS-0820)
Date: 2026-11-24 · Host: tony-omen · Branch: dispatch/20261124-160508-prereq-locate-the-wp-origin-ho

## Prereq answers (what the card asked to locate)

- **WP origin host**: `boards.h3.gizmo-thailand.com` → 103.99.11.249, the
  Plesk-managed web node (`node-1.h3.surf-thailand.com`). Public edge is
  `boards.surf-thailand.com` via Cloudflare + idc02 caddy-edge. No WP
  files on any chaba fleet host — the site lives on the Plesk vhost.
- **`register_post_type` call**: not a standalone theme/plugin file on the
  server — it's the generic CPT loop in the `chaba-boards` plugin, source
  of truth in this repo at `integrations/wp-boards/chaba-boards.php`
  (`init` hook, `foreach ($types as $slug => [$sing,$plural,$icon])` →
  `register_post_type($slug, ...)`, ~line 157). Deployed artifact is a
  zip uploaded through wp-admin (`scripts/wp-boards/deploy-plugin-zip.sh`).
- **show_ui / show_in_menu**: `$common` args set `public=true` (⇒
  `show_ui` defaults true) and `show_in_menu=true` explicitly; `show_in_rest`
  + `rest_base='lesson'` keep REST + board-api working. Confirmed live —
  the "Lessons" top-level admin menu renders and lists posts.

## What changed

`integrations/wp-boards/chaba-boards.php` (v0.9.0 → **0.10.0**):

- lesson tuple `['Education','Educations',icon]` → `['Lesson','Lessons',icon]`
  (drives `label`/REST `name`).
- Added an explicit `labels` array for the lesson CPT only:
  `name=Lessons`, `singular_name=Lesson`, `menu_name=Lessons`, plus the
  full WP label set (add_new_item "Add New Lesson", edit_item, search_items,
  not_found, item_* messages, etc.) so every admin string reads Lesson(s).
- Slug `lesson`, `rest_base`, `has_archive`, hierarchical=false, all meta
  keys, admin columns, sortable Updated column, lessons-due dashboard
  widget — all untouched.

Built `integrations/wp-boards/dist/chaba-boards-0.10.0.zip`
(`chaba-boards/{chaba-boards.php,usage-pull-cron.php}`) and deployed via
`scripts/wp-boards/deploy-plugin-zip.sh` → "OK: overwrite applied"
(script exits 1 on a benign trailing grep — overwrite itself succeeded).

`docs/ssot/apps/ssot.wp-boards.yml`: added the v0.10.0 deploy note.

## Verification (live, post-deploy)

- `GET /wp/v2/types/lesson` (origin): `name: "Lessons"`, `slug: "lesson"`,
  `rest_base: "lesson"`, `has_archive: true`. `/wp/v2/types` still 31 types.
- wp-admin login (admin credential on omen) →
  `edit.php?post_type=lesson`: sidebar menu item reads **"Lessons"**
  (`menu-icon-lesson`), zero occurrences of "Educations" on the page.
- Post count: **137 items, all status=private** (0 in publish/draft/trash/
  archived). The card expected "61" — that figure was from 2026-10-24;
  lessons kept accruing until the 2026-11-07 wiki cutover froze the WP
  corpus, so 137 is the correct current count. List is reachable and
  populated; per-page shows 20 rows.

## Notes / non-changes

- Post **titles** still read `Education — {topic}` — that's the content
  convention, and board-api parses it back with `.replace("Education — ","")`
  (board-api.py ~L3752/4108/4320/4397). Renaming titles is out of scope and
  would break parsing of the frozen archive. SSOT `title_standard.lesson`
  left as-is for the same reason.
- WP lesson CPT is a frozen archive since the 2026-11-07 wiki-education
  cutover (board-api `/lesson` now reads wiki, 221 lessons); the label
  rename is cosmetic on the archive surface only.

## How to verify

```
curl -s 'https://boards.h3.gizmo-thailand.com/wp/index.php?rest_route=/wp/v2/types/lesson' | jq .name   # -> "Lessons"
# wp-admin -> Lessons menu -> lists 137 private lesson posts
```

lessons:
- deploy-plugin-zip.sh exits 1 after a successful overwrite — trailing `grep` under `set -euo pipefail` finds no activate link; check output for "OK: overwrite applied", not the exit code.
- wp-admin list counts include every status; lesson CPT posts are all `private` — check `post_status=` filters before trusting a total.
- Card-specified counts ("61 posts") go stale between carding and dispatch; verify the live number and report the delta.
- boards WP REST quirk still holds: use `index.php?rest_route=` on the origin host `boards.h3.gizmo-thailand.com`; `/wp-json/` 404s on the Plesk vhost.
