# Dispatch outcome — build-a-read-only-opencode-ses (AUD-0938 re-land)

Card: `opencode-session-audit-parity` · Runner: idc02 · Read-only audit work; nothing deleted, no model/config changes, no push.

## What was built

- `scripts/devnest/opencode_session_audit.py` — read-only OpenCode session audit, parity with the Ada transcript audit. Opens `~/.local/share/opencode/opencode.db` with sqlite `mode=ro`, audits **every** session newer than `~/.local/share/devin/opencode-audit-marker` (24h default when absent; `--all`, `--since`, `--session` overrides), and writes JSON + Markdown reports. Marker advances only after both report files are written.
- `tests/devnest/test_opencode_session_audit.py` — 20 unittests on a synthetic sqlite fixture. All green.
- `evals/opencode-lane/reports/2026-11-07-session-audit.{md,json}` — first **durable** full-store audit (276 sessions on idc02).
- `docs/ssot/jobs/devnest/2026-11-07-opencode-session-audit.yml` — job record.
- `evals/opencode-lane/PROCEDURE.md` — session-audit pointer updated to the durable artifacts.

## Per-session coverage

Prompts/task turns, agent/model/provider, tool calls, denied-vs-error split (denial signature), write/delete/commit/push attempts including bash-redirect, `python -c`, and urllib smuggling, artifact paths with durable-landing verdicts (ephemeral/missing/landed/exists/committed/protected — repo-tracked basenames resolve worktree-deleted files that merged), claims without evidence (sentence-scoped negation + JSON-key + passive-voice guards; claims cross-checked vs filesystem, `git ls-files`, and the cards dir), input/output/reasoning/cache tokens vs session columns, wall/step/tool latency, retries, mixed-focus contamination (foreign cards, worktree roots), safety flags.

## Audit result (2026-11-07, idc02, --all)

276 sessions · 39 findings · 24 flagged · 158 denied calls · 37 mutation attempts · 8 durable artifact misses · **0 ungated profile runs** · 0 token mismatches · governance: lane_gated 13, ledger_recorded 217, dispatch_rails 41, interactive 4.

- **S1/S2 evidence:** all 13 `evals/opencode-lane/runs` evidence dirs joined to DB sessions via `events.jsonl` sessionIDs; `run.json` input_tokens == session columns (delta 0.0) on every check. S1 canaries carry verifier verdicts in evidence. No S2 envelopes/runs exist — the lane was rolled back S1→S0 on 2026-10-29.
- **Promotion ledger vs shadow benchmark reconciled:** S0 ledger verified=3/5 vs benchmark opencode-arm pass=2/5 is **not a ledger error** — two independent executions of the same fixtures (benchmark ~06:49Z, lane s0-run ~07:41Z) with non-deterministic gemini-3.5-flash-lite; worktree-safety diverged, mcp-safety + storage-dryrun failed in both. Reported as expected divergence; a real ledger error would require the same session IDs disagreeing.
- **8 kanban cards filed** via board-api (idempotent `audit-oc-*` ids; re-run dedupes to already-filed): 4 artifact_not_durable (verdict-pilot3.json; opencode-profile-inventory-2026-10-30.md ×2 sessions; docs/ssot-research/inventory.md), 1 denied_tool storm (113 denied calls in one ops-readonly pilot), 3 mutating_command (storage-dryrun wrote files via `python -c`; 2× ops-readonly POST /comment against forbidding rails).
- Denied calls are reported as friction (the gate working); only storms ≥20 card. Ephemeral `/tmp` writes report but don't card.

## Repeatable

```bash
python3 scripts/devnest/opencode_session_audit.py              # since marker
python3 scripts/devnest/opencode_session_audit.py --all        # full store
python3 scripts/devnest/opencode_session_audit.py --file-cards # + card filing
python3 -m unittest tests.devnest.test_opencode_session_audit  # 20 tests
```

## Verify

- `python3 -m unittest tests.devnest.test_opencode_session_audit` → 20/20 OK
- `cat ~/.local/share/devin/opencode-audit-marker` → set; bare re-run audits 0 sessions
- `evals/opencode-lane/reports/2026-11-07-session-audit.md` Reconcile section for the discrepancy verdict
- board: `audit-oc-*` cards in backlog

## Note

This is the durable re-land of the 2026-10-27 run Tony flagged evidence-incomplete (AUD-0938) — the original script/tests/report died with the kept-dirty worktree. Detector improvements over the lost v1: governance classification (dispatch-rails + metrics-ledger epoch join) instead of blanket ungated flags, claim-evidence sentence/JSON-key/passive guards, and repo-landing resolution for artifacts whose worktrees were deleted post-merge.
