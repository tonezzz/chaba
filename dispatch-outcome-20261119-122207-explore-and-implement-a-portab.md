# dispatch-outcome — devnest-info-find-skill (Phase 1)

## What changed

Implemented Phase 1 of the portable DevNest info-find capability
(Tony's answered request: **conversational skill first** — no queued
research executor this phase). Commit `159234cdab` on branch
`dispatch/20261119-122207-explore-and-implement-a-portab` — **not
pushed** (card spec does not request it).

- **`scripts/devnest/info_find.py`** — shared planner + source
  adapters, stdlib-only CLI (`plan` / `run` / `record`). Classifies
  intent (mcp / service-health / ssot / code / web / explore /
  general-doc), fans out across:
  - `ssot` + `code` — rg when present, stdlib walker otherwise
    (`INFO_FIND_RG` overrides)
  - `health` — `ssot*health*.yml` lookup; `--probe-health` GETs ≤5
    declared URLs, 4s timeout
  - `mddb` — `/health` preflight over `INFO_FIND_MDDB_URLS` (default
    `127.0.0.1:11027` → `100.102.134.91:11027` cms bank), then
    `POST /v1/vector-search` per collection; per-bank and
    per-collection failures are recorded, never fatal
  - `mcp` — parses `**/ssot.mcp-tools.yml` policy domains, emits
    `deferred` steps for the agent layer (never calls MCP itself)
  - `web` — `deferred` unless `INFO_FIND_WEB_CMD` names a pluggable
    adapter; `--web-json <file>` merges external hits into the ranker
  Merged output: `results[]` ranked (mddb → web → ssot → health →
  code), deduped by `(source, ref)`, each with `source`/`ref`/
  `excerpt`/`score`/`rank`. Cache + audit isolated under
  `~/.cache/devin/info-find/<project>/sessions/<session>/`
  (`INFO_FIND_CACHE_BASE` override); project = `--project` >
  `INFO_FIND_PROJECT` > git remote basename > cwd basename (dispatch
  worktrees resolve to `chaba`); session = `--session` >
  `DEVIN_SESSION_ID` > `$TASK_DIR` basename > pid.

- **`.agents/skills/info-find/SKILL.md`** — portable cross-agent skill
  package (agentskills folder standard): run the script, service
  deferred rungs with the agent's own tools, cite every claim, close
  the audit. Legacy `.devin/skills/info-find/` untouched (duplicate
  skill names across `.agents`/`.devin` are already the norm here).

- **`evals/opencode-lane/profiles/info-find/`** — the "one read-only
  DevNest agent lane" exposure: opencode task profile (S1–S3,
  read_only/report/diagnosis), bash allowlisted to exactly
  `python3 scripts/devnest/info_find.py`, no writes/webfetch/secrets,
  MCP limited to the SSOT/education read-only subset. Fixture:
  `task.yaml` artifact contract, `prompt.md`, held-out `verify.py`
  (repo-path citations must resolve; `mddb://`/URL refs format-checked;
  a deferred rung cannot be claimed as consulted).

- **`evals/opencode-lane/jobs/p1-info-find-tony-omen.yaml`** — S1
  supervised canary envelope ready for the pilot (heartbeat required;
  `OPENCODE_LANES=1` env gate per stage rules).

- **`tests/devnest/test_info_find.py`** — 15 tests: routing matrix +
  plan flags, dead-MDDB fallback (partial results still returned),
  dedupe/rank/citation shape, project+session isolation, TASK_DIR
  fallback, no-rg stdlib path, MCP policy parse.
  `test_opencode_profiles.py` expected profile/envelope lists updated.

- **`docs/ssot/jobs/devnest/2026-11-19-info-find-skill.yml`** —
  capability gate doc: admitted/denied surfaces, source contract
  (statuses, rank order, deferred rungs), env overrides, verification,
  Phase-2 follow-ups.

## Result / verification

- `python3 -m pytest tests/devnest/` — **278 passed** (incl. 15 new)
- `opencode_profiles.py lint info-find` — ok; `check` + `render` of
  the pilot envelope — clean; `lane_gate.py lint` — ok
- Fixture verifier: pass on honest artifact, fail on a deferred rung
  claimed as consulted
- Live run on tony-omen: `run --query "kanban card write path"` →
  mddb hits (infrastructure-ssot, score 0.68) ranked above ssot/code;
  plan/result caches + audit.ndjson under
  `~/.cache/devin/info-find/chaba/sessions/test1/`

Pre-existing, unrelated: `scripts/ssot-prose-smell.py` flags a YAML
parse error in `docs/ssot/jobs/infrastructure/
2026-11-19-board-api-commit-outside-lock.yml` (another session's file).

lessons:
- `opencode_profiles.py` subparser pattern: shared arg groups must be
  added per-subparser — `record` crashed on missing `cache_base` attr;
  use getattr defaults.
- `test_opencode_profiles.py` hardcodes profile count + job-envelope
  count and per-host envelope names — adding a profile or p1 job
  requires updating the expected lists.
- Pre-commit fast gate runs `pytest tests/devnest` (≤15s budget) —
  keep new tests fast.
- MDDB on tony-omen: only idc03 tailnet banks reachable
  (`100.102.134.91:11023` main / `:11027` cms); no local mddb.
- In a dispatch worktree, project name must come from `git remote
  get-url origin` basename, not cwd — cwd is the worktree dir name.
