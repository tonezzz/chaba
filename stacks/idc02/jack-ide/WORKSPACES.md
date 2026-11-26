# Shared Jack OpenCode workspace

> **Status 2026-11-26:** the jack-ide quadlets (`jack-opencode`,
> `jack-enroll`, `jack-ide-network`) and the public Caddy routes were
> retired on idc02 on 2026-11-24 together with the ada-code stack; state is
> backed up at `~/backups/retired-opencode-20261124/jack-ide` on idc02 and
> the quadlet sources remain in this directory. Everything below is the
> restore-ready design — do not treat the instance as live until the units
> are re-deployed (a separate operator decision).

The canonical collaborative instance is `opencode-jack.surf-thailand.com`
(idc02, behind the jack-enroll gateway + Cloudflare Access). The separate
Tony OpenCode instance was retired 2026-11-03; separate instances remain an
option only as fallback — do not resurrect one without a new decision.

The runtime workspace layout is:

```text
/workspace/
├── repos/       imported repositories (operator allowlist only)
├── worktrees/   per-task branches/worktrees (jack/<slug>)
├── projects/    ad-hoc scratch project dirs (`jack-task project`)
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

## Opening a project in the OpenCode UI

Verified against opencode 1.19.4 (the retired container image) and 2.4.1
(the current host `opencode serve` line):

- **The UI cannot create directories.** There is no mkdir / create-project
  API. The folder picker browses existing directories only — resolving a
  missing path fails (`LocationNotFoundError` on v2; the v1 picker simply
  shows nothing to select). Sessions *can* be created against a
  not-yet-existing path via the API, but the UI cannot open/browse it
  until the directory exists on disk.
- **Project identity:** a directory containing `.git` becomes its own
  project (canonical = repo root; linked worktrees register as the parent
  project's `sandboxes`). A non-git directory becomes a project unto
  itself on v2, or folds into the single `global` project (worktree `/`)
  on v1.
- **Safe create path:** `jack-task project <slug>` (alias `scratch`)
  creates `/workspace/projects/<slug>` — slug-validated, refuses
  overwrites, refuses a symlinked `projects/` dir, never accepts host
  paths. Repo-backed work uses `import` (allowlist) + `new` (worktree)
  instead. After creating, open `/workspace/projects/<slug>` (or the
  worktree path) in the UI picker.
- **`external_directory` caution:** on v1 the container's
  `external_directory: deny` confines agent file tools to the project
  worktree (+sandboxes). A session scoped to `repos/<name>` or a
  `worktrees/<repo>--<slug>` worktree therefore CANNOT read
  `/workspace/AGENTS.md`, `shared/`, `incoming/`, or write `outputs/` —
  exactly the files the lane workflow needs. Keep repo-scoped sessions on
  the `global`/workspace-root project, or relax the rule to allow
  `/workspace/AGENTS.md` + `outputs/` explicitly if per-repo projects are
  wanted. On v2 the equivalent is the `permissions` ruleset action
  `external_directory` ("any access outside the Location or worktree");
  note the live `opencode-serve` config still uses the deprecated v1
  `permission` key — verify which key the running version honors before
  relying on it.

Never place secrets, SSH keys, browser data, provider credentials, or private
personal files in the shared workspace. Do not edit the same file concurrently.
