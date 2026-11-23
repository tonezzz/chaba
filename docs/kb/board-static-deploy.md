# Deploying board / board2 static UI changes (standard procedure)

Invariant: **`/home/tony/web-srv/public/` is an rsync target, not a source.**
Never edit or copy files there by hand — `web-srv-sync.service` overwrites
the tree every 15 minutes (`:00/:15/:30/:45`) from idc03. A manual destination
write looks correct until the next sync, then silently disappears
(2026-11-19 control-pane incident).

## Topology (fixed 2026-11-07, see `infrastructure/ssot.routes.yml`)

- **Source of truth:** `chaba` repo, committed + pushed with
  `scripts/git-safe-push.sh`.
- **Canonical writer:** idc03, `~/CascadeProjects/chaba-tony-dell`, pulled by
  `chaba-repo-sync.timer`. board-api and `chaba-board-render.timer` render
  `index.html` + `cards.json` into its `stacks/web/public/apps/board2/`.
  `cards.json` is gitignored — it never travels by git pull.
- **Publish:** idc03 caddy-edge mounts that tree directly (canonical).
  idc02's public edge proxies to a local `:8099` mirror fed by
  `web-srv-sync.timer` rsyncing from idc03.

## idc02 `web-srv-sync.service`: cards-only `--delete`

The two broad rsyncs in this host-local unit deliberately have no `--delete`:
they preserve local-only artifacts (`.local-conflict-*`, `.tmp`, HA/report
files) that do not exist on idc03. One subtree is the exception —
`docs/ssot/kanban/cards/` legitimately **shrinks** at the source, since
`archive-done.py` moves cards into `cards/archive/` on the daily sweep. Without
a scoped prune the mirror keeps a duplicate active copy of every archived card
(1,355 stale files after the 2026-11-23 retention pass). The unit therefore has
a third `ExecStart` after the broad rsyncs:

```sh
rsync -az --delete --timeout=120 \
  idc03:~/CascadeProjects/chaba-tony-dell/docs/ssot/kanban/cards/ \
  %h/web-srv/docs/ssot/kanban/cards/
```

If `web-srv-sync.service` is regenerated from a template or idc02 is rebuilt,
**re-apply this line** — it is host-local config, not in the repo. Do not add
`--delete` to the broad `public/` or `docs/` rsyncs. Verify after a sync with
`find ~/web-srv/docs/ssot/kanban/cards -maxdepth 1 -name '*.yml' | wc -l`
(should match the active count on idc03) and a dry-run residual check:

```sh
rsync -az --dry-run --delete --itemize-changes \
  idc03:~/CascadeProjects/chaba-tony-dell/docs/ssot/kanban/cards/ \
  ~/web-srv/docs/ssot/kanban/cards/ | grep -c '^\*deleting'   # expect 0
```

## Steps

1. Change source only: `scripts/render-board2.py`, `scripts/board/board-api.py`,
   tests, docs. Never edit generated `index.html`/`cards.json` in any checkout.
2. Run affected tests (e.g. `pytest tests/board -q`), then commit a **scoped**
   change and push: `scripts/git-safe-push.sh` (it handles push races via
   safe-pull). Don't mix unrelated staged work into the commit.
3. Wait for `chaba-repo-sync.timer` on idc03, or run
   `ssh idc03 'systemctl --user start chaba-repo-sync.service'`. Confirm the
   commit is in idc03's HEAD and its source file carries the change.
4. Wait for `chaba-board-render.timer` (~60 s), or run
   `ssh idc03 'systemctl --user start chaba-board-render.service'`. Confirm the
   generated `board2/index.html` contains the expected marker.
5. On idc02, trigger `systemctl --user start web-srv-sync.service`. Its
   `ExecStartPost` runs `scripts/board/deploy-check.sh`, which compares the
   canonical and served artifacts and checks the live HTTP page; a mismatch
   logs a warning (the unit ignores the check's exit code).
6. Run `scripts/board/deploy-check.sh` yourself and, for UI work, do a browser
   smoke test of `/apps/board2/`. Only then say it is deployed.

## Rollback

Revert the source commit, push, and repeat steps 3-5. To inspect the previous
rendered page without touching the served tree, serve the checkout's
generated directory on a temporary local port.

## Known gaps

- Propagation to the idc02 mirror is up to 15 minutes without step 5.
- The nested `board2/board2/` stale copy exists in both trees (old ad-hoc
  deploy); remove it from the idc03 canonical tree, not just the mirror.
