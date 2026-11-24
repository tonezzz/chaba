# Dispatch outcome — jack-shared-workspace-repo-promotion

Card: `jack-shared-workspace-repo-promotion` — use `opencode-jack.surf-thailand.com`
as the canonical shared instance; organized `/workspace`; gated
commit/push/PR flow without GitHub credentials in the container.

## What changed (commit f1ec86a574 on dispatch/20261124-185214-…)

**New: `stacks/idc02/jack-ide/lane/` — the operator promotion lane**

- `jack-task.py` — host-side CLI (install as `~/.local/bin/jack-task` on
  idc02). Subcommands: `init`, `repos`, `import`, `new`, `status`,
  `verify`, `push`, `pr`.
  - `import` clones only repos in an operator allowlist
    (`~/.config/jack-ide/repos.json`).
  - `new <repo> <slug>` creates `worktrees/<repo>--<slug>` on branch
    `jack/<slug>` from `origin/<default>` and writes a task manifest under
    `outputs/lane/tasks/`.
  - Jack works + makes **local commits** inside the container worktree;
    the container still has no push capability (no creds mounted).
  - `verify` is the independent gate: worktree identity, `jack/` branch
    scope, clean tree (all changes committed), merge-base check,
    forbidden-path rejection (`.env*`, `*.pem`, `id_rsa*`, `.npmrc`, …),
    secret-pattern scan of added diff lines, and an optional test command
    run with a scrubbed environment. Writes `verdict.json` per task.
  - `push` refuses without a passing verdict matching HEAD, only ever
    pushes `jack/<slug>`, confirms the remote sha via `ls-remote`, and
    injects `JACK_GIT_TOKEN` per-command via `http.extraHeader` — never
    persisted, never for non-github.com remotes.
  - `pr` opens a GitHub PR via REST with the same scoped token; idempotent
    (returns existing PR URL); merge/deploy are never touched.
- `repos.example.json` — allowlist format (`name`, `url`, optional
  `default_branch`).
- `jack-git.env.example` — `~/.config/secrets/jack-git.env` holding
  `JACK_GIT_TOKEN` (fine-grained PAT, pilot repos only, Contents+PR RW).

**Updated stack files**

- `jack-opencode.container` — added the supervised-test mount
  `%h/.local/share/jack-ide/tony-workspace:/workspace/tony-workspace:Z`
  (replaces the retired tony-ide path with a declared dir under jack-ide
  state); header comment documents the no-GitHub-creds boundary.
- `WORKSPACES.md` — rewritten: canonical instance, current Tony<->Jack
  mutual-access model, full lane pipeline doc.
- `README.md` — "Promotion lane (jack-task)" section: install, config,
  credential model, test command.
- `stack.yml` — secrets/state entries for `jack-git.env`, `repos.json`,
  `tony-workspace`, `~/.local/bin/jack-task`.

**Tests + trail**

- `tests/jack/test_jack_task.py` (+ `__init__.py`) — 16 unittest cases
  over real local-git fixtures (bare origin → clone → worktree → commit →
  verify → push → manifest). All pass: `python3 -m unittest
  tests.jack.test_jack_task`.
- `docs/ssot/jobs/infrastructure/2026-11-24-jack-shared-workspace-promotion-lane.yml`
  — job lifecycle doc (planning/processing/followup/report).

## Result / state

- Repo-side deliverable complete and committed on the dispatch branch
  (pre-commit SSOT gates passed). **Not deployed** — per dispatch rules.
- The Tony fallback OpenCode instance was already retired 2026-11-03
  (commit 31380302bb); nothing to keep or delete. WORKSPACES.md now says
  separate instances are fallback-only pending a new decision.
- Canonical instance `opencode-jack.surf-thailand.com` was already live
  (Caddy + CF Access + enroll gateway verified in repo config).

## Operator steps remaining on idc02 (human gate)

1. `install -Dm644 lane/repos.example.json ~/.config/jack-ide/repos.json` — edit in pilot repo(s).
2. `install -m600 /dev/null ~/.config/secrets/jack-git.env` — mint a fine-grained PAT (pilot repos, Contents+PR RW), set `JACK_GIT_TOKEN`.
3. `install -m755 lane/jack-task.py ~/.local/bin/jack-task && jack-task init` (creates layout + `tony-workspace` mount source).
4. Copy updated `jack-opencode.container` to `~/.config/containers/systemd/`, `systemctl --user daemon-reload && restart jack-opencode`.
5. Pilot per card help: one toy/private repo, one Jack task branch,
   deterministic tests (`--test`), verify verdict, local commit, push, PR —
   merge stays manual.

## How to verify

- `python3 -m unittest tests.jack.test_jack_task` → 16 tests OK.
- `python3 -m py_compile stacks/idc02/jack-ide/lane/jack-task.py`.
- YAML: `stack.yml` + job doc parse clean (pre-commit SSOT validation passed).
- Live: after deploy, `jack-task status` + `curl :8377/health`.

lessons:
- Python `str.lstrip("./")` strips characters, not the prefix — `".env"` became `"env"` and escaped the forbidden-path gate; a path-prefix strip (`s[2:] if s.startswith("./")`) plus a dedicated test caught it.
- Informal "info" dicts in an `all(g.get("pass", ...))` verdict need an explicit `pass`/`status` key or they silently fail the gate — give informational entries `pass: True`.
- YAML plain scalars in block sequences break on embedded `: ` and unterminated quotes — quote multi-line list items that contain colons.
- pytest is not installed on this host; `python3 -m unittest` runs the repo's unittest-style tests fine.
