# Ada "what can you do" verb — read-path contract

Card `ada-tools-command-reference`, part 2 (ADA-1285). When Tony asks Ada
*what she can do*, the answer comes from the **generated snapshot** —
sub-second, deterministic, and never computed live. This file is the
contract the producer and consumer both code to; the ada-voice wiring
(card follows there) only has to satisfy it.

## Producer / consumer split

```
ada-voice decls ──► tools-commands-catalog.py (chaba) ──► ada-tools-commands.json ──► ada_capabilities consumer
 realtime_provider.py        runs on decl change,          machine snapshot            inside ada-voice:
 tools.d/* + manifest.yml    same triggers as tool-lint,   checked into chaba,         one cached file read,
 tool_guide.yml, _ALIASES,   --check is the drift gate     transported to ada-voice    template answer out
 ssot.tool-surface.yml,                                               at deploy
 scenarios-live/*
```

- **Producer**: `scripts/ada/tools-commands-catalog.py` (this repo).
  Emits `docs/kb/ada-tools-commands.json` (machine) +
  `docs/kb/ada-tools-commands.md` (human review). Re-run whenever a
  declaration source changes; `--check` fails CI/lint when the committed
  outputs drift.
- **Transport**: the snapshot reaches ada-voice as a *file* — vendored
  at deploy time (e.g. `deploy-ada.sh` copies it to
  `backend/data/ada-tools-snapshot.json`). No second parser inside
  ada-voice: the JSON *is* the single source, per the producer/consumer
  rule.
- **Consumer** (recommended shape): a `ada_capabilities` tools.d drop-in
  — `policy=read`, `secondary_allowed=true`, `timeout_s=5` — that loads
  the JSON once per file mtime (same cached-loader pattern as
  `_tool_guide()` in `tool_runner/common.py`) and answers from a fixed
  template. An instruction-side fast path is a valid alternative; the
  contract below applies either way.

## Snapshot contract (`schema: 1`)

`ada-tools-commands.json` fields the consumer may rely on:

| field | meaning |
|---|---|
| `generated_at`, `source.head`, `source.head_date`, `source.behind` | provenance — "as of" lines |
| `counts` | `{builtin, dropin, guest, aliases, families, count_cap, target_count}` |
| `tools[]` | `{name, layer, purpose, description, backend, registry, policy, timeout_s, secondary, schema, guide, triggers[], last_changed, family, source_file}` |
| `aliases` | `{absorbed_name: canonical}` — internal compat map |
| `families` | `{fam: {canonical, absorbed[], status, merge_card, scenario}}` — merge-family status |

Rules: tolerate missing optional keys (`triggers`, `family`, …) and
ignore unknown future keys; bump `schema` on any breaking change.

## Behavior spec

- **Intents**: "what can you do", "what tools do you have", "list your
  capabilities", "what commands", "help".
- **Answer shape** (deterministic template):
  1. One line: `I have N capabilities — M core + K add-on tools — as of
     <source.head_date>.`
  2. A grouped headline list (~6–8 groups) derived deterministically
     from `family`/name-prefix: memory, calendar & tasks, home control,
     cameras & screens, kanban & jobs, docs & CMS, news & reports,
     media & rendering, misc.
  3. Offer: `ask me about a specific tool or area for details`.
- **Detail mode**: given a tool or family name, read `purpose`,
  `triggers`, `policy` from `tools[]`/`families`.
- **Canonical names only**: absorbed alias names are never presented as
  capabilities — `_ALIASES` is back-compat routing, not surface.
- **Latency**: one cached file read + template fill. No network, no
  model calls, no AST, no `mcp_list_tools`. Target < 50 ms p95.
- **Determinism**: identical snapshot → byte-identical answer (sorted
  groups; the only volatile values echoed are `generated_at` /
  `head_date`).

## Failure modes

- Missing/corrupt snapshot → `ok:false` *"capability list not generated
  — run the catalog producer"*; never fabricate a list.
- `source.behind` > 0 or `generated_at` > 30 d old → still answer, with
  an "as of `<head_date>`" caveat, and log drift.
- `schema` major bump → refuse with the version note (no silent
  misread).

## Non-goals

- Not a live inventory — no MCP probing, no manifest re-parse at call
  time.
- Not a permission oracle — it reports the *declared* surface; the
  gates still decide each call.
- No token/cost metering — the cost column is static policy metadata
  (policy, timeout, schema tier, guide presence).

## Wiring checklist (ada-voice follow-up card)

- `backend/tools.d/ada_capabilities.py` + manifest row
  (`policy=read`, `secondary_allowed=true`, `timeout_s=5`).
- Snapshot path `backend/data/ada-tools-snapshot.json`, refreshed by
  `deploy-ada.sh` (copy chaba's generated JSON — single transport, one
  direction).
- Routing blurb in `DECLARATION` (≤300 chars per
  `ssot.tool-surface.yml`): *"what Ada can do — capability list, tools
  and triggers"*.
- Tests: fixture snapshot → canned-answer assertions; missing file →
  `ok:false`; scenario `tests/scenarios-live/capabilities.yaml` so the
  tool leaves `coverage_debt` at creation.
