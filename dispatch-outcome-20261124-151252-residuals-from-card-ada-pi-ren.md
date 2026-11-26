# Dispatch outcome — ada-voice-rename-cleanup (2026-11-24, tony-dell)

Card: `ada-voice-rename-cleanup` — residuals from `ada-pi-rename-ada-voice`
(job doc `docs/ssot/jobs/infrastructure/2026-10-14-ada-pi-rename-ada-voice.yml`,
`remaining:` block updated in this change).

## What changed

### mn01 catch-up (was unreachable 2026-10-14)
- `scripts/devin/rename-ada-voice.sh run mn01` → `ada-voice@1c94657`,
  6 worktree `.git` pointer fixes, 3 systemd units patched
  (ada-ha-tony, ada-ha-michael, ada-standby-sync), compat symlink created.
- `git -C ~/CascadeProjects/ada-voice pull --ff-only` on mn01 — fast-forwarded
  to origin/main.
- Found + fixed a straggler the rename script can't reach:
  `~/.local/bin/mn01-canary.sh` still defaulted `ADA_REPO=~/CascadeProjects/ada-pi`.
  Reinstalled from `chaba/scripts/ops/mn01-canary.sh` (already ada-voice on
  master; mn01's chaba checkout is 94 behind but has the fixed file —
  md5-identical to this worktree's). Also sed'd the stale "ada-pi standby"
  Description in `ada-standby-sync.service` + daemon-reload.
- mn01 has no `repos.conf` (uses BUILTIN) — nothing to clean there.

### Compat shims retired
- `~/CascadeProjects/ada-pi` symlink removed on all 6 hosts
  (tony-dell, idc02, idc03, tony-omen, mn01, tony-macbook) — each verified
  `[ -L ]` before rm; no real dir ever remained after the mn01 rename.
- `ada-pi` alias line removed from live
  `~/.local/share/devin-dispatch/repos.conf` on the 3 hosts that have one
  (tony-dell, idc03, tony-macbook; idc02/omen/mn01 have no file).
- Repo edits (this worktree, awaiting merge):
  - `scripts/board/dispatch_repos.py` — dropped `ada-pi` from `BUILTIN_REPOS`
    and `REPO_TESTS`.
  - `scripts/devin/devin-dispatch.sh` + `scripts/devin/claude-dispatch.sh` —
    dropped `[ada-pi]` fallback entries (claude-dispatch had the same map;
    card only named devin-dispatch.sh).
  - `scripts/devin/dispatch-repos.conf` — template alias line removed.
  - `scripts/ops/deploy-diff.sh` — macbook row `ada-pi` → `ada-voice`.
  - `scripts/ops/backlog-spec-enrich.py` — repo list in the enrich prompt
    no longer offers `ada-pi`.
- **Kept deliberately:** `REPO_ALIASES = {"ada-pi": "ada-voice"}` in
  `dispatch_repos.py`, `runner-agent.py`, `runner-fleet-health.py` — it is
  the push-label/credential canonicalization ("one repo, one credential"),
  not a path shim. `canon_repo()` still maps a stray `action.repo: ada-pi`
  card to ada-voice for push-guard + push_probe (verified below).

### Card sweep (item 3 — optional)
- No-op: every card with `action.repo: ada-pi` is `column: done` or in
  `archive/` (94 files, all history). Zero live cards carry it — the
  2026-10-14 sweep already moved the 6 non-done ones.

## Verification

- `rename-ada-voice.sh status`: all 6 hosts `old_dir=0 new_dir=1
  new_link=0 old_link=0` (mn01 + macbook now reachable and renamed).
- Fleet audit per host: no `CascadeProjects/ada-pi` in worktree `.git`
  pointers, systemd user/system units, crontabs, env files, `~/.local/bin`,
  or ada-voice checkouts. Only inert hits remain: generated `cards.json`
  board artifacts, `__pycache__`, mddb rebuild ndjson dumps, dated job/card
  docs, and unit *names* (`ada-pi-pwa`, `ada-pi-orch-bench` — renamed units
  were out of scope).
- Dispatch claim on ada-voice green:
  - `dispatch_repos.repos()["ada-voice"]` → `~/CascadeProjects/ada-voice@main`.
  - `push_probe("ada-voice")` → `pushable: True` (live `git push --dry-run`).
  - `push_probe("ada-pi")` → still pushable via canon fallback.
  - Live evidence: `devin-task-20261124-151206-ada-tool-consolidation-merge-o`
    (repo ada-voice) claimed + running on tony-dell during this session.
- Tests: `test_claim_order` + `test_runner_push_guard` +
  `test_kanban_dispatch_rails` (22), `test_dispatch_close_out` +
  `test_merge_sweep` + `test_dispatch_runner_resilience` (110),
  `test_build_task_regressions` + `test_executor_contract` (115 + 17
  subtests) — all pass. `bash -n` clean on both dispatch scripts;
  `ast.parse` clean on both py edits; job-doc YAML validates.

## Notes / leftovers (not blockers)

- tony-macbook ssh: `ssh tony-macbook` (id_cascade) was denied from tony-dell
  early in the session; `tony@100.77.76.112` and a later `tony-macbook`
  attempt worked — likely the macbook re-enroll dispatch fixed keys
  mid-session. Worth a look if it recurs.
- idc03 has an inert `ada-scenario-full.container.bak-mig-20261023` under
  `~/.config/containers/systemd/` — a `.bak` quadlet backup (host-hygiene
  rules say no `.bak` units; it can't load). Left in place, flagged here.
- Stale task metas without `exit_code` linger on omen (8 ada-voice) and
  macbook (2) — no matching running units; cosmetic queue noise for the
  rename script's inflight gate only.
- Live `~/CascadeProjects/chaba*` checkouts still carry the old script
  copies until this branch merges + `chaba-repo-sync` pulls — all remaining
  `CascadeProjects/ada-pi` hits in them are `deploy-diff.sh` (macbook row,
  fixed here), `rename-ada-voice.sh` (the migration tool itself), and
  generated `cards.json` artifacts. None break with the symlink gone.

## How to verify

```
ssh <host> 'ls -la ~/CascadeProjects | grep ada-pi'   # expect nothing, all hosts
bash scripts/devin/rename-ada-voice.sh status          # old_link=0 everywhere
python3 -c "import sys; sys.path.insert(0,'scripts/board'); \
  import dispatch_repos as dr; print(dr.push_probe('ada-voice'))"
```

lessons:
- The rename script patches systemd units + worktree `.git` files but NOT `~/.local/bin` scripts — mn01-canary.sh kept a dead `ADA_REPO=ada-pi` default for 40 days. After any path rename, grep `~/.local/bin` and env-specific script dirs on every host, not just units.
- `ssh tony-macbook` (ssh-config alias, id_cascade) can be denied while `tony@100.77.76.112` works — try the raw tailscale IP before declaring a host unreachable.
- Task metas without `exit_code` are not proof of in-flight work — cross-check `systemctl --user list-units devin-task-*` before trusting the quiet gate.
- `REPO_ALIASES`/`canon_repo` is the credential canonicalization layer (runner-agent.py, runner-fleet-health.py have their own copies) — distinct from the path/name alias entries; removing BUILTIN/REPO_TESTS entries does not strand stray `repo: ada-pi` cards because push_probe falls back through canon_repo.
