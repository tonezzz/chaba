# Dispatch outcome — wiki-extension-control-plane

Card: `wiki-extension-control-plane` (ADA-1033)
Branch: `dispatch/20261124-192442-create-a-controlled-wiki-exten` (commit 3d8e721d4f, not pushed)

## What changed

The `/wiki/extension` board-api door already existed (shipped 2026-11-04,
`be124ba312`) but was missing most of the spec'd controls. This dispatch
hardened it in `scripts/board/board-api.py` (`do_wiki_extension`):

- **Confirm gate** — `install|enable|disable` now require `confirm: true`
  (same shape as `/opencode-command`); `list` stays confirm-free. Mutations
  without it 400 before any login/Springboard call.
- **Allowlist** — unchanged and verified: `list|install|enable|disable` +
  CategoryTree, Mermaid, MsUpload, MultimediaViewer, Cargo, PageForms,
  Lockdown (Lockdown was Tony-added 2026-11-05 for the PrivateNews
  boundary — kept; Graph/Drawio/arbitrary names/repos refused).
- **Special:Version evidence** — new `_wiki_special_version()` captures
  `index.php/Special:Version` (sha256+bytes; the pretty `/wiki/` path 404s
  on this host) plus the siteinfo extension table, before and after every
  mutation.
- **Receipts** — every mutation attempt (ok AND failed) writes
  `wiki-extension-receipt/1` JSON to `$BOARD_API_WIKI_EXT_STATE`
  (default `~/.local/state/board-api-wiki-ext/` on the service host).
- **Honest failure** — Springboard/API errors and unverified results raise
  `UpstreamError` (502); install/enable require the name present after,
  disable requires it gone.

Tests: `tests/board/test_wiki_extension.py` — 9 unittest cases covering
action/name allowlist (incl. Graph/Drawio/repo-injection strings), the
confirm gate, list, install+disable happy paths with receipt assertions,
springboard error, unverified mutation, and login failure. All green;
`board-api.py --selftest` and the board-api mutation/read suites still pass.

Docs: `docs/kb/board-api-write-door.md` endpoint row + note;
`docs/ssot/apps/ssot.mediawiki-news.yml` install_gate corrected;
runbook trail at `docs/ssot/jobs/infrastructure/2026-11-24-wiki-extension-control-plane.yml`.

## Live verification (idc03 board-api + wiki.h3)

- `POST /wiki/extension {action:list}` → all 7 approved extensions already
  installed: Cargo, CategoryTree, Lockdown, Mermaid, MsUpload,
  MultimediaViewer, PageForms (plus core skins/Springboard/OIDC/PluggableAuth).
- Special:Version lists CategoryTree and Mermaid — the "install
  CategoryTree and Mermaid first" step is already satisfied; nothing to install.
- `News/Desks/DevNest/Guides/Extensions-Readiness-Test` and
  `Mermaid-Flow-Test` render (parse 200, content + categories intact);
  DevNest News root/desk/leaf pages all render — nothing broken.
- **BLOCKER found:** live `install`/`enable` calls return
  `springboard: Unrecognized value for parameter "sbname"` for every name.
  Root cause verified in Springboard source: `sbname` is validated against
  the YAML at `$wgSpringboardURL`; the extension.json default is version-keyed
  with only `"1.43"`, and CanastaWiki/RecommendedRevisions ships 1.39/1.43/
  1.44/1.47 — no 1.46 — while the wiki runs MediaWiki 1.46.2. Unless
  LocalSettings overrides it, the accepted set is empty. Minimal fix:
  `$wgSpringboardURL = "https://raw.githubusercontent.com/CanastaWiki/RecommendedRevisions/master/1.44.yaml"`
  (string form skips the version lookup; that YAML has all 7 names incl.
  Mermaid's SemanticMediaWiki repo override). Raised as a board request on
  the card — needs Plesk/LocalSettings access. This also means the
  2026-11-06 "installed via the door" claim was actually the manual
  bundle+LocalSettings path; SSOT corrected.

## Already-present spec items (other repos, verified via registry)

- Ada `tools.d wiki_extension` policy=confirmed — registered
  (`docs/ssot/infrastructure/ssot.tools.yml` wiki.extensions;
  `docs/kb/ada-tools-commands.json`, source `ada-voice:backend/tools.d/wiki_extension.py`,
  2026-11-04). **Follow-up:** the ada-voice tool must pass `confirm=true`
  on mutations for the tightened door.
- OpenCode-Ada tab surface — `ada-ocb: ada_wiki_extensions+ada_wiki_extension`
  via ada_mcp; command doc `stacks/idc02/ada-code/commands/ada.md` already
  describes both tools; offline scenario coverage for the wiki_extension
  gate landed in the ada-voice benchmark suite (card
  ada-benchmark-coverage-scenarios, 30/30 scenarios).
- WIKI_PASSWORD never leaves the service host — the door is the only path.

## How to verify

- `python3 -m unittest tests.board.test_wiki_extension` (9 tests)
- `python3 scripts/board/board-api.py --selftest`
- Live list: `curl -X POST https://idc03.taila0626a.ts.net:10000/wiki/extension -d '{"action":"list"}'`
- After merge+deploy: mutations without `confirm:true` → 400; with it →
  receipt under `~/.local/state/board-api-wiki-ext/` on idc03.

## Not done / gates

- Live confirmed install end-to-end: blocked by the Springboard
  `$wgSpringboardURL` config (board request raised). All target extensions
  are already installed, so the user-visible goal is met; the mutation
  path activates once LocalSettings is fixed and this branch deploys.
- Deploy: not pushed/deployed per dispatch rules; lands via normal merge +
  chaba-repo-sync on idc03.

lessons:
- Springboard sbname is validated against a version-keyed recommended-YAML fetched from $wgSpringboardURL — on MediaWiki versions missing from CanastaWiki/RecommendedRevisions (e.g. 1.46) EVERY name is rejected; check the MW version vs YAML keys before assuming the door is broken.
- Springboard install hardcodes github.com/wikimedia/mediawiki-extensions-<name> — third-party extensions need a `repository:` override in the recommended YAML (Mermaid → SemanticMediaWiki/Mermaid).
- index.php/Special:Version works anonymously; the pretty /wiki/Special:Version path 404s — use it for version-evidence captures.
- "installed via the door" SSOT claims can mask a manual install path — verify the mutation path itself, not just the resulting state.
