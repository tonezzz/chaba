# dispatch 20261124-075942 — wiki-talk-watch-auto-reply (OPS-0074)

## What changed

Built the unattended wiki talk-page auto-reply loop end-to-end,
superseding the manual procedure card OPS-0073.

- `scripts/wiki/wiki-talk-watch.py` (new, ~1000 lines) — the watcher:
  - Polls `api.php list=recentchanges` (`rctype=edit|new`, talk ns
    1,3,5,7,9,11,13,15 + protected 3001/3003/3005/3007), `rclimit=50`
    paged via `rcend`/`rcstart`; client-side `rcid` filter is
    authoritative (1s timestamp resolution).
  - Watermark = max rcid in `~/.local/state/wiki-talk-watch/` +
    `processed_rcids`/`attempts` in state.json — idempotent reruns,
    per-rcid retry cap (3), first-ever run baselines instead of
    replying to history.
  - Comment extraction: diffs `revid` vs `old_revid` wikitext
    (difflib added-lines), batched `prop=revisions rvprop=ids|content
    rvslots=main`.
  - Classify v1 (JevTeam stand-in): LiteLLM `gemini-3.5-flash-lite`
    via `scripts/ada/gemini_rest.py` + `:4000` gateway, scoped
    `LITELLM_KEY_*` virtual key — lane `ada-code|no-response`.
  - Draft: opencode headless (`--standalone` for v2) when the binary
    resolves, else the same LiteLLM lane (`--drafter auto|litellm|
    opencode`). Reply signed `— Ada (ada-code) ~~~~~`, headings
    stripped.
  - Post: `action=edit&section=N&appendtext` inside the commenter's
    located talk section, fallback `section=new`; bot-flag retry
    without `bot` right.
  - Visibility guard: talk-ns tier (public/members/private) vs page
    protection — protected content can never land on a more-public
    talk page; anon mode skips non-public ns entirely.
  - Failures → deduped board-api `/inbox` flags (report-watch
    slug-dedupe pattern), systemic re-alert after 24h. `--dry-run`
    writes nothing; `--self-test` = 16 offline checks.
- `docs/ssot/infrastructure/ssot.jobs.yml` — `wiki-talk-watch` entry,
  idc03 systemd user timer `OnCalendar=*-*-* *:07/15:00` (explicit
  offset minutes, ~7min clear of kanban-commit's drifting 15-min
  cycle). Units rendered to `systemd/generated/idc03/wiki-talk-watch.
  {service,timer}`.
- `docs/ssot/jobs/education/2026-11-24-wiki-talk-watch.yml` — runbook.

## Bugs found & fixed during live verification

- `formatversion=2` emits slot key `content`, not `*` — all revision
  text fetches silently returned empty (every candidate looked like
  "empty diff"). Fixed via `_slot_text()` handling both keys.
- `rvprop=content` alone omits `revid` from the response — revisions
  were skipped by the `"revid" in r` guard. Fixed to `ids|content`.
- `LITELLM_URL` env files carry the OpenAI-style `.../v1` base;
  `gemini_rest.endpoint()` appends `/v1beta` itself → 404. Normalized
  by stripping a trailing `/v1`.
- formatversion=2 carries `minor`/`bot` as booleans, not a `flags`
  string — skip checks updated for both shapes.

## Verification

- `--self-test`: 16/16 PASS (section parse/locate, diff extraction,
  signature/heading strip, guard public/members/private/password).
- Live on idc03, authed as `ada`, `--dry-run --process-all`: all 11
  real rcids walked — Tony/Tonezzzz questions on Education talk +
  Reports talk classified to sensible lanes (`ada-code` for questions,
  `no-response` for an admin-decision ask), drafts previewed with
  signature, `guard=ok`, own-bot/minor/empty-diff skips correct.
- Anon run degrades cleanly: public-ns only + watermark baseline.
- YAML: ssot.jobs.yml + jobs doc validate; `render-jobs.py --check`
  OK (119 jobs).

## How to verify / finish

Post-merge on idc03 (served checkout):
`python3 scripts/render-jobs.py --host idc03 --ids wiki-talk-watch --install`
then `systemctl --user enable --now wiki-talk-watch.timer`. First tick
baselines the watermark (never replies to history). Acceptance test:
post a fresh comment on `Education talk:ZZ-Talk-Watch-Probe` → next
tick drafts + posts a signed reply; anon stays denied on protected ns.

## Open items

- opencode is NOT installed on idc03 — `--drafter auto` falls back to
  the LiteLLM lane until `OPENCODE_BIN` resolves (PATH,
  ~/.opencode/bin, ~/.local/bin probed).
- The literal POST path (`action=edit`) is exercised only by self-test
  + dry-run preview; first live proof is the post-install timer tick
  above (no non-Ada creds available in-session to force a reply).

lessons:
- MediaWiki formatversion=2 changes TWO silent shapes at once: slot
  content key becomes `content` (not `*`) and minor/bot become
  booleans (no `flags` string) — and `rvprop=content` alone drops
  `revid` from the payload entirely.
- LiteLLM gateway env files carry the OpenAI base (`.../v1`) but
  gemini_rest wants the root — strip `/v1` before passing
  base_url_override or every call 404s.
- Session-compaction commits sweep tracked-file edits but leave new
  files untracked — commit new deliverables explicitly before ending.
