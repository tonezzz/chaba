# Dispatch outcome — ops-manual-command-api-mcp-efficiency-audit (AUD-1033)

Branch: `dispatch/20261031-081655-audit-recent-opencode-devin-ne` · commit `21b4309ca` · runner idc02

## What was found

Audited committed OpenCode lane telemetry (14 runs / 137 tool calls in
`evals/`), 306 dispatch-outcome docs, the live board-api surface, and
`runner-agent.py`. The dominant recurring waste was **board reads with no
projection**: bare `GET /cards` = **5,224,998 B** (1136 cards, 15.7k comms
entries) was the only read path — every agent card-check and every runner
claim poll (`api("/cards")` ×2 per ~60s pass per host ≈ 7.5 GB/day/host)
paid the full dump. Second class: the ops-readonly **micro-probe storm**
(~10 bash calls/run: hostname/date/uptime/nproc/free/df/systemctl×2) with
4–30% call error rates — the bash allowlist denied compound commands
while passing per-cmd probes, itself incentivizing call-spam. Existing
bounded surfaces (`mddb_probe.py`, mcp-debug-readonly: 21 calls, 0
errors) were reaffirmed as the winning pattern; board writes, MCP probes,
test gates, and artifact-verification composites were classified
keep-shell/existing.

## What changed

- **`scripts/board/board-api.py`** — `GET /card/<id>[?fields|compact]` and
  `GET /cards?<query>`: `id`/`column`/`action_status`/`since` filters,
  `fields=a,b,c` + `compact=1` projection, `limit`(≤1000)/`offset`/
  `truncated` pagination, `{ok,count,total,offset,truncated,cards[]}`
  envelope. Bare `/cards` unchanged (zero consumer regression).
- **`scripts/devnest/host_snapshot.py`** — one-call read-only host probe
  emitting exactly the ops-readonly contract; per-probe timeout +
  `errors[]` degradation; allowlisted in `ops-readonly/profile.yml`.
- **`scripts/board/board_read_bench.py`** — benchmark running the real
  handler on loopback over identical fixtures (live `--cards-json` or
  seeded synthetic), evidence-equality verified per scenario.
- **Tests**: `test_board_api_reads.py` (19), `test_host_snapshot.py`
  (10); also fixed a stale expected-profile list in
  `test_opencode_profiles.py` (pre-existing master failure — committed
  `artifact-write`/`doc-draft` profiles were missing from it).
- **Durable docs**: `docs/reports/2026-10-31-manual-command-api-mcp-
  efficiency-audit.md` (full inventory + classifications + contracts),
  `docs/reports/board-read-bench-2026-10-31{,-synth}.{md,json}`,
  `docs/kb/board-api-read-door.md` (procedure), SSOT updates
  (`ssot.token-tools.yml` new "Command-to-API/MCP Efficiency Layer"
  section; job record `docs/ssot/jobs/devnest/2026-10-31-…yml`).

## Result

Benchmark on the **real cards.json** (identical fixture both lanes):
single-card 99.92%, board-index 95.80%, claim-poll **99.97%** (5.2 MB →
1.7 KB), status-check 98.73%, delta-sync 99.79% byte cuts; 2→1 calls;
~3× faster median latency; **all scenarios evidence-equal**. Guardrails
kept: reads stay open (no new auth surface), writes untouched, no MCP
broadening, no deploy — promotion is the normal served-checkout merge.

## How to verify

- `python3 -m unittest tests.board.test_board_api_reads tests.devnest.test_host_snapshot` — 29 tests.
- `python3 scripts/board/board_read_bench.py --reps 15` — reruns on the seeded fixture; `--cards-json <path>` for live.
- `python3 scripts/board/board-api.py --selftest`; full `tests/board` = 333 OK.
- Live after merge: `curl 'https://idc03…:10000/card/<id>'`, `curl '…/cards?action_status=queued&fields=id,action'`.

## Open follow-ups (board request raised on the card)

1. runner-agent `api("/cards")` ×2 → projected read (soak first).
2. `host_snapshot` mcp preset (MCP surface change — explicit gate).
3. `storage_probe.py` job-pack (only if storage lanes run unattended often).
4. Devin `sessions.db` tool-call exporter — closes the Devin-side
   telemetry gap (this audit used the same repo-only boundary as AUD-0944).
