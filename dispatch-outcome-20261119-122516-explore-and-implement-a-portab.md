# dispatch-outcome: devnest-info-find-skill (DEV-0230)

## What shipped (Phase 1 — conversational skill first, per Tony's answer)

- **`scripts/devnest/info_find.py`** — shared, stdlib-only planner +
  source adapters + CLI (`plan|run|record|mddb-health|mcp-policy`).
  Intent routing ports the `.devin` Node planner's table **and adds the
  `explore` intent the old planner documented but never implemented**
  (internal sources → GitHub precedent rung → generic web). `run`
  executes locally-runnable sources (ssot, code, health, MDDB via
  `/health` + `/v1/search`, MCP-policy extraction from
  `ssot.mcp-tools.yml`) and emits one ranked, cited result JSON with a
  per-source status map (`ok|skipped|deferred|unavailable|error` +
  reason). Agent-tool sources (web, github) are `deferred` for a
  conversational agent or `unavailable` under `--offline`.
- **`.agents/skills/info-find/SKILL.md`** — portable agentskills-format
  skill driving the shared module; agent-agnostic wording for the
  MCP/web/github steps; documents the isolation + fail-safe contracts.
  `.devin/skills/info-find/SKILL.md` untouched except a pointer note.
- **`evals/opencode-lane/profiles/info-find/`** — new read-only
  OpenCode profile (stages `[S1]` only, matching the live supervised
  stage). Bash allowlist = `info_find.py` + hostname/date; no
  write/edit/patch/webfetch; MCP ceiling = the 5 read-only retrieval
  tools. Message-mode JSON artifact + `fixture/verify.py` held-out
  verifier (citation resolvability, status hygiene, rank order,
  session-isolation). Canary envelope:
  `evals/opencode-lane/jobs/p1-info-find-idc02.yaml`.
- **`tests/devnest/test_info_find.py`** — 23 tests covering routing,
  fallback, citations, session isolation, and lane packaging
  (profile lint, read-only surface, verifier pass/fail paths, envelope
  lint). All pass.
- **Docs** — `docs/ssot/jobs/devnest/2026-11-19-info-find-skill.yml`
  (capability gate: who may invoke, what it may touch, fail-safe +
  isolation contracts, Phase-2 boundary); profile row added to
  `evals/opencode-lane/PROCEDURE.md`; reference added to
  `ssot.devnest-lanes.yml`.

## Verified

- `opencode_profiles.py lint info-find` / `lint all` → ok;
  `lane_gate.py lint` + `opencode_profiles.py check` on the canary
  envelope → ok; `render` produces a valid opencode.json (generic
  agents disabled, MCP elided where no proxy).
- `python3 -m unittest tests.devnest.test_info_find` → 23/23 OK.
- Live smoke on tony-macbook: `run` reached the idc03 MDDB cms bank
  (20 docs over 4 collections), ssot/code adapters returned cited repo
  results, worktree resolved to project `chaba`, cache/audit landed
  under `~/.cache/devin/info-find/chaba/sessions/<id>/`.
- **Not yet run:** the S1 canary envelope itself — needs a supervised
  host with `OPENCODE_LANES=1` (a human watches per lane_gate S1);
  that is the pilot step, flagged in the job doc.

## Phase boundary / open items

- Phase 2 (queued card research executor) deliberately NOT built — the
  card's open decision was answered "conversational skill first". When
  it lands it must reuse `info_find.py`, not re-route.
- Pre-existing (not mine): `ssot-prose-smell.py` flags a YAML parse
  error in `docs/ssot/jobs/infrastructure/2026-11-19-board-api-commit-
  outside-lock.yml` — file is clean in git, error is upstream.

## How to verify

```
python3 -m unittest tests.devnest.test_info_find
python3 scripts/devnest/info_find.py run --query "<q>" --session demo
python3 scripts/devnest/opencode_profiles.py lint info-find
```

lessons:
- ssot.devnest-lanes.yml reference entries must use `>-` folded scalars for multi-line text — plain continuation lines at list-item indent break YAML.
- `check_envelope`/`lint`/`render` from opencode_profiles.py validate a profile+envelope fully offline; `run` is the only step needing a live host.
- info_find tests: intent "ssot" does NOT route the code adapter — assert on a source the query actually routes to, and patch DEFAULT_MDDB_URL to 127.0.0.1:1 for hermetic fallback tests (real bank is reachable on tailnet and will slow tests).
- MDDB /v1/search returns `contentMd` (not `text`) and meta values are single-element lists (`original_path[0]`, not `meta.path`).
- Worktree checkouts resolve their project name via the `.git` pointer file (`<main>/.git/worktrees/<n>` → parents[2]), not the dir basename — needed or every dispatch worktree becomes its own cache "project".
