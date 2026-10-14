# Dispatch outcome — chaba-boards-plugin-deploy (KNB-0657 follow-up)

## Result: VERIFIED LIVE — most of the card was already done before this session

The audit finding was stale by dispatch time. Actual state found and confirmed:

- **(a) Repo landing — already done.** `integrations/wp-boards/chaba-boards.php`
  (v0.3.3) is committed and md5-identical to `/tmp/chaba-boards.php`.
- **(b) Install+activate — already done.** `GET /wp/v2/plugins?context=edit`
  reports `chaba-boards/chaba-boards | 0.3.3 | active` on boards WP
  (deployed earlier via wp-admin plugin-editor ajax). `/tmp/deployed-plugin.php`
  is a stale v0.3.0 snapshot, not what's live.
- **(c) Type registration — verified.** `/wp/v2/types` lists all 10 plugin CPTs:
  asset, expense, contact, reminder, bench, report, xlate, cam, render_job,
  news (news is hierarchical — a v0.3.3 trait, confirming live = repo version).
- **Sample posts — seeded this session.** The six core CPTs were empty;
  created one PRIVATE sample each via REST app password, meta round-trip OK:
  asset=266 expense=267 contact=268 reminder=269 bench=270 report=271.
  Pre-existing content: news=133, render_job=1 (id 117). xlate/cam remain
  unseeded (xlate rows auto-write via the translate hook; cam awaits a writer).
- **(d) SSOT marker — already LIVE; touched up.** Comment bumped 0.3.2→0.3.3
  and now records the 2026-10-14 verification + sample ids.
- **chaba-translate.php — resolved without action.** No such file exists in
  /tmp anymore; its TH↔EN Gemini translation hooks are merged into
  chaba-boards.php itself (xlate CPT + `save_post_post` hook, ~lines 145-234).

## Changed in this worktree (committed on dispatch branch, not pushed)

- `docs/ssot/apps/ssot.wp-boards.yml` — version comment + verification note.
- `docs/ssot/jobs/infrastructure/2026-10-14-chaba-boards-plugin-deploy-verify.yml`
  — new trail doc incl. REST-access quirks worth remembering.

## REST access gotchas (now in the trail doc)

- REST rides `index.php?rest_route=`; extra args go on `&` not `?`.
- `~/.config/secrets/wp-boards.env` password contains shell-special chars —
  parse the file; `source` executes fragments of it.
- Writers must use origin `boards.h3.gizmo-thailand.com`; the public edge
  bot-checks bare/script UAs.

## Verify

```
GET {origin}/wp/index.php?rest_route=/wp/v2/plugins&context=edit  (admin app pw)
  -> chaba-boards 0.3.3 active
GET .../wp/v2/types            -> all 10 CPTs present
GET .../wp/v2/asset&status=any -> id 266 sample
```
