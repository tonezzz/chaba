# Dispatch outcome — news-situation-summaries (OPS-0706)

## What was asked
Situation summaries on wp-news: flag high-interest digest posts as tracked
"situations", surface them on /wp/ for the household, in Thai, with an
ask-hook (Tony's "สรุปข่าวน้ำท่วม" ask on tony-ha was the trigger).
NOTE: the card `note` was truncated at capture (board-api caps `note` at
500 chars) — the BUILD list was rebuilt from the title + `help` field +
verified DESIGN preamble. Reconstruction posted as a card comment.

## What changed (this worktree, dispatch branch — not pushed, not deployed)

- `scripts/ada/news-situation.py` (NEW) — the situation engine:
  - `list` / `set` / `promote` / `demote` — flag ladder none→watching→pinned.
    Pin also sets WP `sticky` (falls back cleanly if the hierarchical CPT
    rejects it). Every transition posts a WP comment (never silent).
  - `ask "<text>"` — member-ask hook: embeds the ask (LiteLLM
    ollama-nomic-embed, ngram fallback), matches digest title+lead by
    cosine (--threshold 0.55, below → exit 3, no write), promotes one rung,
    prints TH+EN briefs + link — the answer Ada relays. `--json` for tools.
  - `sweep` — auto-nominates `watching` on ≥3-source or disaster-desk
    digests. Never pins, never demotes, skips flagged posts.
  - `index` — upserts private WP page slug `situations` (lessons-due
    pattern), Thai-first, pinned then watching, with provenance.
- `scripts/ada/news-digest.py` — LLM now returns `brief_th` (rendered as a
  สรุป block + cached in meta `brief_th`); on digest regeneration the
  parent's `situation*` meta and `situation-*` tag are re-asserted so the
  flag survives (tags were the actual risk — `tags` payload replaces).
- `scripts/ada/wp-comment-sync.py` — new `news` lane: member comments
  pin/watch promote, unpin demotes one rung, unwatch/clear stops tracking
  (EN + Thai: ปักหมุด/เลิกปักหมุด/เฝ้าระวัง/เลิกติดตาม), applied through
  the shared set_state; ack reply states the new state. Non-command news
  comments keep routing to the digest lane. Env now lazy so the module is
  importable in tests.
- `integrations/wp-boards/chaba-boards.php` — v0.6.0: registers news meta
  `situation`/`situation_since`/`situation_by`/`brief_th`, adds a
  Situation admin column, a badge banner on flagged digest single views,
  and the `[chaba_situations]` shortcode (same index list, embeddable on
  any member page).
- `docs/ssot/infrastructure/ssot.jobs.yml` + `systemd/generated/idc03/` —
  new `wp-news-situation` job on idc03, OnCalendar :45 hourly (after fetch
  :00 / digest :20): `sweep` then `index`.
- `docs/ssot/apps/ssot.wp-boards.yml` — plugin version notes, news meta +
  situation-* tags, `news_situation` writer entry.
- `docs/ssot/jobs/ada/2026-10-15-news-situation-summaries.yml` — full
  design/deploy record (leave-a-trail).
- `tests/ada/test_news_situation.py` — 14 tests, all passing.

## Key design decisions
- **Flag lives in meta AND a tag mirror** (`situation-watching`/
  `situation-pinned`): meta keys are unregistered until chaba-boards 0.6.0
  deploys and WP REST silently drops them — tags are already writable, so
  the flag works today; meta becomes authoritative once deployed.
- **Additive ladder, suggestion-only, never silent**: auto-nominate only
  reaches `watching`; pinning needs a member signal (ask or comment);
  every change leaves a WP comment trail.
- **`unpin` demotes one rung** (pinned→watching), `unwatch`/`clear` stops
  tracking — a pinned digest was usually auto-nominated for a reason.

## Verify
```
python3 -m unittest tests.ada.test_news_situation          # 14 tests OK
python3 scripts/ada/news-situation.py --help
python3 scripts/ada/news-situation.py sweep --dry-run      # on idc03
python3 scripts/ada/news-situation.py index --dry-run
python3 scripts/ada/news-situation.py ask "สรุปข่าวน้ำท่วม" --dry-run
```
Full suite: 310 tests — only pre-existing failures (6 modules need pytest,
not installed on this host); unrelated.

## To go live (needs merge + deploy, not done per dispatch rules)
1. Merge to master → idc03 checkout picks up the scripts.
2. `render-jobs.py --host idc03 --install` (or install
   `systemd/generated/idc03/wp-news-situation.*`) — enables sweep+index.
3. Upload chaba-boards.php 0.6.0 via wp-admin plugin zip — unlocks the
   registered meta, admin column, badge, and shortcode. Flag itself works
   pre-deploy via tags; `/wp/tag/situation-pinned/` is a free public view.
4. ada-voice side: wire `news-situation.py ask "<text>"` as a callable so
   voice asks promote + read back briefs (separate repo — not in scope).

## Result
Built and tested — flag, promotion ladder, index, Thai, ask-hook, and
comment commands are in place on the dispatch branch; live effect begins
after merge + the two deploy steps above.
