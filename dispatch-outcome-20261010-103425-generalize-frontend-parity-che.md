# dispatch outcome — ha-release-pipeline (attempt 2)

## one-paragraph summary

Generalized the HA frontend parity check into a per-lane twin-diff engine and built a
single scripted promote engine behind per-lane wrappers. `frontend-parity-check.sh`
now takes a lane name (`tony`, `ada`, `michael`) or `--from/--to` and diffs six
scopes — Lovelace dashboards+views, resources, card-bundle md5s,
automations/scripts/scenes, helpers, users — with staging-guard artifacts
normalized out so they don't count as drift. `promote-lane.sh` (with
`promote-ada.sh`, rewritten `promote-tony.sh`, and converted `promote-michael.sh`
wrappers) does the full release sequence: parity diff before -> scoped writes with
`.promote-bak-<ts>` backups + atomic `.incoming` file swaps -> live reload -> parity
diff after, gated by `--confirm` per the existing release policy (refuses silently-
mutating prod; dry-run is the default safe mode). `promote-tony.sh` now defaults to
`tony-dev -> tony-ha` with a `--from michael-dev` compat path until `tony-dev` is
provisioned; `promote-ada.sh` does `ada-dev -> ada-ha`. All endpoints live in a new
registry (`ssot.home-assistant.lanes.yml`) — unprovisioned twins are detected and
fail cleanly with a pointer at the `ha-dev-instances` card. Verified live on the
real instances: full-scope parity `ada-ha <-> tony-ha` (correctly reports real
drift), remote `michael-dev (idc03) -> michael-ha` collection + dry-run,
rollback dry-run (no dev needed), confirm-gate refusal, and clean failure on the
unprovisioned `tony-dev`/`ada-dev`. No production writes were made.

## what changed

new files:
- `docs/ssot/infrastructure/ssot.home-assistant.lanes.yml` — lane + instance
  registry: 3 lanes (tony/ada/michael), 6 instances (prod+dev each), endpoints,
  config paths, ssh targets, auth method (token-env / token-file / refresh-token
  from `.storage/auth`), bundle_base, dashboard default, `planned:` flag for the
  two unprovisioned twins.
- `scripts/home-assistant/ha-lanes.sh` — shared lib sourced by everything:
  registry query (`lane_field`, `inst_field`), reachability (`inst_up`),
  token resolution incl. ada-style refresh-token exchange, remote/local file ops
  (`inst_cat`, `inst_put` — atomic via `.incoming` rename, `inst_sh`), and
  `inst_collect` (tar-pipe snapshot of `.storage` + www + yaml + packages).
