# Dispatch outcome — map-embed-tool, attempt 2 (2026-11-24, idc02)

## What attempt 1 actually left behind

The card comms showed a clean finish — both 2026-10-27 dispatches
merged to chaba master (`4c1af59d`, `8b3abeef`) and merge-sweep
auto-closed the card. What the close missed: **the ada-voice landing
never happened**. `map_embed` was staged in chaba
`integrations/ada-voice/` (drop 17) but was absent from ada-voice
`origin/main` a month later — drops 16 and wp_read/wp_update are
similarly still pending; drop 19 (host_status) leapfrogged via PR #21.
The card was done+archived, so nothing tracked the gap.

## What this run did

1. **Verified the gap** — `git ls-tree origin/main` on ada-voice
   (1c94657): no `tools.d/map_embed.py`, no manifest/tool_guide entry.
2. **Landed drop 17 for real** — worktree
   `~/CascadeProjects/ada-voice-wt-map-embed`, branch
   `feat/map-embed-drop-17`:
   - `backend/tools.d/map_embed.py` + `tests/scenarios-live/map_embed.yaml` copied verbatim from the chaba drop
   - manifest entry appended (read, secondary_allowed, 60s), tool_guide fragment appended
   - `count_cap` bumped **115→116** (the staged patch's 112→113 base was stale — applied manually per the README fallback)
3. **Gates green** — `tool-lint.py` clean (74 declared, cap 116);
   `pytest tests/ -x -q` = **1942 passed, 7 skipped**; `tools_loader`
   registers map_embed; keyless smoke correct (OSM static URL,
   honest `needs_key` on interactive, route + error paths).
4. **Pushed + PR** — https://github.com/tonezzz/ada-voice/pull/22
5. **Found the key was never dropped** — Tony's 2026-10-27 answer
   claimed `GOOGLE_MAPS_API_KEY` was minted into
   `~/.config/secrets/tony-ha/backend.env` on idc03. Verified
   2026-11-24 via ssh: absent from all four persona backend.env files
   and everywhere under `~/.config/secrets/` (only the known-dead gev
   copy remains). Recorded in `ssot.secrets.yml` (`gev-google-maps`
   note) — interactive embeds still need the key re-dropped; the tool
   works keyless meanwhile.
6. **Trail** — job note
   `docs/ssot/jobs/ada/2026-11-24-map-embed-drop17-landing.yml`; new
   board card `ada-voice-map-embed-pr22-merge-deploy` (ADA-0028)
   tracking merge → deploy-ada.sh → render-tool-profiles → key drop;
   comment posted on the archived card.

## Result / how to verify

- PR: `gh pr view 22 --repo tonezzz/ada-voice` — 5 files, +572/-1.
- Until merge, Ada has no `map_embed` — correct and expected.
- After merge+deploy: `kind=static` returns an OSM image URL today;
  `kind=interactive` returns `needs_key` until the env drop + restart.

## lessons:

- A "done" kanban card can still have an unlanded deliverable — chaba
  drops are two-stage (stage in chaba → land in ada-voice via PR) and
  merge-sweep closes on the chaba merge only. Check the target repo,
  not just the card column.
- Staged `.patch` files in `integrations/ada-voice/` rot: count_cap
  bases go stale within days — bump the scalar manually per the
  README fallback instead of `git apply`.
- Board-api is not on dispatch-host loopback — use
  `https://idc03.taila0626a.ts.net:10000` (board-cli falls back to it
  automatically; bare curl needs `BOARD_API=` set).
- Answer-trust but verify: a "I dropped the key myself" board answer
  was checked by grep and the var was absent — env drops deserve the
  same verify-by-surface rule as service claims.
