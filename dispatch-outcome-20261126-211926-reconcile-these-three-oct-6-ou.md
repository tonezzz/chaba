# dispatch-outcome — reconcile unlanded Oct 6 artifacts (audit-miss-unlanded-oct06-dispatch-artifacts)

## Result: DONE — 1 artifact salvaged and landed on master; 2 documented as redundant

All work happened on tony-dell. Sources read read-only from the frozen
`~/CascadeProjects/chaba-tony-dell` mirror (never edited/cleaned, per spec).

## Per-artifact reconciliation

### 1. `dispatch-outcome-20261006-101400-verify-after-act-for-gev-casts.md` — NOT salvaged (redundant)

Every declared deliverable is already on `origin/master`:

- `stacks/web/input-bridge/gev-cast-verify.mjs` ✓
- `docs/runbooks/vcast-gev-verify-after-act.md` ✓ (14/14 PASS recorded in front-matter)
- `docs/ssot/jobs/gev/2026-10-06-gev-cast-verify-after-act.yml` ✓
- `docs/ssot/ssot.runbooks.yml` registry entry ✓
- `docs/ssot/apps/ssot.apps.gev.yml` verify-after-act requirement ✓
- `docs/ssot/apps/ssot.apps.vcast.yml` Testing entry ✓

Commit `e7c564f2` itself is not an ancestor of master, but its content
landed via a later merge (diff vs master = only the `ada-pi`→`ada-voice`
rename). Archived cards `verify-after-act` (OPS-0022) and `gev-screens`
(MED-0126) record the outcome. The MD's only unique content was a
point-in-time deploy-drift note (vcast sw.js v2-vs-v3, Oct 6) — stale
7 weeks later. Superseded.

### 2. `dispatch-outcome-20261006-103616-inventory-remaining-hardcoded-.md` — NOT salvaged (summary)

A narrative summary of the inventory whose substance lives in the YAML
below (same `stale_broken_now` findings, same phased plan). The archived
card `service-name-indirection` (OPS-0124, column done) already carries
the outcome in comms. Landing the MD would duplicate the YAML.

### 3. `ddocs/ssot/jobs/infrastructure/2026-10-06-tailnet-ip-indirection-inventory.yml` — SALVAGED, landed

Unique 20KB per-file migration inventory (class a/b/c + keep-literal +
exempt, stale-broken-now list, 5-phase plan). Still useful: `svc.internal`
aliases still do not exist on master, so the migration plan remains open
work; the file is a jobs/ historical record, not stale config.

It was untracked under a typo'd `ddocs/` dir on the frozen mirror.
Prior dispatch (2026-11-20) had already restored it to the canonical path
on branch `salvage/aud020-tailnet-ip-inventory` → **PR #196**, adding a
`historical_followup` block correcting the "retired idc01" framing
(idc01 = warm-DR per 2026-10-09 sweep). PR was held because required
`validate` CI failed.

**What I did:**

1. Confirmed the 4 missing-title files that failed CI on 2026-11-20 now
   have `title:` on master → used GitHub `update-branch` to merge master
   into the PR head (2e0a217c).
2. CI failed again — different cause: `ssot-optimize-gate` flagged 2 NEW
   warnings vs baseline, both pre-existing master debt unrelated to the
   PR (`opencode-lane-regraduation` request missing `suggested`;
   `ops-kanban-commit-guard` review card missing `review_kind`). Master
   CI was red for the same reason.
3. Refreshed `reports/SSOT_OPTIMIZATION_WARNINGS.json` baseline on the
   salvage branch via full `node scripts/ssot-optimize.mjs` run (the
   gate's documented accept path; warnings remain listed as debt).
   Committed as `0afe6b37768`, pushed fast-forward.
4. `validate` went green (run 45841938231) → **merged PR #196 squash,
   merge commit `1a918af1b81` on master, branch deleted.**

Verified: `git ls-tree origin/master` shows
`docs/ssot/jobs/infrastructure/2026-10-06-tailnet-ip-indirection-inventory.yml`,
md5-identical to the mirror `ddocs/` content + `historical_followup`.

## Exclusions confirmed

- `2026-10-05-ha-michael-worktree-sync-verify-addendum.yml`: exists
  untracked in BOTH `ddocs/` and `docs/` on the mirror, absent on master.
  Its `additional_findings` are transient 2026-10-05 state observations
  about the `chaba-tony-dell` clone (mid-rebase, diverged lanes) — that
  checkout is now the frozen pull-only mirror, so the open_items are
  moot. Primary job + audit report already on master. Excluded per spec.
- `ada-dead-turn-guard` card: tracked at
  `docs/ssot/kanban/cards/archive/ada-dead-turn-guard.yml` — not a miss.

## Out-of-scope observation

The mirror has 4 more untracked `dispatch-outcome-*.md` files not on
master (disk-trend-watcher Oct 5; gods-eye-view ×2 + vms-native-capture
Oct 6) tied to other archived cards — presumably covered by other
audit-miss cards; flagged in card comms, not actioned here.

## How to verify

```bash
git ls-tree origin/master -- docs/ssot/jobs/infrastructure/2026-10-06-tailnet-ip-indirection-inventory.yml
gh pr view 196 --repo tonezzz/chaba --json state,mergeCommit
```

Frozen mirror untouched: `git -C ~/CascadeProjects/chaba-tony-dell status`
still shows the same `??` entries.

lessons:
- GitHub `update-branch` (PUT /pulls/N/update-branch) refreshes a stale PR head server-side — no local checkout needed; the 2026-11-20 missing-title CI failure was already fixed on master.
- `ssot-optimize-gate` fails PRs on warnings absent from `reports/SSOT_OPTIMIZATION_WARNINGS.json` baseline — when the 2 flagged warnings are pre-existing master debt, a full `node scripts/ssot-optimize.mjs` run + commit of the baseline is the sanctioned unblock (and heals master's own red gate on merge).
- Dispatch outcome docs do NOT need a push: merge-sweep fetches the worktree HEAD directly from the runner — commit on the dispatch branch and leave the worktree clean.
- Mirror `ddocs/` (double-d) is a typo'd untracked dir — canonical path is `docs/`; always diff mirror `ddocs/` content into `docs/` when salvaging.
