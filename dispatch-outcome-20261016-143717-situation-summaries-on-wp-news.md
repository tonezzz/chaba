# Dispatch outcome — news-situation-summaries (attempt 4; rails label it "attempt 3")

## What the prior failure was

Attempt 2's branch (`dispatch/20261015-194424-*`, commit `86f54f5a9`) was held at
the merge gate by `tests/ada/test_draft_hit_frame.py::test_patches_apply_and_compile`.
Root cause was NOT the card's diff (4 files: docs + zip) — the gate test itself was
broken on master at that moment and fixed by `85ec42e86` ("unhold merge gate —
drop-patch tri-state + shallow clone + load/stub leaks"), which landed on master
2026-10-16 11:34, after attempt 2 failed. Attempt 3 on idc03 (commit `732eaa39a`)
contained the real reland but its push failed (`could not read Username for
github.com` — idc03 has no push creds) and the worktree was GC'd, leaving the commit
stranded in idc03's exec checkout.

## What I did

1. **Relanded the stranded work**: recovered `732eaa39a` from idc03 via
   `git format-patch` over SSH and `git am`'d it here as `69ad2cff9`
   (ssot.wp-boards.yml situation hunks, dist/chaba-boards-0.6.0.zip, live job
   status, brief_th content fallback). Supersedes attempt-2's branch byte-identically.
2. **Verified the gate**: `test_patches_apply_and_compile` + all 148 tests in
   tests/ada/ pass on this branch (fix was already on master — rebase was the fix).
3. **Executed Tony's "proceed"**: deployed `chaba-boards-0.6.0.zip` to
   boards.surf-thailand.com via new `scripts/wp-boards/deploy-plugin-zip.sh`
   (scripted wp-admin login → upload → overwrite-confirm flow, run on tony-omen
   where the admin credential file lives — creds never transit this machine).
   `/wp/v2/plugins` confirms `chaba-boards 0.6.0 active`; `ops_error` CPT is
   registered as a side benefit (unblocks ADA-0679 ops-error-posts).
4. **Fixed a real gap the deploy exposed**: the 7 digests flagged pre-0.6.0 carry
   the `situation-watching` tag but empty registered meta (REST silently dropped
   unregistered keys). Added `sync_meta_from_tag()` — the hourly sweep and
   `set_state`'s idempotent path now converge tag→meta silently (transition
   comments already exist; no WP noise). +3 tests → 20 in test_news_situation.py.
   Applied the same backfill live to all 7 watching digests (`situation=watching`,
   `situation_by=tag-sync`) so the admin column/badge/shortcode render now.
5. **Docs**: ssot.wp-boards.yml and the job record updated to deployed status,
   with the UA/app-password gotchas recorded.

## Live state

- wp-news-situation.timer armed on idc03 (:45 hourly; last ran clean 13:45).
- 7 flood digests `watching` — now backed by real meta, not just tags.
- Private page 458 `/wp/index.php/situations/` TH-first, re-renders each sweep.
- Plugin 0.6.0 active: registered meta, Situation admin column, digest badge,
  `[chaba_situations]` shortcode all live.
- brief_th meta fills on the next digest regen (writer in news-digest.py);
  the สรุป-paragraph fallback covers the interim once this branch syncs to idc03.
- Remaining out-of-scope: ada-voice ask wiring = card ada-voice-news-situation-ask
  (ADA-0707).

## How to verify

- `python3 -m pytest tests/ada/test_news_situation.py` → 20 pass.
- `curl -u $WP_APP_USER:$WP_APP_PASSWORD "$WP_SITE_URL/index.php?rest_route=/wp/v2/plugins"`
  → `chaba-boards 0.6.0 active`; `/wp/v2/types` shows `ops_error`.
- `ssh idc03 'cd ~/CascadeProjects/chaba && python3 scripts/ada/news-situation.py list'`
  → 7 watching rows (after repo-sync picks up this merge).
- wp-admin → News list shows a Situation column; a flagged digest's single view
  shows the badge.

lessons:
- Dispatch test-gate failures can be pre-existing master breakage — check whether
  the named test was fixed on master after the failed run before touching the diff.
- Stranded dispatch commits are recoverable: `ssh <host> git format-patch -1 <sha>
  --stdout | git am` beats reconstructing from comms.
- WP app passwords contain spaces — `source`ing wp-boards.env breaks silently;
  parse with `grep ^KEY= | cut -d= -f2-`.
- Cloudflare error 1010 blocks urllib's default `Python-urllib/x.y` UA on
  boards.surf-thailand.com — always send a chaba UA header.
- `IFS=, read` on a cred file without trailing newline returns 1 and kills
  `set -e` scripts before the first echo — append `|| true`.
