# Dispatch outcome — ada-engine-runtimes

Card: `ada-engine-runtimes` (backlog → dispatch). Commit `c12c037061` on
branch `dispatch/20261125-051119-from-ai-engine-lines-ssot-apps` (not
pushed, per dispatch rules).

## What changed

The card's gap: every `ada-*` lane on idc03 shares one
`~/CascadeProjects/ada-voice` checkout + `.venv`, so the fleet-wide
engine version is single — lanes can't run different engine versions
simultaneously. Delivered the enabling infra as **design + tooling**
(no live host changes were possible or authorized from this worktree):

- **`docs/kb/ada-engine-runtimes.md`** — design/runbook. Chosen model:
  per-engine runtime slot `~/CascadeProjects/ada-engines/<engine-id>/`
  (pinned ada-voice checkout + own `.venv`); lane→engine binding is a
  systemd drop-in rewriting `WorkingDirectory`/`ExecStart` — instant,
  reversible, lane env/keys/banks/ports untouched. Quadlet image per
  engine explicitly deferred as hardening (ada-voice isn't
  containerized; the ExecStart-level binding means a container slot can
  replace a checkout dir later without contract changes). Includes the
  ada-2 onboarding procedure and non-goals.
- **`scripts/ada/engine-runtime.sh`** — idempotent bash tool with
  `provision` (clone+pin ref+build venv), `bind`/`unbind` (drop-in
  management, handles `%h`/`~`/`$HOME` path spellings in ExecStart),
  `lane` (scaffolds a variant test lane: env copy + unit +
  isolation.conf caps + stagger drop-in), `status`. `bash -n` clean;
  path-rewrite logic verified against a mock unit.
- **`docs/ssot/apps/ssot.apps.ada-engines.yml`** — new `runtime_model`
  section; the `what_is_NOT_config_swap_today` limit marked resolved;
  gap entry updated to DONE.
- **`docs/ssot/jobs/ada/2026-11-25-ada-engine-runtimes.yml`** — job
  record with decision rationale, artifacts, verification, followups.

## Result / how to verify

- `git show c12c037061` — 4 files, +474/-1; SSOT validation + optimize
  gate passed in pre-commit.
- On idc03 (when ready): `scripts/ada/engine-runtime.sh provision
  ada-2.0 --ref <ref>` then `lane`/`bind` per the runbook; verify with
  `curl http://127.0.0.1:<port>/api/health` and the contract suite.
- Caveat: bind/lane paths were verified syntactically and against mock
  unit text only — first real run on idc03 is the acceptance test
  (unit ExecStart shapes on idc03 may differ; the script errors loudly
  if it can't read ExecStart).

lessons:
- Lane units on idc03 aren't fully declared in-repo (drop-ins live in
  ~/.config/systemd/user) — bind tooling must parse `systemctl --user
  cat` output rather than assume a unit template.
- ExecStart path spellings vary (%h vs $HOME vs ~) — rewrite all three
  or the drop-in silently points at the old checkout.
- Declaring new runtime dirs/units still needs stack.yml +
  ssot.audit.hosts.yml entries (host-hygiene R1) — the `lane`
  subcommand prints that checklist but can't do it for you.
