# Dispatch outcome — audit-miss-remote-eval-results-not-landed

Card: audit-miss-remote-eval-results-not-landed (AUD-0030). Runner: idc02.
Branch: dispatch/20261124-215947-locate-and-land-or-document-as.

## Result: all three flagged artifacts RECOVERED and landed

### 1. evals/results/devnest-host-tony-omen.json — FOUND on tony-dell

Not on tony-omen at all. The devnest-host-assessment skill writes to
`~/evals/results/` on **tony-dell** (outside any git checkout) — see
dispatch-outcome-20261027-053444 on the education-loop rerun. All six
host assessment JSONs from the 2026-10-27 re-run plus the 2026-10-25
`devnest-replay-candidates.json` were sitting in
`tony-dell:~/evals/results/`. Copied verbatim into `evals/results/`
(named file + 5 siblings from the same batch + replay candidates).

### 2. evals/results/devnest-replay-candidates.json — same source

Same tony-dell directory, dated Oct 25 15:31 (matches the
DEV-0861 mining comms). 40 candidates, 30 KB, no secrets (checked).

### 3. evals/kk-mac-lane/out/kk-mac-live-jev-probe-idc03-20261030.json — FOUND in idc03 patch-inbox

The retry commit `1f16965029` ("evals: record supervised KK-Mac JEV
probe", verdict=pass) never reached master — it sat as a thin git
bundle in `idc03:~/.local/share/devin-dispatch/patch-inbox/`. Fetched
the bundle into this worktree (prerequisite 78e52c72 already in
history) and **cherry-picked it** → commit `872de9664c`, preserving
authorship/date. The artifact records the PASSING retry
(task_id kk-mac-live-probe-retry-20261030, qwen3:8b, all fact checks).

Note: the earlier FAILED attempt artifact (verdict=fallback, kk-mac SSH
timeout) survives only inside
`idc03:~/wt-salvage/dispatch-wt-kk-mac-live-probe-20261030-20261113.tgz`;
not landed — superseded by the pass artifact.

## Commits on this branch

- `872de9664c` evals: record supervised KK-Mac JEV probe (cherry-pick of 1f16965029)
- `c6b7c252cb` evals: land recovered devnest host-assessment + replay-candidate results (7 JSONs + job record)

Job/runbook trail: `docs/ssot/jobs/devnest/2026-11-24-remote-eval-results-recovery.yml`

## Root causes documented

- Devnest files: written outside the repo (`~/evals/` on tony-dell) —
  never copied in. `~/evals/` is an untracked single-point-of-failure
  dir (already flagged on devnest-host-assessment-education-loop).
- kk-mac file: committed but stranded in patch-inbox (merge-sweep
  miss), AND its path is under `.gitignore` `evals/*/out/` — normal
  `git add` can never pick it up; needs `-f` or an ignore-rule change.

## Still unlanded (out of scope, noted for audit)

`tony-dell:~/evals/results/` holds more unlanded artifacts:
`devnest-host-fleet-layers/`, `devnest-host-tony-dell-layers/` report
dirs, and kk-mac-*/m1-*/t*-bench outputs belonging to other cards.
kk-mac host itself is unreachable (SSH timeout) — no check possible.

## How to verify

- `git show --stat 872de9664c c6b7c252cb` on this branch.
- After merge: `git ls-tree -r origin/master --name-only -- evals/results evals/kk-mac-lane/out`.
- `python3 -m json.tool` on each landed file (all validated before commit).

lessons:
- Declared card `artifact:` paths under `evals/*/out/` are gitignored — commits of them need `git add -f` or the original commit object must be recovered (bundle/cherry-pick).
- DevNest skill artifacts live at `tony-dell:~/evals/results/` outside the repo — check there before declaring eval results lost.
- idc03 `~/.local/share/devin-dispatch/patch-inbox/*.bundle` retains stranded commits; thin bundles fetch fine inside any checkout with master history.
- `idc03:~/wt-salvage/*.tgz` preserves dead dispatch worktrees — tar tzf | grep finds artifacts even after worktree GC.
