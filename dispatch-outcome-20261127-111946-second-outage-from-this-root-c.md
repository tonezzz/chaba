# Dispatch outcome — idc03-chaba-vault-sync-gap (SYS-1496)

## What changed

Implemented the card's recommended **option (c): split code from data**,
repo-side only (dispatch rules bar host deploys).

- `systemd/ada-memory-sync.service`, `ada-memory-drift.service`,
  `obsidian-vault.service`: ExecStart script paths repointed from
  `~/CascadeProjects/chaba-vault/...` to `~/CascadeProjects/chaba/...`
  (the hourly `chaba-repo-sync` checkout). `--vault` args and `ADA_*`
  env vars still point at `chaba-vault/docs/ada-memory` — vault data
  untouched.
- NEW canonical `systemd/ada-memory-gaps.{service,timer}` and
  `systemd/ada-memory-distill.{service,timer}` — these units were
  hand-installed on idc03 with no repo copies; now captured with chaba
  script paths.
- Job doc: `docs/ssot/jobs/infrastructure/2026-11-27-chaba-vault-sync-gap-code-data-split.yml`
  — decision rationale, verified live state, compatibility check,
  deploy/rollback runbook, commit fate.

Commit: `fe6ccdca9e3` on `dispatch/20261127-111946-second-outage-from-this-root-c`.

## Verified on idc03 (read-only ssh)

- `chaba-vault`: HEAD `e1128f502`, **119,557 behind** origin/master,
  1 ahead, 421 dirty paths — ~9 tracked live vault-data edits
  (`docs/ada-memory/personal-kk/*`, `tony-projects/marker.md`), the
  surgical `sync-ada-memory-to-mddb.py` scp patch (uncommitted), ~411
  untracked inbox extracts. Confirms a blind pull is unsafe → (c) wins.
- `~/CascadeProjects/chaba` on idc03: exec checkout, current (HEAD
  f472bf13 today) — correct script source.
- Script compatibility confirmed by reading code + `py_compile`:
  `--vault` overrides `VAULT`; `REPO`/`SSOT` paths resolve via
  `__file__` so running from chaba reads *current* bank/schema SSOT;
  distill/gaps write MDDB drafts only (vault inbox filled by
  `--export-inbox`); obsidian server is fully env-driven.
- mn01 has no `chaba-vault` — chaba paths work there unchanged.
- idc01 is **offline**; its `config.repo` exec checkout IS chaba-vault
  and `flood-hub-poll` exec references it — flagged as open item in the
  job doc for when it returns.

## e1128f502 fate

**Keep, don't push, don't drop.** It's a vault-data commit (inbox
triage file moves) that would need a risky merge across 119k commits of
divergence for zero benefit — vault data propagates via MDDB sync +
pull-vault rsync, not git push from the replica. It also anchors the
live working tree's triage state as a checkpoint.

## Result / how to verify

After merge, deploy on idc03 = repoint ExecStart in the 5 user units
(sed `chaba-vault/scripts|apps` → `chaba/...`; keep obsidian's jobenv
interpreter + obsidian.env), `daemon-reload`, restart only
`obsidian-vault`. Full runbook + rollback in the job doc. Verify:
`systemctl --user start ada-memory-sync.service` → `Result=success`;
`journalctl --user -u obsidian-vault` clean startup.

Card comms posted with the full decision summary.

lessons:
- chaba-vault on idc03 is a DATA replica, not an exec checkout — code must run from ~/CascadeProjects/chaba; assuming "checkout sync" covers every clone caused this second outage.
- systemd units hand-installed on hosts (ada-memory-gaps/distill) drift invisibly from repo — canonicalize them into systemd/ when touching them.
- ssot.jobs.yml config.repo.idc01 = chaba-vault: idc01's job-exec checkout is the vault clone — same drift class, reassess when idc01 returns.
- Live idc03 obsidian-vault.unit diverges from repo copy (jobenv python + obsidian.env EnvironmentFile) — repo systemd/ files are reference, not installed truth.
