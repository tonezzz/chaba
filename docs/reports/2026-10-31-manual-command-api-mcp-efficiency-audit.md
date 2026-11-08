# Manual-command → API/MCP efficiency audit

- date: 2026-10-31
- card: `ops-manual-command-api-mcp-efficiency-audit` (AUD-1033, program devnest-efficiency)
- session: `dispatch-wt-20261031-081655` on idc02
- verdicts: 1 endpoint gap found and fixed (board read projection), 1 job-pack landed (`host_snapshot.py`), rest classified; no deploys, no MCP surface broadened, no secrets touched.

## Evidence base

| corpus | coverage | what it proves |
|---|---|---|
| `evals/opencode-lane/runs/p1-*/events.jsonl` (14 runs, 137 tool calls) + `evals/results/opencode-mcp-readonly/events-run{1,2}.jsonl` | OpenCode lane sessions, 2026-10-27/28 | per-call tool, wall gaps, status, payload bytes, per-step tokens |
| `dispatch-outcome-*.md` (306 files) | Devin dispatch sessions, Oct 2026 | which orchestrations recur (grep census over documented commands) |
| live board-api on idc03 | production read surface | measured `/cards` = 5,224,998 B / 1136 cards / 15,714 comms entries |
| `runner-agent.py` source | machine consumers of board reads | `/cards` fetched 2×/pass, ~60s cadence per runner host |
| `scripts/board/board-api.py`, `scripts/mcp_debug/tools.py`, `evals/opencode-lane/profiles/*` | canonical surfaces | which API/MCP/script already covers each intent |

Not in corpus (outside worktree, correctly unreachable): `~/.local/share/devin/cli/sessions.db` (Devin tool telemetry), `opencode.db` on tony-macbook. Findings are stated from committed telemetry + documented outcomes only — same boundary the AUD-0944 audit hit.

## Inventory — recurring command sequences

Classification tags: **keep-shell** | **job-pack** (repo script) | **board-api** | **scoped-mcp** | **composite** (profile+verifier workflow).

| # | sequence (intent) | evidence of repetition | measured cost | fail/retry | perm risk | canonical exists? | class |
|---|---|---|---|---|---|---|---|
| S1 | host-health micro-probe storm: `hostname; date; uptime; nproc; free -m; df -P /; systemctl list-units --failed ×2; date arithmetic` | 4 ops-readonly runs, ~10 bash calls each (40 of 137 total calls) | ~8–13 calls/run, 94–221s wall, ~44–71k in-tokens/run | 4–30% errors/run — allowlist denies + python math typos; one retried arithmetic 3× | medium: compound `cmd && cmd` denied outright; per-cmd probes pass → incentive to spam calls | **now: `scripts/devnest/host_snapshot.py`** (this audit) | job-pack |
| S2 | storage/drift probes: `stat --format='%s'`, `du`, `find`, inline-python protected-fragment scan | 2 storage-dryrun runs, ~8 calls each | ~13–19 calls/run, 166–182s wall | 5/19 and 5/13 errors in one run (denied compounds, `du` dir errors) | medium-high: inline python that walks protected paths | partial — profile verifier recomputes; no probe script | composite (keep; probe candidate noted) |
| S3 | MDDB surface probes: banks/health/vector-stats/config/expired | 12 calls across 2 mddb-sequence runs | bounded pages, 0 errors | none | low: script exposes only GETs/read-only search | **`scripts/devnest/mddb_probe.py`** — the exemplar | job-pack (exists) |
| S4 | MCP probes: `mcp_debug`, `mcp_health`, `mcp_search_ssot`, `mcp_get_file` | 9 calls across runs | small payloads, 0 errors | none | low: readonly upstream proxy | **mcp-debug-readonly server** (8-tool allowlist) | scoped-mcp (exists) |
| S5 | repo read/grep/glob | 28 calls | normal agent IO | 2 grep size errors | low | — | keep-shell |
| S6 | date/epoch arithmetic (`date +%s`, `python3 -c` math) | 5 calls in ops runs | trivial bytes, but 1 error + retries | ~20% | low | — | keep-shell (fold into S1 snapshot) |
| D1 | **card state read**: `curl /cards` + client-side filter | every session that checks a card; `runner-agent.py` lines 2077/2173 fetch `/cards` twice per ~60s pass on every runner host | **5,224,998 B/response**; fleet ≈ 15 GB/day/host for claim polls | none observed — just cost | low (open read) | **now: `GET /card/<id>`, `GET /cards?<query>`** (this audit) | board-api |
| D2 | board writes: `POST /comment|/request|/respond|/action` curl one-liners | every dispatch session (rails) | ~1 call each, ~100 B | rare (400 on bad id) | low: tailnet-identity write door | **board-api write door** | keep-shell (already minimal) |
| D3 | ssh remote orchestration (`ssh host 'systemctl|ls|cat'`) | 83/306 outcomes mention ssh | multi-command per hop | varies | **high: broad shell on remote hosts** | mcp-debug `run_on_host` allowlist + presets | composite → prefer scoped-mcp |
| D4 | systemd status/journalctl checks | 61/306 outcomes (systemctl+journalctl) | per-unit curls | — | medium | mcp-debug `mcp_logs`/`mcp_system`; +host_snapshot for fleet facts | scoped-mcp |
| D5 | test gates: `pytest`/`unittest` runs | 49/306 | — | n/a | low | existing test suites | keep-shell |
| D6 | MDDB `/v1/search` curl orchestration | 77/306 outcomes | paged scans | page-cap failures on huge collections | medium (write endpoints reachable by same curl) | `mddb_probe.py` for lanes; `/report` covers cms search | job-pack + board-api |
| D7 | WP `wp-json` REST curls | 13/306 | — | — | high (holds creds) — **forbidden now** | board-api `/lesson` `/job` `/report` `/publish` | board-api (migrated) |
| D8 | `$TASK_DIR/answers.jsonl` polling | every dispatch | 1 file read | none | none | session envelope is the mechanism | keep-shell |
| D9 | surface-verification curls (page/endpoint after change) | 24/306 | — | — | low | mcp-debug `mcp_net`/`mcp_debug` for remote | keep-shell |
| D10 | artifact durability checks (stat/find on outputs, sentinel verify) | storage-dryrun, artifact-write, doc-draft profiles | — | — | medium | profile+held-out-verifier pattern | composite (exists) |
| D11 | Telegram notifications | 12/306 | — | — | low | `/publish` telegram sink | board-api (exists) |
| D12 | lesson capture (`lesson-add.py`→WP) | 5/306 | — | — | low | `/lesson` + thin client | board-api (exists) |

