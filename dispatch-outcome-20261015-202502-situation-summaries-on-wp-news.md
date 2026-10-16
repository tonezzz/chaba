# Dispatch outcome — news-situation-summaries, attempt 3 (OPS-0706)

## Why a third attempt

Card re-queued at 20:25. Verified state going in: attempt-2's deploy was
live on idc03, but its branch (`86f54f5a9`) had NOT merged to master — so
master still carried the attempt-1 merge regression (dropped situation
hunks in `ssot.wp-boards.yml`, no dist zip, stale job-record status).

## What this run did

### 1. Verified the live feature end-to-end (idc03)

- `wp-news-situation.timer` armed `*:45` hourly; ran 19:46 (5 flood
  digests nominated watching), 19:49, 20:45 — all clean. Next 21:45.
- `news-situation.py list` — 5 digests `watching` (288/319/337/437/438),
  tag 39 `situation-watching` applied; flag survived the 20:20 digest
  regen (keep_tags union works).
- Private index page 458 `/wp/index.php/situations/` live and refreshed
  each sweep.
- `ask "สรุปข่าวน้ำท่วม" --dry-run` → matched digest 288 at 0.574 cosine
  (>0.55) — would promote watching→pinned.
- `python3 -m unittest tests.ada.test_news_situation` — now 17 tests, OK.

### 2. Landed attempt-2's stranded fixes on this branch

Checked out `86f54f5a9`'s versions byte-identical (no intermediate edits
to these files between its base and mine, so identical-blob merge is
clean whichever branch lands first):

- `docs/ssot/apps/ssot.wp-boards.yml` — restores the dropped v0.6.0
  situation hunks (meta fields, `situation-*` tag mirror, `news_situation`
  writer entry, brief_th notes) alongside master's ops_error hunks.
- `docs/ssot/jobs/ada/2026-10-15-news-situation-summaries.yml` — status
  → live, deploy_notes rewritten with the real trail + timer-enable
  gotcha.
- `integrations/wp-boards/dist/chaba-boards-0.6.0.zip` — the wp-admin
  upload artifact for Tony's manual step.

### 3. Fixed a real gap: Thai briefs missing until the plugin deploys

`brief_th` lives only in registered meta — which WP REST silently drops
until chaba-boards 0.6.0 is uploaded (still pending Tony). Result: the
index rendered titles only and `ask` printed no TH line, despite digests
437/438/319 already carrying a `สรุป` paragraph in post_content.

Added `brief_th_of(post)` in `scripts/ada/news-situation.py`: meta first,
else parses the `<p class="brief-th">` block from the digest body. Wired
into `cmd_index` rows and `cmd_ask` output. Verified live: `index
--dry-run` now renders real Thai briefs on 3/5 digests (288/337 predate
the new prompt — they pick it up on next regen). +3 tests (17 total).

### 4. Board comms

Progress comment posted (verified state + stranded-branch note). The
open wp-admin-upload request from attempt-2 stands — the flag/index/ask
all function via the tag mirror meanwhile.

## Still open (gates, not this run's scope)

- wp-admin upload of `dist/chaba-boards-0.6.0.zip` — Tony's documented
  manual path (~1 min); unlocks registered meta, admin column, badge,
  `[chaba_situations]`.
- ada-voice tool wiring — card `ada-voice-news-situation-ask` (ADA-0707).
- Attempt-2's branch `dispatch/20261015-194424-…` is still on origin
  unmerged — identical file contents mean whichever merges first lands
  cleanly; the other no-ops on those paths.

## Verify

```
systemctl --user list-timers wp-news-situation.timer   # idc03, armed :45
python3 -m unittest tests.ada.test_news_situation      # 17 tests OK
python3 scripts/ada/news-situation.py list             # 5 watching
python3 scripts/ada/news-situation.py index --dry-run  # TH briefs render
```

## Lessons

- Dispatch-branch merges can strand when a card is re-queued before the
  previous attempt merges — check `git merge-base --is-ancestor` on
  earlier attempt branches before assuming the fix landed.
- WP REST silently drops unregistered meta — any "meta-cached" value
  needs a content/tag fallback while the registering plugin is pending
  deploy, or the feature is quietly half-dead in the gap.
