# Dispatch outcome — gh-radar watchlist seed (2026-11-25)

## What was done

Seeded the gh-radar watchlist as `groups -> repos` from live GitHub
data, and recorded the surface/scheduler decision in chaba (the
gh-radar repo itself is a standalone checkout at
`~/CascadeProjects/gh-radar` on tony-omen, unreachable from this
dispatch worktree).

## Deliverables (commit 8043f040d1b on dispatch/20261125-205450-…)

- `stacks/tony-omen/gh-radar/watchlist.yml` — canonical seed, 46 repos
  in 3 groups:
  - `starred` (5): live pull of api.github.com/users/tonezzz/starred —
    nazirlouis/ada_v2, Sompote/Tiger_bot, mythrantic/ollama-docker,
    openinterpreter/openinterpreter, camenduru/gpt4all-colab
  - `fork-upstreams` (30): parent.full_name resolved via
    api.github.com/repos/tonezzz/<fork> for every fork — watches
    upstreams (incl. nazirlouis/ada-pi, tradik/mddb,
    run-llama/llama_index, NVIDIA/personaplex, PyThaiNLP/pythainlp),
    not the stale forks themselves
  - `stack-tools` (11): upstreams verified 200 on the API and tied to
    repo SSOT/stacks — ollama, openchamber, anomalyco/opencode
    (sst/opencode 301s there), home-assistant/core, weaviate,
    github/github-mcp-server, modelcontextprotocol/{servers,registry},
    erebe/wstunnel, esphome, blakeblackshear/frigate
- `stacks/tony-omen/gh-radar/stack.yml` — stack declaration: units,
  state paths, restore steps, verify command; notes the surface split.
- `docs/ssot/jobs/infrastructure/2026-11-25-gh-radar-watchlist-seed.yml`
  — job/decision record with seed sources and follow-ups.

## Decision recorded

- systemd `--user` `gh-radar.timer` on tony-omen (daily 07:20,
  Persistent) = authoritative scheduler.
- OpenChamber on tony-dell = interactive surface only
  (`bin/gh-radar-leaf.py`, manual-only pending Tony review).

## Result / how to verify

- `python3 -c "import yaml; yaml.safe_load(...)"` on all three files —
  parsed; pre-commit SSOT validation + optimization gate passed.
- Watchlist counts: `grep -c '^    - ' stacks/tony-omen/gh-radar/watchlist.yml`
  → 46 repo lines across 3 groups.
- Card comms posted at start and end.

## Follow-ups (not doable from this worktree)

- Deploy: copy `stacks/tony-omen/gh-radar/watchlist.yml` →
  `~/CascadeProjects/gh-radar/watchlist.yml` on tony-omen.
- PR tonezzz/chaba#164 (ssot.jobs.yml + audit.hosts.yml declaration
  for gh-radar units) still open since 2026-11-12 — merge or close;
  stack.yml notes reference it.

lessons:
- gh-radar's repo is standalone on tony-omen, not in chaba — dispatches
  scoped to a chaba worktree can only seed canonical config here; host
  deploy stays a follow-up.
- api.github.com unauthenticated works for public starred/fork-parent
  resolution — no token needed for watchlist seeding.
- sst/opencode redirects (301) to anomalyco/opencode — use the
  anomalyco/ owner/repo in watchlists.