## The gap that mattered

**Board reads had no projection.** Writes got the unified door (Oct 23–26);
reads stayed a single 5.22 MB dump. Every "check my card" agent turn and
every runner claim poll paid the whole board. `/queue` (2 KB) proved the
shape worked but covered only the queue projection — nothing for
single-card, filtered, or field-subset reads.

Fix landed this session (code + tests, **not deployed — promotion is the
normal served-checkout path**):

- `GET /card/<id>[?fields=|compact=1]` → `{ok, card}` | 404 `{error,id}`
- `GET /cards?<query>` → `{ok,count,total,offset,truncated,cards[]}`
  - filters: `id`, `column`, `action_status`, `since` (lexicographic vs `updated`)
  - projection: `fields=a,b,c` (absent keys dropped, unknown ignored) or `compact=1` → {id,title,column,updated,priority,ref}
  - pagination: `limit` (cap 1000) + `offset`; `truncated` flag
  - bare `/cards` unchanged (legacy shape — zero consumer regression)
- `GET /card` (no id) → 400 with `hint` (self-describing misuse)

Contract facets (per card spec): structured I/O (JSON both ways) ·
pagination/limits (`limit/offset/truncated`, 1000 cap) · compact mode
(`compact=1`, `fields=`) · idempotency (pure GET; `generated` stamp is the
version token for `since=` delta reads) · timeout (served from rendered
file — no upstream, bounded ms) · audit event (stderr/journald request
line per GET, same as today) · authorization scope (open reads —
unchanged from `/cards`; writes still behind tailnet identity) ·
deterministic verifier (`tests/board/test_board_api_reads.py`, 19 tests +
bench evidence-equality) · rollback (additive routes; revert deletes them,
bare `/cards` behavior untouched).

## Benchmark — manual baseline vs replacement, identical fixtures

`scripts/board/board_read_bench.py` runs the real handler on loopback
against an identical fixture per lane; token est = chars/4 + 60-char
envelope (mcp-files-bench convention); evidence equality verified.

Live fixture (real `cards.json`, 1136 cards — full results in
`docs/reports/board-read-bench-2026-10-31.{md,json}`):

| scenario | manual B | new B | Δbytes | calls | Δtok-est | ms m→n | evidence |
|---|---|---|---|---|---|---|---|
| single-card-read | 5,224,998 | 4,216 | 99.92% | 2→1 | 99.91% | 170→54 | yes |
| board-index | 5,224,998 | 219,635 | 95.80% | 2→1 | 95.79% | 172→51 | yes |
| claim-poll (runner ~60s) | 5,224,998 | 1,767 | **99.97%** | 1→1 | 99.96% | 174→50 | yes |
| status-check | 5,224,998 | 66,102 | 98.73% | 2→1 | 98.73% | 174→49 | yes |
| delta-sync (`since=`) | 5,224,998 | 10,909 | 99.79% | 2→1 | 99.79% | 160→44 | yes |

