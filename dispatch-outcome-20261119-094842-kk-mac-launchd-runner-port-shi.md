# dispatch outcome — kk-mac-launchd-runner-followthrough

Verified on the metal: the launchd runner on kk-mac does **not**
claim kanban cards — it was never provisioned. The only launchd job
is the nest-pack lane worker; the gap to runner parity is one un-run
onboard script plus three manual gates. Boundary spec written to
`docs/ssot/jobs/kanban/2026-11-19-kk-mac-launchd-runner-verify.yml`;
a board request asks Tony whether to provision now.

## What was found (live, ssh kkkakk@kk-mac, 2026-11-19)

- `net.adanest.kk-llm-worker` is the ONLY chaba launchd job
  (gui/501, StartInterval=60, runs=8, last exit=0). It runs
  `kk_mac_lane_worker.py --remote gdrive:ada-nest/kk-llm
  --max-packs 1` — bounded LLM task **packs** over rclone. By design
  it never touches the kanban; logs show it gating on `load_high`
  and holding `fallback_held` packs correctly.
- `ai.chaba.runner-agent` is absent: no plist in
  `~/Library/LaunchAgents`, no `~/.local/bin/runner-agent`, no
  `~/.local/share/runner-agent` state dir, no `id_chaba_deploy` key,
  no `gh-chaba` alias, no opencode. No `devin-task-*`/`runner-*`
  jobs registered. Nothing polls the board — no kanban card can be
  claimed today.
- The launchd *code* IS on the metal: the exec checkout
  `~/CascadeProjects/chaba` (clean, synced past the 2026-11-14
  merge) contains the `rt_launch`/launchd seam and
  `kk-mac-runner-onboard.sh`.
- Preflight PASSES: macOS 15.7.3, Mac16,9, arm64, python 3.15.2,
  git+CLT, `gui/501` reachable (kkkakk logged in), disk 24%.
  Load math at check: 5m `vm.loadavg` 9.96 / 14 cores = 0.71 <
  `RUNNER_MAX_LOAD_PC` 1.0 — a provisioned runner would claim.

## Gap to parity (spec'd in the job yml)

`bash scripts/ops/kk-mac-runner-onboard.sh` (all steps, user-level,
no sudo) installs the runner; the manual gates it cannot cross
unattended:

1. deploy-key enrolment at GitHub (write key on tonezzz/chaba) —
   needed for `push:chaba`, not for claiming;
2. `~/.config/secrets/litellm-keys.env` (copy from idc02) — needed
   for opencode lanes;
3. gui-domain persistence — works now (kkkakk logged in); headless
   needs auto-login or `LAUNCHD_DOMAIN=user`;
4. exec checkout remote is plain https + no `chaba-role` stamp —
   the `checkout` step handles both.

By design (stays after provisioning): `executor=devin` cards are
declined by `claimable()` — devin-dispatch drives systemd-run
internally; porting it is separate cardable work. No cgroup on
macOS — plist Nice/LowPriorityIO + `ulimit -v` are the substitutes.
Serveable once provisioned: script, opencode, jules, nlm_batch,
kk_mac_local (container only if podman/docker lands).

## Changes in this worktree

- `docs/ssot/jobs/kanban/2026-11-19-kk-mac-launchd-runner-verify.yml`
  — the durable verification record + parity-gap spec + e2e recipe.
- `docs/ssot/kanban/ssot.kanban.yml` — `runner_fleet` kk-mac note
  now records the 2026-11-19 verified-not-provisioned state.
- Board: progress comments + a pending **request** asking whether to
  run the onboarding via ssh (a service install + deploy-key
  generation on KK's machine — needs the explicit go).

## Result

Packs-only confirmed; boundary documented; provisioning request
raised. If the request is answered `yes`, the onboard script is one
command away (preflight verified); the GitHub key enrolment +
litellm secrets remain the human gates either way.
