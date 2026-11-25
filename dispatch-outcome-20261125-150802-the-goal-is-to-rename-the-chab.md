# Dispatch outcome — chaba-admin kanban tab lowercase rename + runner fleet verify

Card: `chaba-admin-kanban-tab-rename-lowercase`
Branch: `dispatch/20261125-150802-the-goal-is-to-rename-the-chab` (pushed)
Host: tony-dell worktree

## Done-condition — VERIFIED

- Live `lovelace.chaba_admin` on ada-ha (tony-omen:8125, url_path `chaba-admin`):
  `views[path=kanban].title` changed `"Kanban"` → `"kanban"` via
  `push-dashboard.py --mutate scripts/home-assistant/mutate-ada-ha-kanban-tab-lowercase.py`
  (new mutator, committed). Websocket readback confirms `kanban` lowercase;
  `kanban2`/"Kanban 2" and all other views untouched.
- `sync-ssot-from-live.sh --instance ada-ha` resynced:
  `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` (one-line
  title diff, secrets still redacted), chaba-home snapshot unchanged,
  `ssot.home-assistant.dashboards.yml` `last_verified` → 2026-11-25.
- Commit `87bd3c7947c` pushed to origin. Job trail:
  `docs/ssot/jobs/kanban/2026-11-25-runner-fleet-sync-kanban-tab-rename.yml`.

## Runner-agent fleet constraint — VERIFIED

Canonical build: sha256 `1514c75c…` (= manifest pin + exec-checkout copy).
Audited `~/.local/bin/runner-agent` AND the repos.conf/dr-module checkout ref
on all 8 fleet hosts. All now match.

- tony-dell, tony-omen, idc02, idc03, mn01, con01: already clean.
- **tony-macbook — repaired**: 6 zero-byte loose objects + one broken ref
  (`dispatch/20261125-092906-…`, tip `7f5e579fe` never pushed) were failing
  every fetch. Deleted empty objects + the dead ref, fetched origin,
  `git-safe-pull.sh` → origin/master. runner-agent.py now canonical.
  Residual: 106 pre-existing dirty focus-inbox files preserved by
  autostash; orphaned worktree dir `dispatch-wt-20261125-092906-*` left on
  disk (session residue, branch ref deleted).
- **kk-mac — repaired**: shallow clone 6 days stale AND its GitHub deploy
  key `id_chaba_deploy` is absent from the repo's deploy keys (OPS-0220
  enrolled it 2026-11-19; gone now) → no fetch possible. Also added missing
  github.com known_hosts entry. Healed by fetching a full-history bundle of
  origin/master (239MB, built on tony-dell) then `merge --ff-only` +
  removed `.git/shallow` (repo now complete at `53d811b6988`).
  runner-agent.py now canonical.

## Findings needing Tony

1. **kk-mac deploy key missing on GitHub** — checkout cannot self-update;
   drift deferrals will return within days. Fix: re-add deploy key
   (`gh repo deploy-key add -R tonezzz/chaba` with kk-mac's
   `~/.ssh/id_chaba_deploy.pub`) — credential change, left for Tony.
2. **idc02 `~/CascadeProjects/chaba-tony-dell`** holds a stale
   runner-agent.py (`adfa0c57…`) — unreferenced legacy checkout, not the
   drift ref; harmless but worth pruning eventually.
3. tony-macbook worktree residue noted above.

lessons:
- runner-agent drift = installed snapshot vs the host's CHECKOUT ref file —
  a current ~/.local/bin copy still declines when the checkout is stale; audit both shas.
- Shallow clones reject thin bundles (prerequisites below the cut); a
  full-history bundle fetch + `rm .git/shallow` heals without remote auth.
- `find .git/objects -type f -size 0` + for-each-ref/cat-file -e finds the
  corrupt-object + broken-ref pair that fails every fetch with "bad object".
