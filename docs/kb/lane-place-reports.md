# Lane place reports — how place info becomes durable knowledge

Standard for turning "is this shop open / find me a place" questions into
CMS dossiers a member lane can answer from. Applies to `ada-cms-pages-*`
collections (kk-ha first); the same shape generalises to any
named-entity dossier (cam-*, flood-*, place-*).

## The loop

```
member asks about a place (name, "is X open", a maps.app.goo.gl link)
  │
  ├─ 1. cms_read first — key `place-<slug>` may already exist
  │       → fresh (checked_at < fresh_for): answer from the dossier,
  │         state the check age ("ล่าสุดเมื่อ 12 ต.ค.")
  │       → stale or missing: go live
  │
  ├─ 2. web_search resolves
  │       shortlinks auto-expand to 'name (lat,lng)' (195eb85);
  │       Places tool (kk-places) upgrades this to structured fields
  │
  ├─ 3. save-back — write/refresh `place-<slug>` THIS turn
  │       (the web_search result note already mandates save-back;
  │       this doc defines the doc shape)
  │
  └─ 4. answer with a timestamp — never bare "it's open"; always
        "เปิดอยู่ค่ะ — เช็กล่าสุด <when>" so staleness is visible
```

## Doc contract — key `place-<slug>`

Slug: lowercase place name, ASCII, hyphens (`place-rak-chang-cafe`).
One key per place — search the collection before creating; a second
page for the same place is a duplicate, update in place instead.

Meta:

| field | value |
|---|---|
| `domain` | `places` |
| `status` | `active` / `superseded` |
| `title` | place name (+ Thai name when known) |
| `place_id` | Google Place ID when resolved |
| `address` | text address |
| `phone` | `+66…` — only when a source returned it; never guess |
| `coords` | `lat,lng` |
| `maps_url` | canonical maps.google.com URL |
| `source` | `google-places` / `web-search` / `manual` |
| `checked_at` | ISO timestamp of last verification |
| `fresh_for` | `7d` hours/status · `90d` static facts |

Body follows `cms-page-standard.md`: **Status** verdict line →
`## Latest` dated check-ins → `## Contact` / `## Hours` / `## Notes` →
`## History` → provenance footer (`*Checked by <lane> via <source> ·
<ts>Z*`).

## Rules

1. **Specific or honest** — if the source gives no phone/hours, the
   dossier says "no number on file" and she says so; generic search
   snippets are never dressed up as listings (the Nhong aircon miss).
2. **checked_at is part of the answer** — she voices the check age when
   the fact is time-sensitive (open now, hours today).
3. **Private by default** — place pages carry no personal data so they
   *can* go public, but `public: true` stays opt-in; the publish gate
   decides, not the writer.
4. **Re-check cadence** — a `fresh_for`-expired dossier triggers a live
   re-verify on next ask, not a scheduled crawl; places change slowly,
   demand-driven refresh is enough at member-lane volume.
5. **Dedup at lookup** — `cms_read place <name>` before publish; merge
   into the existing page when found (keeps History in one place).
6. **Unresolved = no page** — a bare-name ask that resolves to no
   coords and no maps link publishes nothing; the lane answers with a
   Google Maps search link (`place_report` returns `unresolved` +
   `maps_url`) or asks for the place's link. A title-only page is worse
   than none (the Cape Sports Center Langebaan miss, 2026-10-13).

## Coverage

Declared under the lane content map (KNB-0497 /
`lane-cms-content-model`): `domain: places` → producer `web_search` +
`kk-places` tool → cadence on-demand → truthfulness contract above.
Audit hook: expected `place-*` docs resolve a `checked_at` within
`fresh_for`; stale entries show as stale, not wrong.
