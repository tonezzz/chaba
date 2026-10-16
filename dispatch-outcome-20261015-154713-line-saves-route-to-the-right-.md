# Dispatch outcome — line-cpt-writer-router (2026-10-15)

## What changed

Staged **ada-voice drop 11** in `integrations/ada-voice/` — a new
drop-in tool `cpt_post` that routes LINE "save this" asks to the right
chaba-boards CPT instead of stacking free-form `wp_post` posts:

- `integrations/ada-voice/backend/tools.d/cpt_post.py` — `kind=`
  expense|contact|reminder|asset; the model reads a receipt photo
  in-turn (LINE images arrive as real image turns) and passes
  amount/vendor/date — no OCR inside the tool. Server-side title per
  the wp-boards title_standard, meta filtered to the kind's registered
  keys, archived photo -> featured_media, records land `status=private`.
  `person` resolves explicit -> lane instance (kk lane -> kk — "KK is
  boss of kk-hom") -> caller identity. contact/asset upsert by
  deterministic slug (md5 fallback for Thai-only names); expense/
  reminder always create. Meta 400s degrade (saved_by first, then all
  meta) so the record survives plugin version skew.
- `integrations/ada-voice/backend/tools.d/manifest.cpt_post.yml` +
  `tool_guide.cpt_post.yml` — manifest/guide fragments (read policy,
  secondary_allowed, 60s).
- `integrations/ada-voice/backend/wp_client.cpt-post.patch` —
  `create_post` gains `slug=` and sends `tags` only when non-empty
  (CPTs have no post_tag taxonomy).
- `integrations/ada-voice/backend/tools.d/wp_post.cpt-router.patch` +
  `backend/tool_guide.cpt-router.patch` — wp_post's description/guide
  reroute structured saves to cpt_post (the classification cue).
- `integrations/ada-voice/ssot.tool-surface.cpt-post.patch` —
  `coverage_debt += cpt_post` (a live scenario would write real WP
  records every suite run).
- `integrations/ada-voice/tests/test_cpt_post.py` — 20 unit tests.
- `integrations/wp-boards/chaba-boards.php` — v0.5.1: `saved_by` meta
  on asset/expense/contact/reminder + 'By' admin column.
- `docs/ssot/apps/ssot.wp-boards.yml` — meta lists, `writers.cpt_post`,
  v0.5.1 note. `docs/ssot/apps/ssot.apps.ada-persons.yml` — cpt_post in
  persons.tony + persons.kk include lists.
- `tests/ada/test_cpt_post_drop.py` — chaba-side drop verifier (11
  tests incl. git-apply gate on the ada-voice checkout).
- `integrations/ada-voice/README.md` — Drop 11 install steps/contract.
- `docs/ssot/jobs/ada/2026-10-15-line-cpt-writer-router.yml` — job file.
- Drive-by fix: pre-existing YAML syntax error in
  `docs/ssot/jobs/ada/2026-10-15-wp-comment-sync.yml` (was the
  validator's only error).

## Result

Done, pending deploy — nothing pushed/deployed per dispatch rails.
Tests: 20/20 ada-voice-side (real wp_client, mocked REST), 11/11
chaba-side, all 4 patches `git apply --check` clean vs ada-voice
checkout (files identical to origin/main @ 18c0a01),
ssot-validate-all: 2423 files, 0 errors. Board comment posted.

## How to verify / next steps (need Tony/deploy)

1. Install drop 11 on an ada-voice checkout (README Drop 11 steps),
   `scripts/tool-lint.py` + `pytest tests/ -x -q`, then deploy-ada.sh
   on idc03.
2. Redeploy chaba-boards plugin zip v0.5.1 via wp-admin upload
   (deploy order is flexible — the meta degrade covers <0.5.1).
3. Re-run `scripts/ada/render-tool-profiles.py` for ada-ha-tony.env +
   ada-kk.env on idc03.
4. Live smoke on the kk lane: "save this contact: Honda service
   02-123-4567" -> private contact record; a receipt photo -> expense
   with amount/vendor/receipt_date meta.

Deferred: reminder->calendar fan-out (record-only for now), bench/
report/xlate LINE saves (dedicated producers own those), kk-parity
bench profile drift (missing wp_post predates this drop).