- `scripts/home-assistant/ha-twin-diff.py` — parity engine over collected
  snapshots. Scopes: `dashboards` (registry + per-view config), `resources`
  (url-path-keyed, version query normalized), `bundle` (www/*.js md5),
  `automations` (+scripts+scenes+packages), `helpers` (input_* + counter/timer/
  schedule/group/tag storage), `users` (users/credentials/persons — compares
  identity metadata, never credential material). Normalizes staging-guard
  artifacts (injected `initial_state: false`, stubbed scripts, emptied scenes)
  and reports them as notes, not drift. `--json` + `--scope` + `--names` flags.
  Exit 0=parity / 1=drift / 2=collection error.
- `scripts/home-assistant/ha-config-merge.py` — destaging merge for yaml scopes:
  dev-wins per item by id, strips injected `initial_state: false`, drops stub
  scripts/scenes created by the actuation guard, `eq` subcommand for semantic
  comparison (avoids reserialization noise triggering false writes).
- `scripts/home-assistant/promote-lane.sh` — the promote engine. Flow:
  preflight (planned/unreachable detection) -> token resolution per needed scope
  -> collect both snapshots -> parity diff BEFORE -> confirm gate -> per-scope
  writes -> reload -> sleep 5 (`.storage` debounce) -> parity diff AFTER.
  Every file write is backed up as `<file>.promote-bak-<ts>` on prod; bundle and
  `.storage` writes are atomic renames. `--rollback` re-points the bundle
  resource at the previous `-vN` using only the prod side (works when dev is
  down). `--card` posts start/done evidence to the board.
- `scripts/home-assistant/promote-views.py` — websocket dashboard merge:
  replaces/adds named views by path into prod's lovelace config, preserves
  prod-only views, `--create` registers a missing dashboard, `--dry-run` prints
  the view add/replace list without writing.
- `scripts/home-assistant/promote-ada.sh` — thin wrapper: `ada-dev -> ada-ha`
  (default scope dashboards; bundle scope errors cleanly — ada lane has no
  bundle_base).
- `scripts/home-assistant/ws-resource-url.py` — restored from git history
  (commit b037ac08; was dropped by an earlier salvage restore, both old promote
  scripts referenced it). Bumps a lovelace resource url over websocket.

rewritten:
- `scripts/home-assistant/frontend-parity-check.sh` — now a wrapper over
  ha-lanes.sh + ha-twin-diff.py. New: `frontend-parity-check.sh <lane>`,
  `--from A --to B`, `--scope`, `--json`. Legacy no-arg mode preserved
  (michael-ha vs tony-ha, resources+bundle).
- `scripts/home-assistant/promote-tony.sh` — wrapper: `tony-dev -> tony-ha`,
  scope `dashboards,bundle`, dashboard `tony-test`. `--from michael-dev` compat
  documented in header until `tony-dev` exists.
- `scripts/home-assistant/promote-michael.sh` — wrapper: `michael-dev -> michael-ha`.
  Fixes stale bits wholesale: dev host was still `tony-dell` (migrated to idc03
  yesterday) and the bundle base had been renamed `sunsynk-power-flow-card-fork`
  -> `pfg3d-card` — both now registry-driven.

docs:
- `docs/ssot/infrastructure/ssot.home-assistant.howto.yml` — new
  `lane_release_pipeline` runbook (scope matrix, dry-run/confirm/rollback/
  restart recipes, backups) + superseded note on the old manual steps.
- `docs/ssot/infrastructure/ssot.release-lifecycle.yml` — gates s2/s4 now name
  the real commands; gaps updated (scripts exist, blocked only by unprovisioned
  twins + first real promote).
- `docs/ssot/jobs/home-assistant/2026-10-10-lane-release-pipeline.yml` — job
  record with verify evidence and rollback recipe.
- `AGENTS.md` — promote commands updated to per-lane wrappers; michael-dev
  restart line now points at idc03.

## verified (all dry-run, no prod writes)

- `frontend-parity-check.sh --from tony-ha --to ada-ha` full scope -> real drift
  reported across dashboards/resources/bundle/automations; helpers+users parity.
  exit 1.
- `frontend-parity-check.sh` (legacy no-arg) -> resources+bundle diff works.
- `promote-michael.sh --dry-run --views tpl` -> remote collection over ssh to
  idc03 and michael-ha, view-merge plan (`replace tpl, keep 10 prod-only views`),
  bundle plan `v240 -> v214`. exit 0.
- `promote-lane.sh --from ada-ha --to tony-ha --scope automations --dry-run` ->
  semantic merge plan, no semantic-change files skipped.
- `--scope users --dry-run` -> warns "all prod sessions/tokens become dev's".
- no `--confirm` -> `REFUSING prod writes without --confirm`, exit 1, zero writes.
- `promote-michael.sh --rollback --dry-run` -> `michael-ha v214 -> v213`, dev not
  required.
- unprovisioned `tony-dev`/`ada-dev` -> `registered but not provisioned yet
  (card ha-dev-instances)`, exit 1.
- `ha-config-merge.py` unit-verified on synthetic staging artifacts (strips
  injected `initial_state`, skips stub scripts/scenes).
- bash -n clean on all scripts; py3 compiles; lanes.yml parses.

## how to verify / use

```bash
scripts/home-assistant/frontend-parity-check.sh tony        # tony-dev vs tony-ha
scripts/home-assistant/frontend-parity-check.sh --from tony-ha --to ada-ha
scripts/home-assistant/promote-tony.sh --dry-run            # fails cleanly until tony-dev exists
scripts/home-assistant/promote-tony.sh --from michael-dev --to tony-ha --dry-run
scripts/home-assistant/promote-ada.sh --scope dashboards --dry-run
# real promote (requires explicit same-session approval):
scripts/home-assistant/promote-tony.sh --scope bundle --confirm --card ha-release-pipeline
# rollback a bundle bump:
scripts/home-assistant/promote-michael.sh --rollback --confirm
# .storage scopes (helpers/users) need a restart to load:
scripts/home-assistant/promote-tony.sh --scope helpers --confirm --restart
```

Every write leaves `<file>.promote-bak-<ts>` next to itself on prod; rollback for
yaml/.storage scopes = restore that file + reload/restart. Documented in
`ssot.home-assistant.howto.yml` runbook `lane_release_pipeline`.

## notes / remaining

- `tony-dev` (:8127) and `ada-dev` (:8128) are registered but not provisioned —
  blocked by `ha-dev-instances` (which `ha-staging-actuation-guard`, now done,
  unblocks). Until then the lane default fails fast and `--from` overrides work.
- First real `--confirm` run should record parity-before/after on the card
  (script does `--card` automatically).
- No commit/push per dispatch rules.
- Pre-existing (not mine): `docs/ssot/jobs/vcast/2026-10-10-gev-yt-local-media-
  failures.yml` fails ssot-validate.

## lessons:
- `set -e` inside a bash function called as `"fn" || die` is fully suppressed — `[ cond ] && cmd` as a last line silently exits 1 on real work; end every scope function with `return 0`.
- `ssh host sh -c 'script'` re-parses quoting remotely; pass args with `printf %q` and keep multi-line scripts on stdin or pre-expanded.
- HA `.storage` writes are debounced — wait ~5s before re-collecting for a parity-after diff.
- Production file pushes should stage to `<file>.incoming` then `mv` — a partial scp of `.storage/auth` or a card bundle is a corrupt prod.
- `grep -oP` + pipefail: pipelines like `cmd | head` exit 141 (SIGPIPE) under `set -o pipefail`; read the tail or `|| true` deliberately.
