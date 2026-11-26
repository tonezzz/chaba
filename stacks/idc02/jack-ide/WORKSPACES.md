# Shared Jack OpenCode workspace

The canonical collaborative instance is `opencode-jack.surf-thailand.com`
(idc02, behind the jack-enroll gateway + Cloudflare Access). The separate
Tony OpenCode instance was retired 2026-11-03; separate instances remain an
option only as fallback — do not resurrect one without a new decision.

The runtime workspace layout is:

```text
/workspace/
├── repos/       imported repositories (operator allowlist only)
├── worktrees/   per-task branches/worktrees (jack/<slug>)
├── shared/      deliberate shared notes/references
├── incoming/    explicitly imported task files
├── outputs/     reports, patches, test artifacts
│   └── lane/    jack-task state: repos.json + tasks/<slug>.json + verdicts
└── tony-workspace/  Tony's supervised-test drop dir (host:
                     ~/.local/share/jack-ide/tony-workspace)
```

Tony and Jack may read/write each other's workspaces during the supervised
test: Jack sees Tony's drop dir at `/workspace/tony-workspace`, and Tony
reaches Jack's whole workspace on the host at
`~/.local/share/jack-ide/workspace`. This mutual access is intentional for
the test, not a privacy boundary.

## Promotion lane (operator-run, host side)

The container holds no GitHub credentials. Promotion is a gated pipeline
driven by `lane/jack-task.py` (installed as `jack-task` on idc02):

```text
jack-task init                          # layout + /workspace/AGENTS.md rules
jack-task import <name>                 # allowlisted clone -> repos/<name>
jack-task new <repo> <slug> [--test CMD] # worktree + jack/<slug> branch
#   ... Jack edits and makes LOCAL commits inside the worktree ...
jack-task verify <slug>                 # secret/scope/clean-tree/test gates
jack-task push <slug>                   # scoped-token push of jack/<slug> only
jack-task pr <slug>                     # GitHub PR via scoped token
#   ... human review -> merge -> deploy (never automated) ...
```

Verify is the independent gate: it requires a clean tree (everything
committed locally), scans added diff lines for secret shapes, rejects
credential-looking paths (`.env*`, `*.pem`, `id_rsa*`, …), optionally runs
the declared test command with a scrubbed environment, and records a
verdict. `push` refuses without a passing verdict matching HEAD and only
ever pushes `jack/<slug>` — never the default branch. `pr` needs the
pushed branch and opens a reviewable PR; merge stays a human gate.

Credentials: `~/.config/jack-ide/repos.json` (import allowlist) and
`~/.config/secrets/jack-git.env` (`JACK_GIT_TOKEN`, a fine-grained PAT
scoped to the pilot repos — see `lane/jack-git.env.example`). The token is
injected per-command via `http.extraHeader` and never persisted into repo
config or the container.

Never place secrets, SSH keys, browser data, provider credentials, or private
personal files in the shared workspace. Do not edit the same file concurrently.
