# Dispatch outcome — ada-wiki-extension-confirm-flag

## What changed

Card `ada-wiki-extension-confirm-flag` (ref ADA-1324): board-api
`/wiki/extension` now hard-requires `confirm=true` in the POST body for
`install|enable|disable`; both Ada call paths omitted it and would 400
once the hardened door deployed.

The card's edit point is tony-dell `~/CascadeProjects/ada-voice`, but
this dispatch ran on tony-macbook whose local ada-voice checkout was 134
commits behind. I fetched `origin/main` and created a dedicated
worktree instead of touching either live checkout:

- Worktree: `/home/tony/CascadeProjects/ada-voice-wt-wiki-confirm-flag`
  (moved out of this chaba worktree after committing, so the dispatcher
  cannot sweep the nested repo into a chaba commit)
- Branch: `dispatch/wiki-extension-confirm-flag` (2 commits ahead of
  `origin/main` c9d0f30; NOT pushed — dispatch rails)

Commits:

- `e12c641` — the fix + tests
- `d5c6132`→`d5c9132` — job trail
  `docs/ssot/jobs/ada/2026-11-24-wiki-extension-confirm-flag.yml`

## Diff summary (ada-voice repo)

- `backend/tools.d/wiki_extension.py` — `run()` adds
  `body["confirm"] = True` when `action != "list"`. The manifest
  `policy: confirmed` gate already gates the call before `run()`, so
  reaching `run()` for a mutation means confirmation happened.
- `opencode/ada_mcp.py` — `ada_wiki_extension()` payload adds
  `confirm=true` for non-list actions (only reachable after its own
  `confirmed=true` gate). `ada_wiki_extensions` (list-only) untouched.
- `tests/scenario_engine.py` — fakeboard `/wiki/extension` now mirrors
  the hardened door: non-list without `confirm is True` → 400, so the
  offline scenario exercises the real gate.
- `tests/scenarios/wiki_extension_gate.yaml` — board audit now asserts
  `'"confirm": true'` on the wire for the enable call.
- `tests/test_wiki_extension.py` — install expectation updated to
  include `confirm: True`; new `test_list_stays_confirm_free` pins the
  list body confirm-free.

## Verification

- `python3 scripts/tool-lint.py` — clean (69 warnings, none new)
- `.venv/bin/python -m pytest tests/ -x -q` — **1977 passed, 4 skipped**
  (fresh venv: pytest, pytest-asyncio, httpx, websockets,
  backend/requirements.txt minus torch/speechbrain/faster-whisper/
  soundfile/av — dep_stubs covers genai/fastapi/mcp)
- `pytest tests/test_scenarios.py -k wiki_extension` — pass against the
  confirm-enforcing fakeboard (proves the tool sends the flag)

## How to verify / next steps

1. Review/merge `dispatch/wiki-extension-confirm-flag` in
   `~/CascadeProjects/ada-voice` (tony-dell edit point) or push the
   branch to origin first.
2. Deploy via `deploy-ada.sh` on idc03; `ada-ocb-bridge-sync` will ff
   the bridge worktree (`~/CascadeProjects/ada-bridge`) on its timer.
3. Live check: `wiki_extension {action: enable, name: Mermaid,
   confirmed: true}` should no longer 400 with "needs confirm=true".

Note: chaba-side `scripts/board/board-api.py::do_wiki_extension`
(chaba worktree, ~line 3335) already enforces `confirm is True` — this
change is the ada-voice client side of that contract.

lessons:
- Card spec named tony-dell as ada-voice edit point, but dispatch ran on tony-macbook whose checkout was 134 behind — `git fetch origin && git worktree add <dir> -b <branch> origin/main` off the local clone is the clean isolation move.
- Nested a foreign-repo worktree inside the chaba dispatch worktree initially, then `git worktree move`d it to ~/CascadeProjects post-commit — keeps the dispatcher from `git add -A`-ing a nested repo.
- ada-voice tests run without the full requirements.txt: tests/dep_stubs.py stubs genai/fastapi/mcp; torch/speechbrain/faster-whisper/soundfile/av can be skipped for the unit+scenario suite.
- The scenario fakeboard (tests/scenario_engine.py) is the right place to mirror a hardened door — asserting '"confirm": true' in the `audit: board` call log gives end-to-end coverage of wire fields.
