# Dispatch outcome — sweep findings: report-graph standard applied

Card: `report-graph-standard` (KNB-0224) · runner: tony-omen
Commit: `6d41aaf04` on `dispatch/20261013-193828-sweep-findings-standard-to-app` (not pushed)

## What was already done (verified, not re-done)

- `unreachable` status + `offline_ok` + report-feed remote meta push — commit `90df7b8a`
- systemwide-assessment ada-side meta emit — `scripts/ada/cms-report-reflect.py` (commit `d6eead8b`) mirrors the `chaba-systemwide-assessment` CMS page into `reports/meta.systemwide-assessment.yml` via `chaba-cms-reflect.timer`; this IS the push-back contract for CMS-published reports
- overnight-assessment / http-health-audit probing retired idc01 — resolved by `idc01-ssot-cleanup` (KNB-0148, done 2026-10-07: probes retargeted to idc03, audits green 78/78)
- `audit-hosts/idc01` node retired in the registry (commented block, 2026-10-07)

## What this pass applied

1. **Status vocab finalized** — `status_enum` in `docs/ssot/infrastructure/ssot.reports.yml` now carries exactly the contract vocab: `ok|delta|error|stale|missing|unreachable|planned|remote|dormant`. `unreachable` documented as target-side (producer ran; its audit target didn't answer — producer crashes stay `error`). `dormant` added for arg-required/never-run generators. `untracked` demoted to `derived_statuses` — still emitted by `resolve_node` for artifacts-without-meta (legacy producers) but not producer vocabulary.
2. **Node hygiene** — `audit-hosts/idc01` removed from `fleet.children` (the retired node was still listed as a child, which would render as a phantom missing child in the L2 rollup).
3. **Contract documented** — new `contract:` section in ssot.reports.yml: `own_meta` (producers write meta; run-node augments with inputs_at/run_node_rc/pending-clear, never originates), `remote_pushback` (scp meta to served checkout; report-feed = reference impl; CMS reports use cms-report-reflect), `offline_ok`, `dormant`, `same_commit` (new timer/producer lands with node+meta together), `cadence_enforcement`, `consumer`.
4. **lib/report.py** — `STATUSES` gained `dormant`; `resolve_node` emits `dormant` for arg-required generators with no meta/artifacts, and meta now takes precedence over `observe:remote` so a pushed-back meta makes a remote producer observable (`remote` = "meta never arrived").
5. **report-watch.py (consumer)** —
   - Computes staleness itself: `meta.generated_at` older than node cadence → `stale`. Previously dead code — producers never write `stale`, so the stale flag could never fire.
   - Distinguishes `untracked` (artifacts, no meta — never flagged), `remote`, `planned`, `dormant` from `missing`.
   - Auto-heal: when a flag condition clears, the open `report-watch-*` inbox item is flipped to `focus.status: processed` with a `processed_reason` (covers node flags, overrun items, goal-rot items). Processed items no longer mute re-flagging — a healed node that rots again raises a new item.
   - `--json` (machine report per node + flagged/healed/probes), `--dry-run` (no writes anywhere — no inbox items, no heal flips, no requeue, no state.json), `--gate` (exit 1 while any node is flag-worthy). CI gate usage: `report-watch.py --json --dry-run --gate`.

## Verification

- `node scripts/ssot-validate-all.mjs` — ssot.reports.yml ✅ valid. (2 unrelated pre-existing YAML syntax errors in `docs/ssot/jobs/ada/2026-10-13-tony-lane-tool-profile.yml` and `docs/ssot/jobs/infrastructure/2026-10-13-omen-timer-pack-fixes.yml` — committed by other sessions, not touched here.)
- `report-watch.py --dry-run --json --gate` — clean JSON, exit 1 with 26 active flags on this satellite checkout (metas live on the tony-dell served checkout; `missing` there is expected — the kanban node note documents this).
- Isolated write-path test (INBOX/STATE redirected to a tempdir): run1 created flag items; run2 with a planted `ok` meta auto-healed the item (`status: processed` + reason); run3 after meta removal re-flagged a new item. Full flag→heal→reflag cycle verified.

## Follow-ups left on the board/next_steps

- The systemd unit `chaba-report-watch.service` runs `--quiet` — unchanged, compatible.
- `--gate` is available for CI wiring; nothing calls it yet (opt-in per the card spec's "optional").
- Pre-existing, unrelated: 2 job-file YAML syntax errors from other sessions (listed above) — worth a card if not already handled.
