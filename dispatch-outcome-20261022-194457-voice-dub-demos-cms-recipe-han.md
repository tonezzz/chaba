# Dispatch outcome — voice-dub-recipe-lan-url (MED-0313)

**Card:** `docs/ssot/kanban/cards/voice-dub-recipe-lan-url.yml`
**Date:** 2026-10-22 · runner tony-omen

## What changed

Updated the `voice-dub-demos` CMS page live in MDDB (mddb-cms, idc03
`http://100.102.134.91:11027/v1`) — in **both** collections that carry it:

- `ada-cms-pages` (tony lane)
- `ada-cms-pages-mn` (mn lane replica — no sync automation exists, edited by hand)

Three edits to `contentMd`, upserted via `POST /v1/add` with merged meta:

1. **Lede** — the two base URLs are now labelled by target:
   `http://192.168.2.67/apps/yt-live/` = LAN, TV/Chromecast path only;
   `https://tony-dell.taila0626a.ts.net/apps/yt-live/` = tailnet, numbered
   vcast screens and anything off-LAN.
2. **Numbered vcast screens paragraph** — `cast_to_screen` now instructed with
   the **tailnet** URL and an explicit "never `192.168.2.67`" rule: every
   vcast display is a tailnet device, and the URL pre-check runs on the Ada
   backend host (idc03, off-LAN), so the LAN URL is refused with
   `TimeoutError` before the display is asked (origin failure: session
   6744c10aab, 2026-10-09 02:24).
3. **Failure modes** — added a "LAN URL refused on numbered screens" bullet
   so Ada can diagnose the symptom.

Unchanged on purpose: the TV recipe (`yt action="cast"`) keeps the LAN URL —
the TrueID/Chromecast box is a LAN-only device that can't resolve tailnet
names. Verbatim-filename alias map and screen-number routing notes preserved.
Meta refreshed: `updated=2026-10-22T12:47Z`, `last_verified=2026-10-22`,
`written_by=devin` kept.

## Repo artifacts

- `docs/ssot/jobs/vcast/2026-10-22-voice-dub-recipe-lan-url.yml` — job record.

## How to verify

```
curl -s http://100.102.134.91:11027/v1/get -H 'Content-Type: application/json' \
  -d '{"collection":"ada-cms-pages","key":"voice-dub-demos","lang":"en"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['contentMd'])"
```

Expect: `cast_to_screen(..., url="https://tony-dell.taila0626a.ts.net/apps/yt-live/<file>.mp4", ...)`
in the numbered-screens paragraph; `yt(action="cast", query="http://192.168.2.67/...")`
still in step 2 for the TV. Same check with `collection: ada-cms-pages-mn`.

## Result / residual

Done — recipe fixed in both replicas. Residual gap stays on
`cast-precheck-vantage` (ada-voice): the pre-check itself is still
vantage-blind; this fix only changes what the recipe hands out.
