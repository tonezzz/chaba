# dispatch-outcome — ops-manual-command-api-mcp-efficiency-followups

Card: `ops-manual-command-api-mcp-efficiency-followups` (parent audit
AUD-1033 `ops-manual-command-api-mcp-efficiency-audit`, request
`gated-follow-ups-from-aud-1033-which-to-8d37ba` — Tony approved all
three). Commit `bfb288744f` on `dispatch/20261124-190507-parent-ops-manual-command-api-`.
Job trail: `docs/ssot/jobs/devnest/2026-11-24-mcp-efficiency-followups.yml`.

## What changed

### 1. Runner-agent claim-poll read projection (env-gated)
`scripts/board/runner-agent.py` — `claim_pass` + `verdict_pass` (the
only two `/cards` readers in the claim-poll pair) now read through
`_cards_read()`: legacy `GET /cards` by default, paginated
`GET /cards?fields=<CARDS_FIELDS>&limit=1000&offset=` when
`RUNNER_CARDS_PROJECTION=1`. Field set covers everything the claim path
touches; `comms` is excluded and resolved lazily per ledger-held card
via `/card/<id>?fields=comms` (`_card_comms`, memoized per pass).
Unknown comms (fetch failure) returns `None` — `retry_gate` treats it
as neither a forgive signal nor a baseline write, so a flaky projection
can never forge a re-arm delta. All other passes keep legacy reads.
Fallback/rollback: flag defaults OFF; unset = byte-identical old path.

Proof: `tests/board/test_runner_agent_projection.py` (17 tests —
URL shape, unknown-comms gate, static claim-path field audit, real-
corpus parity through a claim+verdict cycle) + live soak
`scripts/board/cards_projection_soak.py`: **12/12 polls parity-clean**,
full dump ~12.74 MB/poll vs projected field set; live board churn
(719→720 cards) confirmed non-issue via fresh `/card/<id>` confirm.

### 2. Scoped host_snapshot mcp_debug preset + catalog note
The Aug refactor dropped the inline `presets:` block and the split
`ssot.mcp-debug.presets.yml` was never created — `PRESETS` has been
empty since. Restored the intended split file
(`docs/ssot/infrastructure/ssot.mcp-debug.presets.yml`) with an
explicit `policy.step_tools` block; `scripts/mcp_debug/config.py`
merges inline + split (split wins). First preset `host-snapshot`:
four `mcp_raw` steps running `host_snapshot.py` on every configured
host — **verified live**: `mcp_preset_run('host-snapshot')` returned
ok:true with valid contract JSON (`read_only:true`) from all 4 hosts.
Catalog notes updated in `ssot.mcp-debug.yml` (presets extension +
related_files), `ssot.token-tools.yml` (AUD-1033 section), registry
entry added. **No global tool-surface expansion**: presets are bundles
of existing tool calls; `tests/test_mcp_debug_presets.py` (12 tests)
pins dispatchable/declared step tools, allowlisted raw bases, and that
no lane profile allows `mcp_preset_run`.

### 3. storage_probe.py S2 job-pack + deterministic verifier
`scripts/devnest/storage_probe.py` — read-only job-pack emitting the
storage-dryrun contract: walks declared `scan_roots` (bounded), builds
the directory-size table (per-root + per-candidate bytes + summary),
classifies every candidate through the same
`opencode_profiles.classify_candidate` + profile policy the held-out
verifier enforces (protected-fragment checks structural). Emits
`deletions: []`, `dry_run: true` unconditionally; no
unlink/rename/write path exists (proven structurally + functionally in
tests). `verify` subcommand re-checks an artifact deterministically —
same rules as `fixture/verify.py`, policy re-derived from the profile.
Wired into the storage-dryrun profile bash allowlist
(`python3 scripts/devnest/storage_probe.py*`) + prompt FAST PATH.
Live run vs committed fixture: 11 candidates / 7 refused, verify pass —
1.6 MB automatic_ok vs 625 MB refused (go/pkg/mod, gods-eye-view).

## Verification

- `tests/board/test_runner_agent_projection.py` — 17 pass
- `tests/test_mcp_debug_presets.py` — 12 pass
- `tests/devnest/test_storage_probe.py` — 17 pass
- `tests/devnest` suite — 353 pass, 1 pre-existing failure
  (`test_lane_gate Admit.test_s1_requires_opencode_lanes_env` — fails
  identically at HEAD, unrelated)
- `tests/board` suite — 973 pass; 5 failures all pre-existing at HEAD
  (4× `test_control_pane_projection` missing generated files, verified
  via clean worktree) except `test_runner_tooling_contract` pin which
  WAS caused by the runner-agent change — fixed by bumping
  `runner_agent` sha256 in `scripts/devin/runner-tooling.manifest.json`
  (same commit, as the contract requires)
- Live: mcp preset run (4/4 hosts), storage probe scan+verify, cards
  soak 12/12

## How to verify / enable

- Projection: set `RUNNER_CARDS_PROJECTION=1` in the runner unit env
  after merge (normal deploy gate); soak script rerunnable anytime.
- Preset: `mcp_preset_run("host-snapshot")` on any full-surface MCP
  client.
- Probe: `python3 scripts/devnest/storage_probe.py scan` /
  `... verify artifact.json`.

No production rollout performed; every item preserves fallback.

lessons:
- runner-agent.py is content-pinned in scripts/devin/runner-tooling.manifest.json — any edit MUST bump the sha256 in the same commit or test_runner_tooling_contract fails.
- mcp-debug presets were silently empty: the Aug refactor removed the inline `presets:` block intending a split file that was never created — check `config.PRESETS` before assuming the surface exists.
- JSON rewrites of pinned/hand-formatted files create diff noise — edit manifest-style files surgically (string replace), not json.dump.
- Live-board soak diffs need a fresh /card/<id> confirm step — bare full-vs-projected comparison false-positives on normal card churn.
