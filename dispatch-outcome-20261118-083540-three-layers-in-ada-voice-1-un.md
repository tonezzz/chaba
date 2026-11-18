# ada-ocb-regression-suite — dispatch outcome (2026-11-18)

**Result: DONE** — all three layers implemented, verified live, committed to
ada-voice branch `dispatch/20261118-083540-ada-ocb-regression-suite`
(commit `b362d92`, **not pushed** — needs merge to main via tony-dell).

## What changed (ada-voice worktree at `.scratch/ada-voice`)

- `tests/test_opencode_ada_mcp_context_pack.py` — context_pack tool set
  (`ada_card_context`, `ada_memory_search`, `ada_ssot_excerpt`/`_get`,
  `ada_context_pack` incl. selector-block hit), board-API helpers,
  dispatch-envelope deadline/partial behavior.
- `tests/test_opencode_ada_mcp_board_snapshots.py` — snapshot payload
  parsing (strings/numbers/nulls/missing keys tolerated),
  compact→projected→hydrate resolution order for `find_card`, 20s
  `_get_json_cached` TTL, `ada_board_snapshot`/`ada_cards`/`ada_status`/
  `ada_card_show` no-mutation contract.
- `tests/test_opencode_ada_mcp_selection_gate.py` — `_pick_cards`
  preview-only + selection tokens, `_selection_gate` confirm/next/native-
  menu paths, `_card_pick`/`ada_card_pick` end-to-end, `ada_preflight`
  gate fields + dispatch envelope.
- `tests/dep_stubs.py` — `mcp.server.fastmcp` stub so all bridge tests
  actually RUN in the deploy-gate venv (previously they imported-skipped;
  `test_opencode_ada_mcp_bridge_version.py` now runs too: 69 opencode tests total).
- `scripts/ocb-smoke.py` + `ada-ocb-smoke.{service,timer}` — live read-only
  smoke (bridge_info, ssot_get tony-macbook, find_card ADA-0172, pick_cards,
  context_pack, preflight gates); per-call ok / `mutations_performed==[]` /
  `<8s`; appends `kind:benchmark` doc to `ada-ha-scenario-reports` on the
  **ops store** `http://100.123.163.11:11025/v1`; hourly user timer armed on
  idc02 (ExecCondition-skips until the script lands in `~/CascadeProjects/ada-voice`).
- `scripts/ocb-bench.py` — per-tool calls/ok-rate/p50/p95/error-classes from
  `~/.local/share/ada-control/calls.jsonl` → same benchmark collection
  (`--hours`, `--calls`, `--mddb`, `--dry-run`).
- `opencode/ada_mcp.py` — real fix: `_cards_payload` no longer TypeErrors on
  dict payloads with null/missing `cards` key.
- Trail: `docs/ssot/jobs/ada/2026-11-18-ada-ocb-regression-suite.yml`.

## Verification

- Full deploy-gate suite in worktree: **1807 passed, 7 skipped** (3.5 min);
  tool-lint clean.
- `scripts/ocb-smoke.py` manual run: **6/6 PASS** in ~3.4s, doc
  `ada-ha-scenario-reports/benchmark/ocb-smoke-20261118-085114`.
- `scripts/ocb-bench.py`: `benchmark/ocb-bench-20261118-085127` (49 calls,
  11 tools — the container-mount fallback path, host path first).
- `systemctl --user list-timers ada-ocb-smoke.timer` → next fire 09:00 +07.

## Findings / follow-ups

- `ada-ha-scenario-reports` lives on **mddb-ops** `:11025`, not the
  `:11023` leader (`/add` there embeds inline → timeout). Both scripts
  default to the ops store; override via `MDDB_OPS_URL`.
- Deployed ada-code bridge copy
  `~/.local/share/ada-code/workspace/.opencode/ada_mcp.py` is **stale**
  (pre-ff2d6a1) vs repo HEAD — smoke tests repo HEAD; the container needs
  its own sync/redeploy.
- `mddb /vector-search` 400s on `infrastructure-ssot` + `chaba-glossary`;
  bridge degrades to `/search` fallback (surfaced as `errors[]` in smoke docs).

## Verify

```sh
cd .scratch/ada-voice && /home/tony/CascadeProjects/ada-voice/.venv/bin/python -m pytest tests/test_opencode_ada_mcp_*.py -q
python3 .scratch/ada-voice/scripts/ocb-smoke.py
python3 .scratch/ada-voice/scripts/ocb-bench.py --dry-run
curl -s 'http://100.123.163.11:11025/v1/get?collection=ada-ha-scenario-reports&key=benchmark/ocb-smoke-20261118-085114'
systemctl --user list-timers ada-ocb-smoke.timer
```
