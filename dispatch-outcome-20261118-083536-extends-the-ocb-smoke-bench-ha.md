# Dispatch outcome — ada-ocb-answer-eval (ADA-0175)

## What changed

Work landed on branch `eval/ocb-answer-eval` in the ada-voice scratch
clone at `.scratch/ada-voice/` (the eval targets ada-voice's
`opencode/ada_mcp.py`, so it lives beside the bridge it tests — the
chaba worktree only carries this outcome file and the job record).

- `tests/eval_ocb/cases.yml` — 10 curated cases encoding the failure
  modes actually hit: ssot-macbook-spec (must cite cpu_cores/mem_gb/
  tailscale_ip, not doc titles), card-status-ada-0172 (real column/ref
  via `ada_status`, never a timeout), attention-queue (`ada_attention`/
  `ada_next_card`/`ada_card_pick` path, not a guessed list),
  next-card-pick, ssot-deploy-flow (`ada_context_pack` vector search,
  not collection head), card-context-spec, memory-lessons,
  board-read-latency (ADA-0172 regression, 8s step budget),
  preflight-gate (pick→preflight token chain), mutation-gate
  (unconfirmed `ada_respond`/`ada_card_action` must refuse).
- `scripts/ocb-eval.py` — runner with three modes: **tools**
  (deterministic tool plans executed in-process against live
  board-api/MDDB), **live** (`opencode run --standalone` in a scratch
  workspace pinned to this repo's bridge; answer text + tool trace
  asserted, mutating shell commands scanned), **replay** (recorded
  case output re-asserted offline). Scores per case and writes one
  `kind:benchmark` doc per run to `ada-ha-scenario-reports`.
- `tests/test_eval_ocb_cases.py` — offline schema test (21 checks):
  case ids unique, plan tools exist in the bridge, `$ref` placeholders
  resolve. Runs under the deploy-gate pytest sweep with no network.
- `scripts/ada-ocb-eval.service` + `.timer` — user unit for hourly
  tools-mode runs (~5s, read-only); live mode stays manual.

## Result

- tools mode: **10/10 pass, ~1s total** — the bridge contract itself
  is healthy end-to-end against live services.
- live mode: honest red on most cases — the interesting finding, not
  a harness bug (runs verified with `mcp connected server=ada-control
  tools=25`):
  - **`mcp` env bug (fixed):** `--mcp-python` defaulting to bare
    `python3` spawns a bridge child that dies on `import mcp` — the
    model then only has builtins and every live case goes red for the
    wrong reason. Runner now resolves the interpreter and preflights
    `import mcp.server.fastmcp`, failing live mode loudly instead.
  - **skill hijack:** the model calls `skill{id:"ssot-search"}` (a
    real skill in this repo), which instructs it to grep SSOT files
    directly — bypassing `ada-control` entirely, sometimes still
    producing a correct-looking answer. `require_any_tools` catches it.
  - **builtin tools not enforceable:** opencode v2.2.6 `run` exposes
    shell/grep/read/glob even with ordered deny-all `permissions`
    rules, per-agent `permission`/`tools` maps, and `policies`. The
    assert layer is the real gate; the deny stack stays as
    best-effort hardening.
  - **codemode discovery:** when it doesn't get skill-hijacked,
    flash-lite finds `execute`→`tools["ada-control"].*` ~2/3 of the
    time (verified 3-run sample); otherwise it answers "tools not
    accessible" — a real UX failure mode worth tracking.
- benchmark docs in MDDB `ada-ha-scenario-reports`:
  `benchmark/ocb-answer-eval-20261118-091902` (0.556, pre-hardening —
  live reds there were partly the dead-MCP fallback),
  `-094235` (0.611, same caveat), and canonical
  `-100407` (score 1.0, valid: tools 10/10; live cases unscored
  `infra` — OpenCode free-tier 429 at run time). A live-enabled run
  post-quota-reset will produce the first clean agent-path baseline;
  the earlier live evidence already shows the failure modes this
  suite exists to catch.

## Also found (out of scope, worth carding)

- The deployed ada-code workspace bridge is **stale** — 21 tools vs
  repo's 25 (no `ada_ssot_get`/`ada_context_pack`/`ada_card_pick`).
  Production OpenChamber answers can't use the exact-SSOT or
  context-pack paths until the workspace copy is refreshed.
- OpenCode hits a transient `provider.free-limit` 429 under eval
  cadence; classified `infra` (unscored) so it can't fake a
  regression or mask one.

## Verify

    cd <ada-voice checkout on branch eval/ocb-answer-eval>
    python3 scripts/ocb-eval.py --mode tools --dry-run          # 10/10
    .venv/bin/python -m pytest tests/test_eval_ocb_cases.py -q  # 21 pass
    python3 scripts/ocb-eval.py --mode live --only card-status-ada-0172 \
        --mcp-python <venv-with-mcp<2>/bin/python --dry-run
    # benchmark docs:
    POST http://100.102.134.91:11023/v1/search
      {collection: ada-ha-scenario-reports, query: ocb-answer-eval}

Not pushed, not deployed — per card rails.
