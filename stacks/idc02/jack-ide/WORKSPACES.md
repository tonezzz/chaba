# Shared Jack OpenCode workspace

The canonical collaborative instance is `opencode-jack.surf-thailand.com`.

The runtime workspace layout is:

```text
/workspace/
├── repos/       imported repositories
├── worktrees/   per-task branches/worktrees
├── shared/      deliberate shared notes/references
├── incoming/    explicitly imported task files
└── outputs/     reports, patches, and test artifacts
```

Tony's separate fallback instance sees Jack's workspace at
`/workspace/jack-workspace`; Jack's instance sees Tony's primary workspace at
`/workspace/tony-workspace`. This mutual read/write access is intentional for
the supervised collaboration test, not a privacy boundary.

Repository promotion remains gated:

```text
import → task worktree → tests → independent verifier
→ local commit → scoped branch push → pull request
→ human review → merge/deploy
```

Never place secrets, SSH keys, browser data, provider credentials, or private
personal files in the shared workspace. Do not edit the same file concurrently.
