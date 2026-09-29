# CMS page automation — per-page switches & knobs for Ada

Status: **P0 implemented** (this worktree). P1 (ada-pi tools) and P2 (UI)
are planned phases — see below.

## Idea

Same control shape as `cctv_wall(zone, action, screen)`: a *state store*
holds per-page automation config; a *tool* flips switches and turns knobs;
a *background worker* honors the state. Tony can say "turn off flood
updates" or "check the flood pages every hour" and Ada adjusts the page's
knobs — no code, no redeploy.

## Components

### 1. Registry (state store)

MDDB collection **`ada-cms-automation`** — one doc per CMS page slug
(key = slug). `contentMd` holds the JSON config; meta follows the memory
schema (kind=automation-config, subject=slug, status, written_by...).

```json
{
  "enabled": true,
  "label": "Bang Phli flood watch",
  "feeds": [["name", "rss-url"], ...],
  "require": "น้ำท่วม|flood|...",
  "since_hours": 72,
  "max_items": 6,
  "interval_min": 240,
  "langs": ["en", "th"],
  "run_now": false,
  "parent": "rollup-slug",
  "children": ["child-slug"],
  "last_run": "2026-09-29T00:44:00+00:00",
  "last_status": "ok",
  "last_count": 6,
  "last_duration_s": 0.4,
  "last_error": "optional — set on failed runs, cleared on success"
}
```

Switches/knobs:

| field | knob |
|---|---|
| `enabled` | master switch — timer skips disabled pages |
| `feeds` | which RSS queries drive the page |
| `require` | relevance regex (title+description) |
| `since_hours` | freshness window for items |
| `max_items` | list cap |
| `interval_min` | min minutes between auto runs (denser timers can coexist) |
| `langs` | which lang variants get the block |
| `run_now` | one-shot flag — worker runs the page next tick, then clears — **this is the Regenerate button's backend** |
| `parent` / `children` | hierarchy links — stamped onto page meta so rollups can extract children with references |

`last_*` fields are the worker's write-back — the observability Ada reads
("when did the flood page last refresh?", "how long does it cost?").
`last_duration_s` doubles as the cost telemetry for the benchmark.

Page-format and provenance details are codified in
`docs/ssot/apps/ssot.apps.cms-reports.yml` and enforced by
`cms-audit.py` R-rules (snapshot mode for CI — see
`.github/workflows/cms-audit.yml` + `scripts/ada/cms-audit-baseline.json`
ratchet).

### 2. Seed (defaults)

Repo `scripts/ada/flood-news-feeds.json` stays the git-tracked default.
Resolution order per page: **registry doc wins** (whole config), seed is
the fallback and the bootstrap source — first run of a seed page creates
its registry doc from the effective config + state.

### 3. Worker (runner)

`scripts/ada/flood-news-update.py` (systemd `ada-flood-news.timer`, 4h):

- `--all` iterates the union of seed + registry pages; `enabled: false`
  skips; `interval_min` gates runs; `run_now: true` forces once.
- Registry unreachable → seed-only mode (degrade, don't die).
- Writes `last_run`/`last_status`/`last_count` back per page; failures
  record `last_status=error` + `last_error` and clear `run_now`; a
  successful run clears `last_error`.
- Malformed registry values (e.g. `interval_min: "abc"`) warn and fall
  back to defaults rather than crashing the run.
- `--force` bypasses `interval_min` for manual runs (still honors `enabled`).

### 4. Ada tool surface (P1 — ada-pi repo)

One `cctv_wall`-style tool, added to `CMS_WRITE_TOOLS` (confirm-gated):

```
cms_automation(
  action: list | get | set | run | enable | disable,
  slug: str,
  enabled?: bool, feeds?: [[name,url]], require?: str,
  since_hours?: int, max_items?: int, interval_min?: int,
  langs?: [str], run_now?: bool
)
```

- `list`/`get` — read registry docs (voice-friendly summary: "flood-report
  is on, every 4h, last refreshed 07:44").
- `set` — merge knob changes into the registry doc (find-then-update
  semantics, same key, revision trail in MDDB).
- `enable`/`disable` — sugar over `set enabled=`.
- `run` — either sets `run_now` or subprocesses the runner on the host
  holding the chaba checkout (idc01 has `~/CascadeProjects/chaba-vault`) —
  decide during implementation; subprocess gives true "update it now".
  The same `run_now` flag is what a ⟳ Regenerate button in the Ada PWA /
  chaba-admin writes — one backend, three surfaces (voice, UI, timer).

Same change in P1: `cms_publish_page` stamps the schema meta fields
(bank/scope/status/source/written_by/subject/attribute/valid_from/
last_verified) at write time so new pages arrive already conformant.

### 5. Scenario + verify

- ada-pi `tests/scenarios/*.yaml`: `cms_automation_toggle` — enable→set→
  disable→run_now cycle against FakeMddb.
- Live: flip `enabled` on a scratch page via the tool, watch the timer run
  skip it, `last_status` stays stale; re-enable, see `run_now` fire.
- `scripts/ada/flood-news-update.py --all --dry-run` prints per-page
  resolution (seed vs registry) and gating decisions.

## Phases

| phase | scope | where |
|---|---|---|
| P0 | registry-aware runner, state write-back, interval gating, --force | this worktree — DONE (enabled/interval/run_now all verified live) |
| P0b | report standard (ssot.apps.cms-reports.yml), provenance meta + hierarchy stamping, `last_duration_s`, cms-audit R-rules + snapshot/baseline CI | this worktree — DONE |
| P1 | `cms_automation` tool, `cms_publish_page` schema stamping, scenarios, ⟳ Regenerate button in the PWA | ada-pi worktree — new dispatch |
| P2 | `command`-kind generators in the registry (regenerate non-feed reports: ops-report etc.), denser dispatcher timer, chaba-admin toggles | later |

## Decisions

- Registry lives in MDDB, not a repo file — "MDDB is the mutable current
  truth"; Ada already reads/writes it; git repo can't be mutated by voice.
- One registry doc per page (not one mega-doc): find-then-update
  semantics and MDDB revision history stay per-page.
- `enabled` is honored even by `--force` — a manual run must not
  silently resurrect a page the operator switched off.
