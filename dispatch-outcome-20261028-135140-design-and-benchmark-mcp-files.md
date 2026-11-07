# Dispatch outcome — mcp-structured-files-tool (OPS-0961)

## What was built

Four structured read-only filesystem tools on the mcp_debug MCP server,
per card spec (card writes `mcp_files/list` etc.; MCP tool names require
`[a-zA-Z0-9_-]+` so shipped with underscores):

- `mcp_files_list` — one directory level (pattern/max_entries/sort/order)
- `mcp_files_stat` — single path, one entry
- `mcp_files_search` — recursive fnmatch search (depth/max_entries/kind)
- `mcp_files_tree` — pre-order walk with per-entry depth

Architecture: `scripts/mcp_debug/files.py` vets the path against the
existing per-host `allowed_path_prefixes` allowlist
(`ssot.mcp-debug.files.yml`), then ships the self-contained
`scripts/mcp_debug/files_agent.py` base64'd through `run_on_host(shell=True)`
to a remote `python3` (no remote mcp-debug binary needed → works on macbook
too). The agent re-verifies the allowlist after realpath resolution, never
descends symlinks (flags `link_escape` instead), and enforces
entries/depth/output/errors/scan caps remotely — one SSH round trip per
call.

Stable schema per card: `host, root, entries[{name, relative_path, kind,
size_bytes, mtime, mode}], truncated, errors, observed_at` (+tool,
resolved_root, truncated_reason, counts, scanned, depth/pattern/sort/order
echoes). `kind ∈ file|dir|symlink|other`, mtime epoch int, mode 4-digit
octal. Opt-in `format:"rows"` returns the same fields positionally with a
`fields[]` header (~37% smaller payloads).

`mcp_raw` remains gated behind `raw_commands.allowed_prefixes`; compact
mcp_debug commands untouched. All four tools added to
`READONLY_MCP_TOOLS` in `scripts/devnest/lane_gate.py` (graduated lanes may
request them); `docs/ssot/infrastructure/ssot.mcp-debug.files.yml` gained a
`files:` policy section.

## Verification

- `scripts/mcp-files-verify.py`: **39/39 green** — agent ops/schema/caps,
  security matrix ('..', outside-roots, symlink escape, dir loops,
  permission-denied, unicode/space names, rows format), tool-layer e2e via
  `run_on_host` (injected local host), MCP stdio tools/list + error
  envelope.
- `python3 -m unittest tests.devnest.test_lane_gate
  tests.devnest.test_opencode_profiles`: 96/96 OK.

## Benchmark (30 tasks vs raw shell)

`scripts/mcp-files-bench.py` → `reports/mcp-files-bench-2026-10-28.md/.json`
(both force-committed; reports/* is gitignored but bench reports are
tracked by convention). Deterministic fixture, 10 host-assessment + 6
node-red/devnest + 14 general tasks; raw lane given best-practice shell
(ls -la, find -name/-printf, du, stat).

| metric | mcp_files_* | raw shell |
|---|---|---|
| recall | 1.000 | 0.987 |
| field fidelity | 1.000 | 0.666 |
| parse success | 1.000 | 1.000 |
| error rate | 0.033 | 0.033 (intentional missing path) |
| interventions | 0 | 0 |
| latency median | 41.7 ms | 3.7 ms (python startup; SSH constant applies to both) |
| tool tokens | 18,981 objects / 12,015 rows | 7,392 |
| prompt tokens | 1,157 | 991 |

Honest read: structured tools cost ~2.4× output tokens (1.6× in rows mode)
and ~38 ms/call locally, but guarantee parse and deliver 6/6-field fidelity
vs raw's 66.6% — `find -name` yields paths only, `ls -la` loses epoch mtime
and relative paths, and `ls -lat|head` silently dropped entries (recall
0.60 on ha04). Raw's field gaps force follow-up calls in real sessions that
erase its byte advantage.

## Integration (after verifier pass)

- Host-assessment: pointer added to the deterministic lane in
  `docs/ssot/infrastructure/ssot.devnest-lanes.yml` — prefer mcp_files_*
  over ad-hoc ssh ls/find for artifact globs/unit dirs/log dirs; the skill
  itself is untracked on tony-dell, comment posted on
  `devnest-host-assessment-education-loop`.
- Node-RED/DevNest: comment posted on `node-red-devnest-visual-map` —
  observe-flow filesystem facts should use mcp_files_*.
- Job record: `docs/ssot/jobs/mcp-tools/2026-10-28-mcp-structured-files.yml`.

## Files changed

new: `scripts/mcp_debug/files_agent.py`, `scripts/mcp_debug/files.py`,
`scripts/mcp-files-verify.py`, `scripts/mcp-files-bench.py`,
`docs/ssot/jobs/mcp-tools/2026-10-28-mcp-structured-files.yml`,
`reports/mcp-files-bench-2026-10-28.{md,json}`
modified: `scripts/mcp_debug/server.py`, `scripts/devnest/lane_gate.py`,
`docs/ssot/infrastructure/ssot.mcp-debug.files.yml`,
`docs/ssot/infrastructure/ssot.devnest-lanes.yml`

## How to verify

```bash
python3 scripts/mcp-files-verify.py        # expect OK 39/39
python3 scripts/mcp-files-bench.py --reps 3  # regenerates reports/mcp-files-bench-*.md
```

Deploy note: tools appear after the next `mcp_debug` server reload/restart
(mcp-debug.sh singleton wrapper on tony-dell).
