# Dispatch outcome — wiki-page-door-infrastructure-namespace (attempt, idc02, 2026-11-23 17:27)

## What changed

Re-applied the previously completed-and-verified work onto current master.
The original commit `3ac5d7f6f6` (branch
`dispatch/20261120-190141-extend-wiki-page-door-to-allow`, pushed 2026-11-20)
never merged — the merge gate's full-suite run timed out at 240s, and every
re-dispatch since died on provider rate-limits before doing work. This run
cherry-picked it as **`b68631f2b9`** on
`dispatch/20261123-172715-extend-wiki-page-door-to-allow`.

Diff (5 files, +58/−11 — same as the original commit):

- `scripts/board/board-api.py` — `WIKI_PAGE_PREFIXES` now
  `("Education:", "Reports:", "Infrastructure:")`; docstring updated to
  note that Infrastructure: edits still pass the wiki-side Lockdown
  inhouse/sysop group check — the prefix gate is a guard, not an ACL grant.
- `tests/board/test_publication.py` — new
  `test_wiki_page_infrastructure_ns`: an `Infrastructure:Hosts/…` title
  writes when siteinfo reports the namespace registered, and is refused
  ("not registered") when it doesn't — same siteinfo gate as
  Education:/Reports:.
- `docs/kb/board-api-write-door.md` — `/wiki/page` row added to the
  endpoint table + an endpoint-notes paragraph documenting the allowlist
  and the Lockdown caveat.
- `docs/ssot/infrastructure/ssot.jobs.yml` — fleet-mcp job note updated:
  Infrastructure: writes now go through the /wiki/page door.
- `scripts/mcp-inventory.py` — comment updated likewise.

Merge conflict resolved: master had added a `/opencode-command` row to the
runbook endpoint table since Nov 20 — both rows kept.

## Result

- `pytest tests/board/test_publication.py tests/board/test_board_api_mutations.py`
  → **99 passed in 8.03s**
- `python3 scripts/board/board-api.py --selftest` → **selftest ok**
  (the `No module named 'lib'` report-index-regen warning is pre-existing
  on master, unrelated)
- `board-api.py` and `ssot.jobs.yml` both parse clean.

## How to verify / deploy

After merge + `git pull` in the idc03 served checkout + restart of
`chaba-board-api.service`, the door accepts e.g.:

```bash
curl -sX POST https://idc03.taila0626a.ts.net:10000/wiki/page \
  -H 'Content-Type: application/json' -d '{
    "title":"Infrastructure:Hosts/tony-dell/Backup-and-Recovery",
    "wikitext":"<dell disk-DR / fleet-backup plan>"}'
```

Pre-merge sanity: `grep WIKI_PAGE_PREFIXES scripts/board/board-api.py`
shows the three prefixes; `pytest tests/board/test_publication.py -k
infrastructure` runs the new gate test alone.

## Caveats

- The Nov-20 merge was held by the test gate's 240s full-suite timeout —
  an infra constraint, not a defect in this diff. Targeted tests pass in
  seconds; if the gate times out again the suite duration is the thing to
  fix, not this change.
- Infrastructure: is Lockdown-protected wiki-side; the write only
  succeeds because the door's wiki account is in the inhouse/sysop
  group. If live writes 403, check that account's groups first.

lessons:
- Prior dispatch branches stay fetchable on origin — `git fetch origin dispatch/<old>` + `git cat-file -t <sha>` recovers completed-but-unmerged work instead of redoing it.
- When a card re-dispatches, read the full comms trail first: this card's "failures" were provider rate-limits, not bad code — the fix was a cherry-pick, not new work.
- Cherry-picking old dispatch commits onto current master hits trivial conflicts in docs tables that gained rows meanwhile; resolve by keeping both rows.
