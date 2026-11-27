# Dispatch outcome — yomi-idc03-active-refresh-cgroup-oom (MEM-1508/1510)

Card: `yomi-idc03-active-refresh-cgroup-oom` — spec: keep `--memory=2g`,
reduce MAX_ACTIVE, per-chat unread/action ceiling, cap mcpb heap via
NODE_OPTIONS, deploy with Ansible, verify a full refresh with zero cgroup
kills.

## What happened

This dispatch started at 18:48; a parallel ops/Devin session completed the
card at 18:56–19:00 while I was diagnosing. I verified their work live
rather than duplicating it, found one residual spec gap, and landed the
missing piece on this branch.

### Verified (parallel session's work, commits 1d696bf948c + b0d60633709)

- `--memory=2g --memory-swap=2g` live on the yomi-api container
  (`podman inspect` → 2147483648; applied earlier by
  `bound-yomi-api-memory.yml`).
- MAX_ACTIVE 20→5 (`YOMI_REFRESH_MAX_ACTIVE`), per-chat ceilings in
  `update-conversations.mjs`: pages 200→5, retained messages→500,
  media→10 @ concurrency 2 (`YOMI_MAX_PAGES/MESSAGES/MEDIA_MAX/
  MEDIA_CONCURRENCY`), shared helpers in new `refresh-limits.mjs` +
  `test-refresh-limits.mjs`.
- `NODE_OPTIONS=--max-old-space-size=1536` added to `yomi-api.env`,
  container restarted 18:50:55.
- Deploy was via new gated playbook
  `ansible/playbooks/idc03-yomi-refresh-bounds.yml` (sha256 pins,
  timestamped backups under `~/.local/share/chaba-backups/`).
- Live verification at ~19:05: container cgroup `memory.events`
  `oom_kill=0`, zero `CONSTRAINT_MEMCG` kernel kills since 18:50:55, the
  18:54 timer sweep refreshed 5 heavy chats (unread 224/154/150/96/75) in
  ~93s with Result=success. Card is `done`.

### Residual gap found + fixed (this branch, commit 15560a69267)

The spec's "cap mcpb node heap via NODE_OPTIONS" was only half done:
`yomi-api.env`'s NODE_OPTIONS reaches yomi-api and `spawnNode()` children
(`env: process.env`) but NOT `run.mjs` — the MCP SDK `StdioClientTransport`
builds the child env from `getDefaultEnvironment()` (HOME/LOGNAME/PATH/
SHELL/TERM/USER only). The ~2 GiB worker that caused the kills stayed
uncapped; bounded work masks it but the ceiling itself was missing.

Changes on `dispatch/20261127-184834-keep-memory-2g-cap-bound-work-`:

- `scripts/yomi/refresh-limits.mjs`: new `mcpbTransportEnv()` →
  `NODE_OPTIONS=--max-old-space-size=<mb>` (`YOMI_MCPB_MAX_OLD_SPACE_MB`,
  default 1024, clamp 256–8192).
- All five run.mjs-spawning scripts (`update-conversations`,
  `fetch-conversations`, `download-media`, `send-message`, `yomi-login`)
  now pass `env: mcpbTransportEnv()` to `StdioClientTransport`.
- `test-refresh-limits.mjs`: +1 test (4/4 pass locally, node v26).
- `systemd/yomi-api.service`: vendored copy synced to the live unit's
  `--memory=2g --memory-swap=2g` flags (repo/live drift fix).
- `docs/ssot/jobs/infrastructure/2026-11-27-idc03-yomi-mcpb-heap-cap.yml`:
  trail incl. the corrected env-inheritance lesson.

## Deploy / verify path

No Ansible re-run needed for this delta: the scripts are read fresh per
invocation and `yomi-api.mjs` is untouched (no restart). It converges via
merge-sweep → origin/master → idc03 `chaba-repo-sync` (15-min cadence);
the next `yomi-update-active` tick picks it up. Deliberately did NOT
hot-patch the served checkout: its working tree already holds the
hot-patch that is byte-identical to the merged content (verified by
sha256), and copying divergent content would risk a `git-safe-pull`
autostash conflict.

To verify post-merge on idc03:
`podman exec yomi-api printenv` won't show it (it's per-spawn) — instead
check the next refresh's worker: `journalctl --user -u yomi-update-active`
for a clean sweep and `cat /sys/fs/cgroup/.../libpod-<id>.scope/container/memory.events`
`oom_kill` staying 0.

## Notes for reviewers

- The other session's SSOT job doc claims NODE_OPTIONS "is inherited by
  spawned ... mcpb node workers" — incorrect for MCP stdio workers; my job
  doc records the correction.
- `ansible/playbooks/idc03-yomi-refresh-bounds.yml` sha256 pins now
  intentionally mismatch `update-conversations.mjs` — re-running it fails
  safe with "update the pin in the same commit"; it was a one-shot
  incident playbook, leave as is.

lessons:
- MCP SDK StdioClientTransport does NOT inherit process.env — it uses getDefaultEnvironment() (HOME/PATH/shell vars only); env-file NODE_OPTIONS never reaches MCP workers spawned that way. Pass `env:` explicitly on the transport.
- Before implementing a dispatched card, check card comms + the target checkout's `git status`/`git diff` — a parallel session may have already hot-patched and closed it minutes earlier; verify-then-extend beats re-doing.
- Hot-patched files in the served checkout that are byte-identical to an incoming merge converge cleanly through git-safe-pull autostash; divergent hot-patches risk stash-pop conflicts — prefer letting merge+repo-sync carry follow-ups.
- `systemd/yomi-api.service` vendored copy drifted from the live unit after bound-yomi-api-memory.yml patched it in place — keep vendored copies in sync when a playbook edits a unit directly.
