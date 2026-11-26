# Dispatch outcome — lesson-comments-dev-board (phase 1)

Session: devin-dispatch 20261126-140605-phase-1-only-1-digest-worker-c
Branch: dispatch/20261126-140605-phase-1-only-1-digest-worker-c
Commit: 57e0109bff1 (worktree only — not pushed, per dispatch rails)

## What changed

Phase-1 spec implemented end to end (code + tests + runbook; live
verification is gated on deploy/provisioning steps below):

1. **Digest-worker classify -> card** — `scripts/ada/wp-comment-sync.py`:
   digest-bound comments (lesson, CMS posts, cam/bench/render_job,
   unknown types — i.e. everything that used to be "digest only") now get
   one chat-local classification (`WCS_BOARD_CLASSIFY`, model
   `WCS_BOARD_CLASSIFY_MODEL`, default `chat-local`):
   - `actionable` -> kanban card via board-api `POST /card`, id
     `wpc-<comment_id>` (dedupes re-polls; "already exists" counts as
     filed), column `backlog`, priority `medium`, spec carries
     post_id + comment_id + permalink + the loop-close contract.
   - `question` -> focus-inbox entry via `POST /inbox` (tags
     wp-comment/wp-question, owner devin) + local
     `questions/q-<cid>.yml` record + digest line.
   - `discussion` -> digest.jsonl only (class recorded).
   Spec said "POST /request" — that endpoint raises requests on
   EXISTING cards and cannot create one or set a column; `POST /card`
   is the only door that produces a backlog card, so `/card` is used.
   In-thread acks now post as the `chaba` WP agent identity when
   `~/.config/secrets/wp-agent-users.env` exists (fallback: shared app
   user). Comments authored by devin/ada/chaba WP identities are marked
   processed and never re-routed — they are the loop-close replies.

2. **WP identity / hold-queue fix** — three pieces:
   - `integrations/wp-boards/chaba-boards.php` v0.10.0 -> v0.11.0:
     registers `chaba_agent` role on init (read + read_private_posts +
     moderate_comments; idempotent cap convergence). `moderate_comments`
     is what lets `status:"approve"` pass the REST comments controller's
     cap check; `read_private_posts` covers private CPT posts.
     `dist/chaba-boards-0.11.0.zip` built (wp-admin upload layout).
   - `scripts/wp-boards/ensure-agent-users.py` (new): provisions
     devin/ada/chaba WP users + chaba_agent role + Application
     Passwords, writes `wp-agent-users.env` (0600). Auth = wp-login
     cookie + wp_rest nonce (the omen admin credential file — there is
     NO WP-CLI/SSH path to the h3 Plesk host) or `--admin-app-password`.
     `--check` verifies, `--rotate` remints.
   - `scripts/board/board-api.py`: new remote-write endpoint
     `POST /wp-comment {post|post_id, parent?, content|text,
     as: devin|ada|chaba}` — in-thread reply under a real agent
     identity; devin/ada callers may only post `as` themselves;
     payload sends `status:"approve"` so a missing cap 403s loudly
     instead of silently holding. `wp_api()` gained an `agent` kwarg
     reading per-identity creds from `wp-agent-users.env`
     (`BOARD_API_WP_AGENT_ENV` override).
   - `scripts/ada/news-situation.py`: transition comments prefer the
     `chaba` agent identity (real author, approved) with app-user
     fallback.

3. **Loop-close convention** — documented in code, card spec template,
   and runbook: the actioning agent replies via
   `POST /wp-comment {post, parent:<comment_id>, content, as:<self>}`
   and records the returned WP comment id in card comms (`POST
   /comment`). wp-comment-sync skips agent-authored comments so replies
   never re-enter the front door.

4. **SSOT trail** — runbook
   `docs/ssot/jobs/wordpress/2026-11-26-comment-dev-board.yml`
   (provisioning order, verify steps, deferred scope); `ssot.jobs.yml`
   wp-comment-sync entry updated; `ssot.wp-boards.yml` v0.11.0 note.

## Result / verification status

- Unit tests: 27 new (`tests/ada/test_wp_comment_sync_board.py`,
  `tests/board/test_board_api_wp_comment.py`) — all pass; related
  suites (test_news_situation, test_board_api_mutations,
  test_board_api_reads) pass. `python3 -m unittest discover
  tests/board` shows pre-existing env failures (no pytest module,
  merge-gate timing tests) unrelated to this change.
- Live e2e NOT yet verified — requires, in order (all documented in the
  runbook):
  1. Deploy chaba-boards 0.11.0 via `deploy-plugin-zip.sh` on tony-omen
     (wp-admin upload is a Tony gate).
  2. Run `ensure-agent-users.py` on tony-omen, scp
     `wp-agent-users.env` to idc03 `~/.config/secrets/` (0600).
  3. Merge this branch so idc03's exec checkout + board-api pick it up.
  4. Probe: `POST /wp-comment {post:<lesson id>, content:"probe",
     as:"chaba", from:"tony"}` -> expect `status:"approved"`, author
     "Chaba".
  5. Comment on a lesson/CMS post -> within one 15-min digest cycle a
     `wpc-<cid>` card lands in backlog (actionable) or a focus-inbox
     entry (question); ack is threaded under the comment.

## Lessons

- board-api `POST /request` cannot create cards — it raises requests on
  existing cards only; `POST /card` is the create door (spec text said
  /request, intent was clearly "file a card").
- WP REST comments: `status` on create requires `moderate_comments` —
  pass `status:"approve"` so a mis-provisioned identity 403s instead of
  silently landing in the hold queue.
- boards WP host has no SSH/WP-CLI/Plesk path (ssot.secrets gap) — the
  only admin surface is wp-admin on tony-omen; agent-user provisioning
  had to ride the wp-login cookie + X-WP-Nonce REST flow.
- wp-comment-sync saves processed/acks state once at end-of-run — a
  mid-run kill (e.g. systemd timeout) can double-post acks on the next
  poll; cards/questions dedupe by deterministic id, acks do not.
