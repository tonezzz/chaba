# Dispatch outcome — board-diagram-lanes-view (2026-11-27 14:19)

## What changed

Commits on `dispatch/20261127-141928-prototype-already-exists-uncom` (pushed via `scripts/git-safe-push.sh`):

- `df098af67e3` — board-diagram: fix gantt import rename + add /action control panel
- `1bab957f1bb` — docs: job record (`docs/ssot/jobs/board/2026-11-27-board-diagram-control.yml`)

Files touched: `stacks/web/public/apps/board-diagram/{index.html, js/app.js, js/diagram.js}` only.

## State found (important — the card spec was stale)

The "uncommitted prototype" was already **committed to master on 2026-11-10** (`703041d99b0`, `31ec26dd1f7`) and fully wired: ssot.routes.yml route, Caddyfile `handle_path` block, `routes.json` entry, static files already rsynced to `~/web-srv/public/apps/board-diagram/` on idc02, and the **HA chaba-admin dashboard already had the Diagram tab** (live-verified on tony-omen: `views[3]` after kanban/Kanban 2, Gantt at `views[17]` after Obsidian — exactly Tony's 2026-11-09 order). No push-dashboard.py run was needed; the repo snapshot `ada-ha-chaba-admin-current.json` matches live.

The page was nevertheless **dead in the browser**: board-gantt renamed `groupOf` → `groupIdOf` on 2026-11-24 (`7c3cd799fa3`) and `diagram.js` still imported `groupOf` — the ES-module instantiation threw, so "loading…" never resolved. That is the real fix in this dispatch.

## What I did

1. **Import fix** — `diagram.js` now imports `groupIdOf` (verified it is the export groups.js actually provides); `buildLanes` uses it.
2. **CONTROL** — per-node action panel + per-lane batch claim, all posting to `board-api /action`:
   - Node click → panel (replaces the old hover-follow info popup): **▶ claim** (`do:claim`, `host:'tony'`, client-gated on `action.status=queued` and non-manual lane/executor/type), **move** `<select>` (`do:move`, columns = board-api `COLUMNS` — `lab` excluded because `do_move` refuses it), **✓ finish** (`do:finish host:tony ok:true` when the card is running-by-tony, else `do:close` — the merge-guarded human close, same as board2).
   - Lane head shows **claim n** when the lane holds queued cards → confirm → sequential `do:claim` per card.
   - Auth identical to board2: same-origin `fetch POST /apps/board-api/action`, 60 s timeout; the edge injects `Tailscale-User-Login` (tailnet) or `X-Board-Edge-Key` (CF-Access vhost → `edge:<cf-email>`). No credentials in JS.
3. **Verification** —
   - Node smoke test (`/tmp/bd-smoke`, `type:module`): `buildLanes` over the live `cards.json` (658 cards) → `members` lane with the 5 in-scope adobe-stock cards (3 done / 2 doing); imports resolve.
   - Headless Chrome `--dump-dom` against a symlinked worktree tree + real `cards.json`: status "Adobe Stock — lanes · 5 cards · 210px", 5 `.node.col-*` nodes, lane count, legend — zero JS errors.
   - Write path: `POST /action` on the idc03 tailnet front passes auth (verb/card validation answered); public edge injects the edge key — same path board2 writes through.
   - `render-routes.py --check`: board-diagram route valid; routes.json already contained it — **no regen needed**.

## Result / pending

- Pushed; **deploy is pending the dispatch merge** — merge-sweep lands the branch (~15 min cadence post-session), then idc03 `chaba-repo-sync` → idc02 `web-srv-sync` carries `stacks/web/public/apps/board-diagram/` to the `:8099` mirror and idc03's edge automatically. No hand-copy to `~/web-srv/public` (rsync target, not a source — board-static-deploy.md).
- Live verify after merge: `https://tony-ha.surf-thailand.com/apps/board-diagram/` (CF Access) and the chaba-admin **Diagram** tab on ada-ha.

## How to verify

- Repo: `git log --oneline origin/master -- stacks/web/public/apps/board-diagram/` after merge.
- Page: open `/apps/board-diagram/` → expect "5 cards" status (adobe-stock group is thin — only 5 alias-matched cards; zero `project:` slugs exist in cards.json yet, so everything sits in `members` until the project-slug convention is adopted).
- Controls: click a node → claim/move/finish panel; lane head `claim n` appears only when queued cards exist.

## lessons

- Cross-app ES-module imports under `stacks/web/public/apps/` break silently on export renames — grep importers whenever board-gantt/board2 js exports change (`groupOf`→`groupIdOf` killed this page for 3 days).
- Compact `cards.json` (KNB-1302) drops `project`/`program`/`brief` on most cards — project-grouped views degenerate to alias groups + `members` lanes until `project:<slug>` adoption lands.
- board-api `COLUMNS` excludes `lab` — move UIs must not offer it (`do_move` 400s); lab has its own promote/retire flow.
- board-api error bodies are `{"error": …}` without `ok:false` — check `j.ok === true` for success.
- The prototype was already committed+deployed+tabbed since Nov 10 — the card spec described a stale "uncommitted" state; verify real state before re-doing work.
