# Dispatch outcome — wiki-extension-control-plane (attempt 2)

Card: `wiki-extension-control-plane` (ADA-1033)
Branch: `dispatch/20261124-201305-create-a-controlled-wiki-exten`
(cherry-picked prior attempt's 3d8e721d4f + b6b86d95ab, plus b19e6069b4)

## Prior failure fixed

Attempt 1 (tony-macbook) finished cleanly but the merge was held:
"test gate failed — pytest unavailable — no test evidence" (OPS-1191
fail-closed) plus a dirty worktree. This attempt ran on tony-omen where
`python3 -m pytest` (9.0.2) exists, added the new suite to the chaba
merge-gate command, and ran the full gate locally: **260 passed in 84s**
(well under the 240s gate timeout). Merge evidence is now producible.

## What changed this attempt

- `scripts/board/board-api.py` `do_wiki_extension`: **idempotent
  no-op** — when siteinfo already shows the requested end-state
  (name present for install|enable, absent for disable) the door
  verifies via the extension table, writes a `wiki-extension-receipt/1`
  receipt, and returns `verified:true, no_op:true` without calling
  Springboard. This keeps every approved mutation honest AND usable
  while Springboard's sbname validation is broken on MW 1.46 — and it
  means `install CategoryTree` with `confirm:true` returns a verified
  result today (CategoryTree is already installed).
- `tests/board/test_wiki_extension.py`: +2 tests (install-already-
  present no-op, enable-present/disable-absent no-ops) — 11 total, all
  green; asserts Springboard is never invoked on no-ops.
- `scripts/board/dispatch_repos.py`: added
  `tests/board/test_wiki_extension.py` to the chaba merge test-gate
  command so the suite contributes merge evidence going forward.
- Docs: `docs/kb/board-api-write-door.md` no-op paragraph;
  `docs/ssot/jobs/infrastructure/2026-11-24-wiki-extension-control-plane.yml`
  contract/verify/followups updated; `ssot.mediawiki-news.yml`
  install_gate note amended.

## Verified live (idc03 board-api + wiki.h3)

- `POST /wiki/extension {action:list}` → ok; all 7 approved extensions
  installed+enabled: Cargo, CategoryTree, Lockdown, Mermaid, MsUpload,
  MultimediaViewer, PageForms.
- siteinfo siprop=extensions confirms the same set (Special:Version
  equivalent evidence).
- `News/Desks/DevNest/Guides/Extensions-Readiness-Test` → 200,
  `Mermaid-Flow-Test` → 200, `News` root → 200 — nothing broken.
- "Install CategoryTree and Mermaid first" — already satisfied; both
  installed since the 2026-11-06 manual path.

## Spec coverage status

- board-api `/wiki/extension` door: allowlist (list|install|enable|
  disable; CategoryTree/Mermaid/MsUpload/MultimediaViewer/Cargo/
  PageForms + Lockdown), confirm=true gate, one-per-request, no
  repo/branch/commit/delete params, before/after Special:Version +
  receipts, honest 502 — DONE (attempt 1 + this attempt's no-op).
- Ada `tools.d wiki_extension` policy=confirmed: registered in
  `ssot.tools.yml` + `ada-tools-commands.json`; ada-voice
  `backend/tools.d/wiki_extension.py` exists. **GAP:** it does not yet
  send `confirm:true` — filed as card `ada-wiki-extension-confirm-flag`
  (ADA-1324) since ada-voice is a separate repo.
- OpenCode-Ada tab surface: `ada-ocb: ada_wiki_extensions+
  ada_wiki_extension` via ada_mcp per ssot.tools.yml; offline scenario
  coverage lives in the ada-voice benchmark suite (separate repo,
  verified by prior attempt).
- WIKI_PASSWORD stays on idc03 (`~/.config/secrets/wiki-h3-gizmo.env`)
  — never exposed.

## Remaining gates (not dispatchable from here)

1. **Merge + deploy**: branch merges via normal sweep; then on idc03
   `chaba-repo-sync` updates `~/CascadeProjects/chaba-tony-dell` and
   `systemctl --user restart chaba-board-api` activates the hardened
   door (user unit; until then live door is the pre-hardening build).
2. **Springboard `$wgSpringboardURL`**: Tony answered "proceed" — but
   there is NO ops SSH/Plesk path to the ReadyIDC host
   (103.99.11.249; re-verified: no creds in any host's
   ~/.config/secrets). The fix is a one-line LocalSettings.php edit via
   Plesk panel:
   `$wgSpringboardURL = "https://raw.githubusercontent.com/CanastaWiki/RecommendedRevisions/master/1.44.yaml";`
   Until then, real (non-no-op) mutations fail honestly; all approved
   extensions are already installed so nothing user-visible is blocked.
3. **ADA-1324**: ada-voice confirm flag (above).

## How to verify

- `python3 -m pytest tests/board/test_wiki_extension.py -x -q` → 11
- Full gate set → 260 passed (~84s)
- `python3 scripts/board/board-api.py --selftest` → ok
- Live: `curl -X POST https://idc03.taila0626a.ts.net:10000/wiki/extension
  -d '{"action":"list"}'` (post-deploy: mutations need confirm:true;
  install CategoryTree → verified no_op + receipt)

lessons:
- The chaba merge test gate runs a FIXED file list in dispatch_repos.py REPO_TESTS — a new test file contributes no evidence unless added there; "pytest unavailable" on the claiming host fails the merge closed (OPS-1191), so host capability matters at claim time.
- MediaWiki siteinfo siprop=extensions lists ENABLED extensions only — an installed-but-disabled extension is invisible to it; idempotent no-op checks must treat "absent" as "not enabled", not "not installed".
- ReadyIDC/Plesk hosts (wiki.h3, boards.h3) have no ops SSH path — LocalSettings.php edits are Tony-panel-only; verify access before speccing agent-applied fixes.
- Springboard sbname validation reads a version-keyed YAML from $wgSpringboardURL; CanastaWiki/RecommendedRevisions lacks MW 1.46 — the plain-string 1.44.yaml URL is the workaround.
