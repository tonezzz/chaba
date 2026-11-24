# Dispatch outcome — wiki-page-door-infrastructure-namespace

## What changed

`POST /wiki/page` (board-api `do_wiki_page`) now admits `Infrastructure:`
titles — `WIKI_PAGE_PREFIXES` grew from `("Education:", "Reports:")` to
include `"Infrastructure:"`. The door's existing guards apply unchanged:
the prefix allowlist, the siteinfo namespace-registration check, title/text
size caps, and the wiki-side Lockdown ACL (ns 3000 is inhouse/sysop — the
allowlist is a guard, not an ACL grant).

Commit `3ac5d7f6f6` on `dispatch/20261120-190141-extend-wiki-page-door-to-allow`:

- `scripts/board/board-api.py` — `WIKI_PAGE_PREFIXES` + docstring.
- `tests/board/test_publication.py` — new `test_wiki_page_infrastructure_ns`:
  `Infrastructure:Hosts/tony-dell/Backup-and-Recovery` writes when the ns is
  registered; unregistered `Infrastructure:` is refused by the siteinfo gate.
- `docs/kb/board-api-write-door.md` — `/wiki/page` was missing from the
  endpoint table entirely; added the row + an endpoint-note bullet covering
  the allowlist, the siteinfo gate, and the Lockdown caveat.
- `scripts/mcp-inventory.py` + `docs/ssot/infrastructure/ssot.jobs.yml` —
  refreshed the two stale "no Infrastructure: writes until the door card
  lands" notes.

## Result

- Live check: anon siteinfo on wiki.h3 confirms `Infrastructure` is
  registered at ns 3000, so the door's registration gate will pass.
- Tests: `pytest tests/board/test_publication.py` 72/72 pass;
  `tests/board/test_board_api_mutations.py` + `tests/test_lessons_due.py`
  38/38 pass; `board-api.py --selftest` ok.
- Prior failures (2026-11-19, exit=1 after ~4s on idc02 + tony-macbook)
  were provider rate-limit crashes, not a code approach — nothing to undo.
- NOT done here (needs merge→pull→`chaba-board-api` restart on idc03):
  actually publishing `Infrastructure:Hosts/tony-dell/Backup-and-Recovery`.
  The live door still rejects `Infrastructure:` until this lands.

## How to verify after merge+deploy

```bash
curl -sX POST https://idc03.taila0626a.ts.net:10000/wiki/page \
  -H 'Content-Type: application/json' -d '{
    "title":"Infrastructure:Hosts/tony-dell/Backup-and-Recovery",
    "wikitext":"= Backup and recovery =\n(dell disk-DR / fleet-backup plan)"}'
# expect {"ok":true, action:"success", ...}; then confirm the page exists
# via authenticated wiki read (anon read is accessdenied by Lockdown).
```

lessons:
- `/wiki/page` was absent from `docs/kb/board-api-write-door.md`'s endpoint table — when extending a door, check the runbook actually documents it.
- The siteinfo gate means a newly-allowlisted prefix is live-verified at write time; check `api.php?action=query&meta=siteinfo&siprop=namespaces` anonymously before claiming the path works.
- Prior attempts on this card died in ~4s with provider rate-limit signatures — an exit=1 with tiny CPU/wall time on dispatch units is a provider crash, not a task failure; don't burn the retry redesigning the approach.
