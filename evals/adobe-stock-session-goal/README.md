# adobe-stock-session-goal — OpenChamber Session Goal eval

Card: `openchamber-session-goals-adobe-stock-qc` · Status: **goal defined,
awaiting a live OpenChamber run** (no ocb/opencode executor on the authoring
host).

Tests whether an OpenChamber Session Goal can drive a **bounded, read-only**
Adobe Stock reuse review to a verifiable stopping condition: the agent must
call the `ada_adobe_stock_reuse` MCP report for a named campaign idea, list
candidate assets with provenance, flag missing previews and open questions,
emit a structured markdown+JSON artifact plus a run record (turns, cost,
final artifact), and **stop** — no card creation, uploads, generation,
licensing, or publishing.

## Layout

- `GOAL.md` — the Session Goal text. Paste this into an OpenChamber
  session (or feed it as the session's goal/brief) to run the eval.
- `goal.json` — machine-readable mirror of the same contract: allowed
  calls, forbidden actions, required artifacts, `stop_when` conditions,
  acceptance checks, recording requirements.
- `verify.py` — held-out mechanical verifier. Run it against the session's
  artifact directory; exit 0 = acceptance met.
- `fixtures/sample-out/` — synthetic but contract-valid example output
  (3 real provenance records from campaign
  `AS-2026-11-05-REMOTE-WORK-001`). Not a real session result.

## How to run (on idc02, where OpenChamber lives)

1. Start an OpenChamber session on the ada-ocb profile (it carries the
   `ada_adobe_stock_reuse` MCP tool) in a scratch working directory —
   e.g. `~/session-goal-out/adobe-stock-reuse-qc-v1/`.
2. Give the session the contents of `GOAL.md` as its goal/brief.
3. Let it run to its own stop condition. Do not prompt it further — the
   point is whether the goal alone terminates correctly.
4. Collect the artifact dir (the three required files) back to a chaba
   checkout or verify in place.

## How to verify

```bash
cd evals/adobe-stock-session-goal
python3 verify.py fixtures/sample-out   # contract self-check -> pass
python3 verify.py /path/to/session/artifact-dir
```

`verify.py` checks: all three artifacts present and non-empty; the JSON
parses with every required key; `report.tool == ada_adobe_stock_reuse`
with a `called_at`; every candidate has the full key set, a valid
decision/preview_status enum, non-empty provenance fields, and no
duplicate asset_ids; `missing_previews`/`open_questions` are lists whose
entries are known candidate ids; the policy block is fully clean
(`mutations_performed: []`, all `*_requested`/`cards_created`/`published`
false); `no_mutation_receipt` present; `run.json` records `turns`
(integer), `cost_usd` (null allowed — unmetered is honest), timestamps,
`artifact_dir`, and `stop_reason` (`acceptance-met` or `blocked:<why>`).

For the card's `expected_goals`-style acceptance, the equivalent checks
are in `goal.json → acceptance.expected_goals_style`.

## Interpreting a run

- `verdict=pass` + `stop_reason=acceptance-met` → the Session Goal drove
  the review to a verifiable stop. Record turns/cost from `run.json`.
- `verdict=fail` → `hard_failures` names exactly which acceptance
  condition the session missed — that is the eval signal (did the goal
  loop, skip provenance, or mutate something it shouldn't).
- `stop_reason=blocked:*` with a passing verifier is an honest partial:
  the goal stopped rather than looped, which is itself a pass on the
  "does not loop" criterion; note the blocker.

## Cost / turns recording

`run.json` is the record. `turns` comes from the ocb/opencode session
record or event log; `cost_usd` is `null` when the executor does not
meter cost — never estimate silently. The verifier enforces key presence,
not meter accuracy; the runner should fill real values.
