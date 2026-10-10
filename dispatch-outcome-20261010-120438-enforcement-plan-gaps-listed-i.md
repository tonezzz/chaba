# dispatch outcome — release-lifecycle-standard (enforcement, attempt 2)

**Result: done — all six gap items implemented in the worktree; checker +
smoke verified; no prod writes, no deploys.**

## What landed

- **Tag convention + opt-in** (`ssot.release-lifecycle.yml` new
  `evidence_convention:` section; `ssot.kanban.yml` card_schema): a card
  joins the lifecycle via a truthy `release:` field (convention: lane
  name). Stage evidence = comms tags `[exp] [alpha] [beta] [smoke] [rc]
  [prod]` anywhere in comms text. Opt-in means zero disruption to
  non-release cards.
- **`scripts/ada/lifecycle-check.py`** (new) — reads bars from the
  standard; runs inside `kanban-sync.sh` on the sync worktree. Review
  cards missing `[exp]`/`[alpha]` and done cards missing any tag or the
  soak bar bounce to `doing` with a comms note naming the missing gate.
  First sight of a release card in review stamps `soak_until` (entry +
  `bars.beta.soak_hours`) — that's the soak timer. `--gate <card.yml>
  --stage review|preprod|done` is a read-only mode (exit 0/1/2 + JSON).
- **Per-lane parity** — already landed via ha-release-pipeline
  (`frontend-parity-check.sh <lane>` generalized); the standard's gaps
  list now reflects it as deployed.
- **Beta soak** — `soak_until` card field documented in
  `ssot.kanban.yml`; satisfied when reached OR a `[beta]` comms cites
  >= `sessions_min` sessions. Enforced at both `--gate preprod`
  (promotion) and `done` (close).
- **Post-deploy smoke inside promote-lane.sh** — after the parity-after
  diff: prod `/api/` 200 + parity-after rc==0 + bundle 200. PASS posts
  `[prod]` comms; FAIL exits 1 with rollback hint and posts `[prod] FAIL`.
  `[rc]` evidence (parity-before + rollback recipe) posts after the
  `--confirm` gate — well inside the 30-min bar.
- **Dev-twin playlive gate** — `scripts/home-assistant/dev-twin-smoke.py`
  (new): playwright-headless session on playlived, token injection via
  `hassTokens` (env/file/refresh auth from `ssot.home-assistant.lanes.yml`,
  `--inst X --url Y` override for tailnet-vs-loopback cases), DOM probes
  for HA shell + rendered cards + login-form detection, `--views` per-view
  checks, screenshot + JSON verdict in `reports/dev-twin-smoke/` (gitignored),
  `[smoke]` comms to `--card`. promote-lane.sh **refuses** a confirmed
  promote on a release card without `[smoke]` evidence + satisfied soak —
  no dev-twin playlive evidence, no promotion.
- Docs: `lane_release_pipeline` runbook updated; AGENTS.md promote/tag
  bullets; job record `docs/ssot/jobs/kanban/2026-10-10-release-lifecycle-enforcement.yml`.

## Verified

- lifecycle-check.py on a synthetic 6-card dir: all bounce/stay/stamp
  paths correct incl. the `>=3 sessions` alternative bar (found + fixed a
  regex gap where "4 real sessions" didn't match). Second pass idempotent.
- `--gate` mode: missing → rc 1 + missing list; non-release → rc 0
  "not release-tracked"; compliant → rc 0.
- Real-board dry-run (364 cards): gate-clean — no `release:` cards exist
  yet, rollout bounces nothing.
- **dev-twin-smoke.py live PASS**: `tony-ha lovelace` via tony-dell
  playlived — 7.2s, 3 shell elements, 42 cards, screenshot saved, exit 0.
  FAIL path also verified live: stale michael-dev token → correctly
  detects the login redirect and reports "token rejected"; a bogus
  dashboard → FAIL with evidence (found + fixed: playlived eval needs an
  IIFE/expression, not a bare arrow — returns `{ok:true}` with no result).
- py_compile, bash -n, yaml.safe_load, ssot-validate-all (only error is
  the pre-existing `jobs/vcast/2026-10-10-gev-yt-local-media-failures.yml`),
  pytest tests/{ha,board,ada} — 135 passed.

## How to verify / use

```bash
# opt a card in: add `release: tony` to its yml
python3 scripts/ada/lifecycle-check.py --dry-run            # audit all
python3 scripts/ada/lifecycle-check.py --gate docs/ssot/kanban/cards/x.yml --stage preprod
python3 scripts/home-assistant/dev-twin-smoke.py --inst michael-dev --card <id>
scripts/home-assistant/promote-michael.sh --card <id> --dry-run   # warns on unmet gate
scripts/home-assistant/promote-michael.sh --card <id> --confirm   # enforces gate + smoke
```

## Caveats / remaining gaps (documented in the standard)

- michael-dev token on tony-omen is stale (401) — smoke runs from
  tony-dell or after re-minting `~/.config/secrets/ha-michael-dev.env`.
- tony-dev/ada-dev still `planned:` — [smoke] gate unmeetable there until
  ha-dev-instances lands; `--from michael-dev` bridge stands.
- "zero attributable incident cards" and the 2-consecutive-scenario alpha
  claim remain human-attested (listed as the remaining gaps).
- Nothing committed/pushed/deployed per dispatch rails — worktree files
  left for the session checkpoint.
