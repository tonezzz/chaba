# New Host Onboarding — Standard Procedure

How a fresh machine becomes a first-class Chaba node. Written from the
tony-macbook run (2026-10-11); follow top-to-bottom. Every step is
user-level unless marked **[sudo]** or **[Tony]** (needs his hands/password).

## 0. Orientation (read first)

- Fleet SSOT: `docs/ssot/infrastructure/ssot.host-capacity.yml` (capacity + mesh membership),
  `ssot.host-roles.yml` (roles/offload), `ssot.audit.hosts.yml` (expected services),
  `ssot.secrets.policy.yml` (secret roots), `ssot.kanban.yml#runner_fleet` (dispatch lanes).
- Per-host system page: `docs/ssot/ssot.mysystem.<host>.yml` — keep it live; it is the
  host's status page, not a one-time record.
- Placement decisions go through `host-capacity.yml#placement_policy` — nothing lands
  "by convenience".

## 1. Base provisioning

- OS installed, hostname set, user `tony`, tailscale up with **its own node identity**
  (never reuse a stick identity — `docs/kb/mn01-stick-standard.md`).
- Verify: `tailscale status` shows the host; ping a peer.
- **[Tony]** WiFi join once (no PSKs are recoverable from anywhere — this is always manual).
- **[sudo]** `ufw` per `ssot.security.<host>.yml` (sshd only on LAN+tailnet is the norm).
- If devin-desktop: `bash scripts/devin/install-devin-host.sh` — apparmor profile is the
  only sudo step; watchdog + cron are user-level (devin-desktop runs fine without the
  profile on most hosts — install it if renderer crashes appear).

## 2. SSH mesh (both directions)

- Inbound: seed `~/.ssh/authorized_keys` with fleet keys (standard set: omen's
  `id_ed25519_macbook`-style key, dell `mcp-debug@`, dell `cascade`).
- Outbound: `ssh-keygen -t ed25519` if no key, then push the pubkey to every host in
  `host-capacity.yml hosts:` — fastest is via a host that already reaches them:
  `ssh tony-dell 'for h in tony-omen idc02 idc03 mn01; do ssh $h "echo <pubkey> >> ~/.ssh/authorized_keys"; done'`
- `ssh-keyscan -t ed25519 <all fleet hosts> >> ~/.ssh/known_hosts` — first BatchMode
  contact dies silently without this.
- Also add the host's own pubkey to its own `authorized_keys` + `ssh-keyscan localhost`
  (lets ssh-mesh-sync run correctly from the host itself).
- Register: add `hosts:` entry in `ssot.host-capacity.yml`; only hard-exclude in
  `scripts/ops/ssh-mesh-sync.sh` when a host genuinely can't participate (michael-ha).
- Verify: `ssh -o BatchMode=yes <each host> hostname` succeeds.

## 3. Repo + toolchain

- Clone `~/CascadeProjects/chaba` (remote `tony-dell:CascadeProjects/chaba-tony-dell` —
  needs the ssh edge from step 2 first).
- `bash scripts/install-hooks.sh` in the clone — arms pre-commit checks + rebase pulls
  (single-writer rule: every checkout gets armed once).
- Git identity: repo-level `user.name=Devin Fleet`, `user.email=devin-fleet@chaba.local`
  (dispatch commits carry this).
- Node: user-space tarball to `~/.local/node` + symlinks in `~/.local/bin`
  (`ssot-validate-all.mjs` and dispatched script tasks need it; no sudo required).
- `mkdir -p ~/.config/secrets && chmod 700` — the only sanctioned secret root
  (`ssot.secrets.policy.yml`); copy only what the host's role needs over ssh
  (e.g. `ha-michael-dev.env` for HA dev work). Never commit, never echo.

## 4. Devin satellite layer

- `scp tony-dell:~/.config/devin/scripts/*.sh ~/.config/devin/scripts/` and
  `mcp-scripts/*` → same paths (repo `.devin/config.json` hooks point at
  `~/.config/devin/scripts/`).
- `~/.config/devin/mcp_config.json`: start from dell's, then per entry —
  - **URL-type** (`mddb`, `alphavantage`, `home-assistant`, `michael-*`): verbatim;
    tailnet URLs resolve anywhere. Check for stale IPs — MDDB leader is **idc03
    (100.102.134.91:9000/mcp)** since the migration.
  - **Command-type that execs locally on dell** (github, postgres, yomi, notebooklm,
    docs, docs-trade, mcp-llama, mcp-weaviate): rewrite to
    `ssh -o BatchMode=yes tony-dell '<original invocation>'` — a satellite host re-execs
    on the control plane instead of re-installing servers+deps.
  - **Already-ssh wrappers** (mcp-debug, mcp-health, mcp-focus, workflows, mcp-gpu):
    verbatim — they ssh from wherever they run.
  - **playlive**: runs locally; repoint `PLAYLIVE_HOSTS_FILE` to the local clone.
- Hygiene timers (create in `~/.config/systemd/user/`): `devin-cleanup.timer`
  (weekly sessions.db prune via `scripts/prune-devin-sessions.sh`),
  `devin-session-prune.timer` (dispatch session GC, `session-prune.py --days 14`),
  `devin-dispatch-watch.timer` (5-min), `devin-dispatch-prune.timer` (weekly).
  Dell-scoped jobs in `ssot.jobs.yml` (devin-summaries-sync, session-audit…) do NOT
  get replicated — they read dell's local ledger.
- **[Tony]** `devin auth login` once — session tokens do NOT port between hosts:
  `credentials.toml` copied from another host reports "not logged in" even though
  identical. Until done, dispatch-type cards can't run on this host.

## 5. Runner enrollment (if the host takes kanban work)

- Install `scripts/devin/devin-dispatch{,-watch,-prune}.sh` → `~/.local/bin/` and
  `dispatch-repos.conf` → `~/.local/share/devin-dispatch/repos.conf`.
- `runner-agent.service`+`.timer` (oneshot every ~60s): `RUNNER_CAP`, `RUNNER_LABELS`
  per the hardware doc / placement policy.
- Mirror cap+labels in `ssot.kanban.yml#execution.concurrency.runner_fleet` prose —
  fleet-health parses it.
- Task types: `dispatch` needs the devin login; `container` needs podman;
  `script` needs only git+the toolchain — a host can run script-only while pending.
- Verify: `journalctl --user -u runner-agent` clean passes; the runner reports
  capacity on the board.

## 6. SSOT registration (same commit as the code changes)

- `ssot.host-capacity.yml` hosts: entry (role, cores/mem/disk, gpu, note).
- `ssot.kanban.yml` runner_fleet prose.
- `ssot.mysystem.<host>.yml` — installed/pending sections current.
- `ssot.audit.hosts.yml` + `scripts/audit-hosts.py` HOSTS entry.
- `ssot.security.<host>.yml` posture file + index row.
- `ssot.host-roles.yml` block (offload eligibility, headless/web-preview flags).
- `node scripts/ssot-validate-all.mjs` before commit.
- Commit, push; then `ssh tony-dell 'cd ~/CascadeProjects/chaba-tony-dell && ./scripts/git-safe-pull.sh'`
  if the served checkout needs the new content.

## 7. Card the leftovers

Anything **[Tony]** or **[sudo]** gated becomes a kanban `requests:` block or a
backlog card — never a chat-only note. Then update the onboarding card's comms
with installed/skipped/pending.

---

Known per-host deltas: `docs/kb/ubuntu-install-macbook-pro13-3.md` (install),
`docs/kb/hardware-tony-macbook.md` (hw), `ssot.mysystem.<host>.yml` (state).
