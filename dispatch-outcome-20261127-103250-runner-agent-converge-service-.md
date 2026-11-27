# Dispatch outcome — runner-agent-converge.service NOPERMISSION fix

Card: `runner-agent-converge-nopermission-fix` (OPS-1491)
Branch: `dispatch/20261127-103250-runner-agent-converge-service-` — commit `31b7331060e`

## What was wrong

`runner-agent-converge.service` on tony-dell alternated clean runs and
`status=4/NOPERMISSION`. That label is a red herring: systemd names exit
code 4 `NOPERMISSION` (sysexits), but for `ansible-playbook` exit 4 is
`ExitCode.HOST_UNREACHABLE` in ansible-core 2.20. The 2026-11-27 03:30 run
converged all 6 reachable hosts cleanly (log shows REDEPLOYED + restart
handler on each) and lost the unit only because `tony-macbook` — a
`portable`-group laptop whose inventory comment says sleep/off-net is
normal — timed out on ssh during `gather_facts`. The playbook targeted
`all:!macos:!disabled`, which includes `portable`.

## What changed

`ansible/playbooks/deploy-runner-agent.yml` — split into two plays:

- **Portable play first** (`portable:!disabled`, `ignore_unreachable:
  true`): a sleeping laptop is counted ok+ignored instead of unreachable,
  so it cannot fail the unit. It still converges whenever it is on-net.
- **Always-on play last** (`all:!macos:!disabled:!portable`): keeps
  hard-fail semantics. Ansible's process exit code is the LAST play's
  result (`PlaybookExecutor.run` returns the final `result`), so an
  unreachable idc02/idc03/con01/tony-omen/tony-dell still exits 4 and
  keeps alerting.
- Dest paths switched from `ansible_facts.user_dir` to `~/` (remote
  $HOME): a host unreachable at `gather_facts` has no facts, and
  fact-based paths turned the ignored unreachable into a real task
  FAILURE on the next task — caught by ghost-host testing before it
  shipped. This also removed the INJECT_FACTS_AS_VARS deprecation noise.

Job trail: `docs/ssot/jobs/infrastructure/2026-11-27-runner-agent-converge-nopermission.yml`.

## Verification (all on tony-dell unless noted)

- Ghost inventory (`/tmp/ra-ghost/hosts.yml`, dead 192.0.2.x hosts + real
  idc02/mn01), run from idc02: unreachable portable -> `ok=4 ignored=3
  failed=0`; unreachable always-on -> `RC=4` preserved; `~` expansion
  verified on real hosts.
- `--check --diff` on real inventory: all 7 hosts `in-sync`, changed=0.
- Fixed playbook temporarily staged at the unit's real path on tony-dell
  (backup `/tmp/deploy-runner-agent.yml.bak-20261127`), then **3
  consecutive `systemctl --user start runner-agent-converge.service` ->
  `Result=success`, `ExecMainStatus=0` each**; unit log shows both plays,
  all 7 hosts in-sync, changed=0.
- Hash sweep: `~/.local/bin/runner-agent` sha256 = manifest pin
  `d0465bfe2a6e1ff241f253195ad83846f199f7cba7e66331cebb37b2b6c2c062` on
  all 7 hosts (tony-dell, idc02, idc03, con01, tony-omen, mn01,
  tony-macbook — all currently reachable).
- tony-dell exec checkout **restored** to master's playbook after
  verification (git status clean). The fix reaches the unit via normal
  merge + `chaba-repo-sync` (15-min cadence on dell); next timer fire is
  2026-11-28 03:34 — a single recurrence before merge is possible if
  tony-macbook sleeps and self-heals on merge.

## Notes / residuals

- `deploy-runner-tools.yml` has the same latent fleet-wide shape, but its
  only fleet caller (`runner-tools-converge.sh`) already pre-pings and
  `--limit`s to reachable hosts (OPS-1478); a manual fleet-wide run could
  still exit 4 on a sleeping laptop.
- A genuine task *failure* (not unreachable) on a portable host is masked
  when the always-on play succeeds — last-play-wins exit code.
  Acceptable: portables are best-effort and drift is independently audited
  by hash comparisons.
- Card comms posted on `runner-agent-converge-nopermission-fix` and
  `timer-alert-tony-dell-runner-agent-converge`.

lessons:
- systemd `status=4/NOPERMISSION` on an ansible oneshot is almost always
  ansible `ExitCode.HOST_UNREACHABLE` (4), not a permissions problem —
  check the appended playbook log before hunting become/file-mode bugs.
- ansible-playbook's exit code is the LAST play's result only; multi-play
  playbooks must order hard-fail plays last or earlier failures get masked.
- `ignore_unreachable: true` keeps the host in the play — every later task
  still runs against it; fact-dependent paths (`ansible_facts.user_dir`)
  then fail for real. Use `~/`-style remote paths on volatile-host plays.
- The chaba `ansible.cfg` sets global `become=true`; ad-hoc `ansible -m
  ping` tests fail on hosts without passwordless sudo — play-level
  `become: false` is what makes the converge playbooks work.