Synthetic seeded fixture (reproducible, `*-synth.{md,json}`): same
ordering, 93–99.9% reductions, all evidence-equal. Fleet projection:
a runner host polling `/cards` every 60 s moves ~7.5 GB/day → ~2.5 MB/day
via `action_status=queued&fields=…` (~3000×), before counting the second
fetch in `verdict_pass`.

`host_snapshot.py` vs micro-probe storm (telemetry-derived): ~10 calls →
1; measured run wall 94–221s → probe itself <0.1s local; denied-call
class disappears entirely (one allowlisted script instead of 10+ rules);
output is exactly the ops-readonly contract the held-out verifier
already checks.

Requirements check: **no capability regression** (evidence-equal every
scenario; bare `/cards` untouched), **lower overhead** (95.8–99.97% wire,
fewer calls), **equal-or-better evidence** (verifier normalizes only
absent-key-vs-null — semantically identical).

## Classified outcomes

- **board-api endpoint (implemented)**: D1 read projection — code, 19
  tests, bench, contract doc. Runner-agent switchover is deliberately
  **not** in this change (production behavior change; recommended
  follow-up — swap the two `api("/cards")` calls for
  `/cards?action_status=queued&fields=id,title,brief,spec,action,blocked_by,priority,updated,claim`
  after soak).
- **job-pack (implemented)**: `scripts/devnest/host_snapshot.py` —
  S1 storm → 1 call emitting the ops-readonly contract; allowlisted in
  that profile's bash rules; 10 tests.
- **job-pack (existing, reaffirmed)**: `mddb_probe.py` — the model for
  bounded probes (allowlist-safe, held-out verifier).
- **scoped MCP (existing, reaffirmed)**: mcp-debug-readonly toolset —
  measured zero errors across lane runs; covers D3/D4 when callers use
  it instead of ad-hoc ssh. Designed-but-not-deployed: a `host_snapshot`
  preset entry (`PRESETS` map) so interactive lanes get the same
  collapse — MCP surface change is gated, contract ready.
- **composite (keep)**: storage-dryrun / artifact-write / doc-draft
  profiles + held-out verifiers; ops-readonly profile now has the probe
  to fold into. ssh multi-host sweeps should route through
  `mcp_preset_run`, not bespoke ssh chains (D3).
- **keep shell**: D2 write curls (already 1-call minimal via the write
  door), D5 test gates, D8 answers polling, D9 surface curls, S5 repo
  reads, S6 date math (now also inside the snapshot).

## Follow-ups carded/recommended (not done — gates)

1. runner-agent `/cards` → projected read (soak the endpoint first;
   behavior-identical claim/verdict fields — bench claim-poll proves
   payload adequacy).
2. `mcp_preset` entry `host_snapshot` + preset catalog note (MCP surface
   change — explicit gate).
3. `storage_probe.py` job-pack for S2-class drift scans (dir-size table,
   protected-fragment check emitting the storage-dryrun contract) —
   worth it only if S2 profiles run unattended often.
4. Devin-side telemetry gap: `sessions.db` tool-call export would let
   this audit measure Devin sessions directly instead of via
   outcome-doc census — a small exporter belongs with the
   devin-session-audit skill.

## Files

| path | change |
|---|---|
| `scripts/board/board-api.py` | `GET /card/<id>`, `/cards` query projection, `load_cards()` shared |
| `scripts/devnest/host_snapshot.py` | new job-pack |
| `scripts/board/board_read_bench.py` | new benchmark (real handler, identical fixtures) |
| `tests/board/test_board_api_reads.py` | 19 tests |
| `tests/devnest/test_host_snapshot.py` | 10 tests |
| `evals/opencode-lane/profiles/ops-readonly/profile.yml` | bash allowlist +`host_snapshot.py` |
| `tests/devnest/test_opencode_profiles.py` | stale expected-profile list updated (pre-existing master failure) |
| `docs/kb/board-api-read-door.md` | new operational procedure |
| `docs/ssot/ssot.token-tools.yml` | catalog section for the command-efficiency layer |
| `docs/reports/board-read-bench-2026-10-31{,-synth}.{md,json}` | bench artifacts |
| `docs/ssot/jobs/devnest/2026-10-31-manual-command-efficiency-audit.yml` | job record |

Tests: `unittest tests.board.test_board_api_reads` (19),
`tests.devnest.test_host_snapshot` (10); suite `tests/board` 333 OK,
`tests.devnest.test_opencode_profiles`+`test_lane_gate` 96 OK,
`board-api.py --selftest` OK.
