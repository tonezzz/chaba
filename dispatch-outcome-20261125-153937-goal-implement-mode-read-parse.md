# Dispatch outcome — board-api-wiki-read-search-doors

## What changed

`scripts/board/board-api.py` (commit acf836f76d4 on
`dispatch/20261125-153937-goal-implement-mode-read-parse`):

- `do_wiki_page` now accepts `mode=read|parse` (absent/`write` keeps the
  existing guarded write path). `mode=read` → `action=query
  prop=revisions rvprop=content` returning raw wikitext
  (`missing:true` for absent pages, not an error). `mode=parse` →
  `action=parse prop=text|wikitext|revid redirects=1 formatversion=2`
  returning `html` + `wikitext` + `revid`. Both ride `_wiki_login` so
  Lockdown-protected namespaces resolve, and deliberately skip the
  write allowlist — recall is governed by the wiki's own read ACLs.
- New `do_wiki_search` + `POST /wiki/search {query|q, limit|srlimit
  (≤50, default 10), srnamespace?}` → `action=query list=search`;
  results carry title, HTML-stripped/unescaped snippet, timestamp,
  wordcount, and an `index.php?title=` url.
- Routing: `/wiki/search` added to `REMOTE_WRITE_PATHS` (WP_LOCK +
  `run_bounded` deadline like the other remote doors), `_remote_dispatch`,
  and the `job_actor` actor tuple; `import html` added.
- `tests/board/test_publication.py`: `_fake_wiki_read_api` seam + 6 new
  tests covering read/parse/missing/bad-mode/search/clamp/query-required.
- Trail: `docs/ssot/jobs/board/2026-11-25-wiki-read-search-doors.yml`.

## Runner-agent redeploy

`scp scripts/board/runner-agent.py` → `~/.local/bin/runner-agent` on
tony-dell and idc02, `chmod 755`, sha256-verified:
`1514c75c4679a01b486bbffd9f75c5636d023fed528424aed358a970ee3f7210`
identical to each host's `~/CascadeProjects/chaba/scripts/board/
runner-agent.py`. Drift the card complained about had already
self-healed via `_self_update`/sync-runner-tools; the scp was a
verified byte-identical rewrite. Note: idc02's
`~/CascadeProjects/chaba-tony-dell` checkout still carries a different
runner-agent.py (adfa0c57…) — outside this card's named constraint.

## Verification

- `python3 -m unittest tests.board.test_publication` — 90 tests OK;
  `test_board_api_mutations` + `test_board_api_reads` +
  `test_wiki_extension` — 89 tests OK.
- Live MediaWiki contract probe run on idc03 (bot login, read-only —
  nothing deployed): `Education:Index` read → 23,803-char wikitext;
  parse → 44KB html + wikitext (revid populated once `prop=revid` was
  added — it was `None` without it); `list=search` → hits with the
  expected HTML/entity snippets that `_wiki_snippet_text` flattens.
- `_remote_dispatch("/wiki/search")` exercised with stubbed
  `WIKI_API_CALL` — wiring confirmed.

## Caveat / how to verify live

The doors go live when this branch merges — board-api serves from the
idc03 served checkout and no deploy was performed per dispatch rails.
Post-merge:

```
curl -X POST https://idc03.taila0626a.ts.net:10000/wiki/page \
  -H 'Content-Type: application/json' \
  -d '{"mode":"read","title":"Education:Index","from":"devin"}'
curl -X POST https://idc03.taila0626a.ts.net:10000/wiki/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"education","from":"devin"}'
```

Both should return 200 with payloads (no 404). ada-voice's
wiki_read/wiki_search tools then hit real doors instead of falling
back.

lessons:
- action=parse does NOT return revid unless `revid` is in prop — probe the live API shape before assuming fields.
- runner-agent drift on tony-dell/idc02 had already self-healed via _self_update; always sha256 both installed and repo copies before scp — the redeploy was a verified no-op.
- Read recall doors should skip the write allowlist but still ride the bot login — Lockdown namespaces need the session, and read ACLs are the wiki's own gate.
