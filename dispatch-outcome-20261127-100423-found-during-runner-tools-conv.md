# Dispatch outcome — runner-drift-rearm-idc03-ssh-proxyjump-dead (SYS-1487)

## What was found

- Reproduced live from tony-dell: `ssh idc03 true` → rc=255
  `channel 0: open failed: administratively prohibited`; `ssh -G idc03`
  showed `proxyjump tony-omen`. `ssh -o ProxyJump=none idc03` → rc=0.
- Root cause is a **stale hand-managed stanza**: tony-dell's
  `~/.ssh/config` has no SYS-0032 managed block; the `Host idc03` stanza
  carried `ProxyJump tony-omen`, dead since the 2026-11-26 scoped-sftp
  hardening set `AllowTcpForwarding no` fleet-wide. Direct tailnet is the
  declared route (`ansible_host: 100.102.134.91`).
- Card's timer-sentinel hypothesis checked and **disproven for today**:
  timer-sentinel + timer-timeline-update are co-located on tony_omen
  (ssot.jobs.yml), whose ssh config is clean — `_live_verify` was not
  actually broken. Patched anyway (same latent class).
- Fleet ssh-config survey: only tony-dell drifted. omen/mn01/idc02/idc03
  clean (con01 unverifiable — mn01→con01 publickey denied).

## What changed (commit 2e53e08368 on dispatch branch)

- `scripts/lib/ssh_route.py` (new): `ssh_run()`/`ssh_argvs()` — direct
  tailnet (`ProxyJump=none ProxyCommand=none`) first, operator ssh config
  as fallback; all-fail returns last route's result, last-route
  TimeoutExpired propagates. Mirrors mcp-health `execOnHealthHost`.
- Wired into: `scripts/board/board-cli.py` (--ssh transport — fixes
  card-run/card-pick/card-context/capture-apply at once),
  `scripts/board/runner-drift-rearm.py` (board_call),
  `scripts/ada/timer-sentinel.py` (_live_verify, guarded import →
  plain-ssh fallback on stale checkout), `scripts/ada/timer-timeline-update.py`
  (collect_host, same guard).
- `tests/test_ssh_route.py`: 8 unit tests, all pass; board-cli +
  drift-rearm existing tests pass; py_compile clean.
- Job doc: `docs/ssot/jobs/infrastructure/2026-11-27-runner-drift-rearm-ssh-proxyjump.yml`.

## Live host change (root-cause repair)

- tony-dell `~/.ssh/config`: removed `ProxyJump tony-omen` from
  `Host idc03` (backup `~/.ssh/config.bak-20261127-sshproxyjump`).
  Verified: `ssh idc03 true` rc=0 and the full board_call path
  (`ssh idc03 python3 .../board-cli.py __api` GET /cards) returns JSON.
  This also repairs every other `ssh idc03` consumer on dell
  (chaba-nag relay, mddb-standby-pull, llm-burn, ci-smoke, ad-hoc ops).

## How to verify

- `ssh tony-dell 'ssh idc03 true'` → rc=0 (was 255).
- `ssh tony-dell 'ssh -G idc03 | grep -i proxy'` → empty.
- After merge + repo-sync: `python3 scripts/board/runner-drift-rearm.py
  --audit-file <transcript>` on dell posts to the board instead of
  silently no-oping; `board-cli.py --ssh idc03 get <card>` works.
- Residual: other fleet-ssh call sites (runner-fleet-health probe,
  board-api remote calls, kanban-dispatch, merge-sweep, host-services-cms,
  log-shipper, scripts/ops/*) not yet on ssh_run — most run on idc03
  (clean) or fail loudly; adopt on next touch. Running
  `ansible/playbooks/ssh-config-generate.yml` on dell would put the
  stanza under the SYS-0032 managed block and prevent recurrence.

lessons:
- `AllowTcpForwarding no` silently kills every ProxyJump fleet-wide — any ~/.ssh/config jump-host path becomes dead weight overnight; the durable pattern is direct-tailnet-first with operator config as fallback (scripts/lib/ssh_route.py, same as mcp-health execOnHealthHost).
- `|| true` on a board-writing script turns ssh failure into a silent no-op — verify the transport end-to-end, not just the exit code.
- A card's "likely also affects X" hypothesis needs a live check: timer-sentinel runs on tony_omen (clean ssh), not tony-dell — only dell's config was drifted.
- Hand-managed ~/.ssh/config on dell has no SYS-0032 managed block; ssh-config-generate.yml was never applied there, so stanza drift accumulates unchecked.
