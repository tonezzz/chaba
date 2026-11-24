# Dispatch outcome — ada-ha chaba-admin live-view drift (read-only evidence)

- card: `ada-ha-dashboard-live-view-drift` (ref HOM-0015)
- branch: `dispatch/20261124-212619-read-only-evidence-from-2026-1` — committed, **not pushed** (dispatcher merge path)
- host: idc02 (dispatch worktree); live evidence read via `ssh tony-omen` (read-only `cat`)

## Verdict

**Ada Control stays absent. The live 19-view set is correct and the repo
snapshot/SSOT are now verified in sync — nothing was restored, nothing was
mutated.**

## What the evidence shows

Live readback today (2026-11-24): `lovelace.chaba_admin` on tony-omen,
sanulated through `sync-ada-ha-chaba-admin.py`'s own extractor/sanitizer,
is **byte-identical** to
`docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` — 19 views:
Pair, Kanban, Kanban 2, Diagram, OpenChamber (ada-ocb), Ada Code (ada-code),
Cline, Node-RED, DevNest, Wiki, Private Wiki, Ada Pages, Monitor, Hosts,
Services, Events, Log, Obsidian, Gantt.

History of the "Ada Control" view (path `ada-control`,
`custom:ada-voice-card` + `custom:ada-activity-card` panel):

- **2026-11-04** `43a72beaaf` — added as an iframe to
  `chaba-home/ai` in the post-Board "control-plane" slot (card
  `opencode-ada-ha-tab-standard`, Tony picked option B).
- **2026-11-08** `33380aa02b` — reshaped to native voice/activity cards
  during the same live-edit batch that renamed Board→Kanban, added Ada Code
  and Node-RED.
- Present in every snapshot through `fc69519a88` (2026-11-18 21:07, which
  also already had Hosts + Services — the card spec's "not Hosts/Services"
  phrasing is inaccurate).
- **Gone from live** by 2026-11-20 ~12:00 (first captured absent in sync
  `943d7895b9`). The removal window is 2026-11-18 21:07 → 2026-11-20 ~12:00.
  No agent/dispatch/card claims it; HA storage-mode dashboard edits are not
  audit-logged (`.storage/` is gitignored on tony-omen, HA log has no
  per-save entries). Most consistent with a **manual HA UI edit** during
  the same Nov-18-evening hands-on session that added the Hosts/Services
  tabs — those snapshot commits were surgical +12-line inserts by Tony,
  not full `sync-ssot-from-live.sh` rewrites, so the snapshot could stay
  stale w.r.t. live in that window.
- **Kanban2 cleared**: `mutate-ada-ha-kanban2-tab.py` only retitles/re-URLs
  the `path==kanban` view and inserts one `kanban2` view — it has no code
  path that removes views; the session's own readback confirmed the other
  17 views unchanged.

## Decision basis

The card's board request was already answered (2026-11-20): *"Keep current
live views (recommended). Do not restore Ada Control now; reconcile the repo
snapshot/dashboard state to the current live view set unless explicitly
requested later after card resources are verified."* This run confirms that
answer is safe: the same voice+activity pair remains the canonical Ada
surface on ada-ha `chaba-home`/`ai` and `chaba-ai`, `/local/ada-voice-card.js?v=14`
is still registered in `lovelace_resources` (restoration would be trivial if
ever explicitly requested), and no card or session ever asked for its
return. Per spec, no custom cards were restored and no live mutation was
made.

## What changed (this branch)

- `docs/ssot/infrastructure/ssot.home-assistant.dashboards.yml` —
  `chaba_admin_ada` note now records the investigation result, the
  keep-live decision, and the 2026-11-24 byte-identical verification.
- `docs/ssot/jobs/home-assistant/2026-11-24-ada-ha-chaba-admin-view-drift.yml` —
  full timeline/findings/verification trail.
- Snapshot JSON needed **no change** — it already matched live.

## How to verify

- `ssh tony-omen "cat /home/tony/.config/ada-ha/.storage/lovelace.chaba_admin"`
  → run through `extract_dashboard_config` + `sanitize_snapshot` from
  `scripts/home-assistant/sync-ada-ha-chaba-admin.py` → diff against
  `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json`
  (identical as of this run).
- `git log -S 'Ada Control' -- docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json`
  reproduces the whole view-history table above.
- `python3 -m pytest tests/test_ada_ha_dashboard_snapshot.py` — 4 passed.
- `python3 scripts/ssot-prose-smell.py` — 0 flagged.

lessons:
- Surgical snapshot edits (insert one view block by hand) break the
  "snapshot == live" invariant silently — the ada-ha hosts/services commits
  on 2026-11-18 were +12-line inserts, not sync-ssot-from-live.sh rewrites,
  which is exactly how this drift stayed invisible for two days.
- HA storage-mode lovelace edits leave no audit trail: `.storage/` is
  gitignored and home-assistant.log has no per-save entries — when a
  dashboard view vanishes, git history of the snapshot + card comms are
  the only evidence; bound the window by last-good/first-bad syncs.
- The kanban2 drift scare was a false attribution: read the mutator script
  before assuming a WebSocket mutation dropped sibling views — it only
  inserts.
