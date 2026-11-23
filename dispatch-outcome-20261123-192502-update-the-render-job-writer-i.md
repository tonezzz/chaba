# Dispatch outcome — render-job-writer-must-upload-output-to-78229c (2026-11-23, tony-macbook)

## What was found

- The render_job **writers do not live in the chaba repo** — they are
  ada-voice tools (`backend/tools.d/ada_render_image.py`,
  `ada_render_video.py`, `wp_client.py`), which this chaba-only worktree
  cannot reach. Every chaba-side consumer (qc-scoreboard, line-digest,
  wp-comment-sync, the chaba-boards plugin) only *reads* render_job; the
  plugin already flags path-shaped output_url as broken.
- The convention was already documented (ssot.wp-boards.yml
  writers.render_job): upload via POST /wp/v2/media, store the returned
  source_url (or member-gated chaba/v1/media/<id>), never a filesystem
  path. What was missing was a canonical implementation in chaba.
- Prior attempt (2026-11-17, tony-dell) died exit=1 in ~4s — infra crash,
  no work product; its branch never reached origin.

## What changed (this branch, commit 03c57667bf)

- `scripts/lib/wp_boards.py` (new) — shared WP boards REST client
  consolidating the hand-rolled plumbing every scripts/ada/*.py writer
  carries (wp-boards.env parse, Basic auth, `index.php?rest_route=`
  quirk), plus `upload_media()` (POST /wp/v2/media; path|bytes|fileobj|
  http(s) source; `WP_MEDIA_MAX_BYTES` cap) and `write_render_job()`
  which uploads `output` FIRST, then creates/slug-upserts the private
  render_job post with `output_url=source_url`, `featured_media`=attachment
  id, title per title_standard. `member_gated=True` stores the plugin's
  `chaba/v1/media/<id>` URL. A non-http(s) `output_url` (the original
  filesystem-path bug) raises `WpBoardsError` before any WP write.
- `scripts/ada/render-job-record.py` (new) — CLI wrapper:
  `--kind image|video --prompt ... --output <path|url> [meta flags]
  [--slug] [--member-gated] [--dry-run]`; prints `{ok,id,slug,output_url}`.
- `tests/test_wp_boards.py` (new) — 11 offline unit tests (mocked
  urllib): upload-before-post ordering, output_url=source_url,
  featured_media, path rejection, slug upsert, member-gated URL,
  dry-run, CLI happy path.
- `docs/ssot/apps/ssot.wp-boards.yml` — writers.render_job now points at
  the canonical implementation.
- `docs/ssot/jobs/ada/2026-11-23-render-job-media-upload.yml` — trail doc
  incl. the remaining ada-voice wiring gap.

## Result / how to verify

- `python3 -m unittest tests.test_wp_boards` — 11/11 pass, fully offline.
- Live done-condition (real render_job → /wp/v2/media → valid
  output_url) is **one command away on a writer host** — tony-macbook has
  no `~/.config/secrets/wp-boards.env`:
  `python3 ~/CascadeProjects/chaba/scripts/ada/render-job-record.py
   --kind image --prompt "verify" --output <png> --source dispatch-verify`
  on tony-dell/idc03 after merge (chaba-repo-sync carries it).
- **Remaining gap (carded in comms):** ada-voice `ada_render_image` /
  `ada_render_video` still write path-only output_urls until they adopt
  this — either subprocess `render-job-record.py` via CHABA_REPO
  (trip_calendar precedent) or an ada-voice patch adding
  `wp_client.upload_media`. That is a separate ada-voice-repo dispatch.

lessons:
- "The render_job writer" is NOT in chaba — writers are ada-voice tools; chaba only reads the CPT. Check `ssot.tools.yml` `source:` fields before assuming a writer lives in the dispatch repo.
- Every scripts/ada/*.py WP writer hand-rolls env-parse + Basic auth + `index.php?rest_route=` — `scripts/lib/wp_boards.py` is now the shared home; new WP writers should use it.
- WP REST on the Plesk vhost: query args ride as literal `&param=` after `rest_route=` (a `?` is normalized to `&`), and `/wp/v2/media` POST wants raw bytes + `Content-Disposition: attachment; filename=`.
- output_url convention is enforceable in code: reject any non-http(s) value before the POST — the filesystem-path bug (job 117) becomes impossible rather than flagged-after-the-fact.
- A chaba-worktree dispatch CAN land the canonical writer + CLI that ada-voice tools later adopt (subprocess via CHABA_REPO is an established pattern — trip_calendar does it).
