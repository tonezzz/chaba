# dispatch outcome — ada-pi → ada-voice rename (attempt 2, auto-retry)

Card: `ada-pi-rename-ada-voice` (ADA-0596, Tony-approved). Session repo: chaba, runner tony-macbook.

## Context: attempt 1 had already executed the rename

Dispatch `20261014-220238` (tony-dell) did the zero-risk half + host renames; its 307-file chaba sweep branch was merge-held on a stale patch-apply test, which is why this retry fired. Full mechanics live in `docs/ssot/jobs/infrastructure/2026-10-14-ada-pi-rename-ada-voice.yml` (updated with `attempt2_resolution`).

## Verified state (all hosts checked live, not from docs)

- GitHub `tonezzz/ada-pi` → `tonezzz/ada-voice` — done by attempt 1; `git ls-remote` confirms both names resolve to the same HEAD (redirect live).
- Checkouts: tony-dell, idc02, idc03, tony-omen, tony-macbook all have real `~/CascadeProjects/ada-voice` + `ada-pi` → `ada-voice` compat symlink. All five at `origin/main` `8eaab27` (idc02/omen/macbook pulled forward this session; dell pulled + `deploy-ada.sh` installed at `~/.local/bin/`).
- **mn01 unreachable** (ssh connect timeout) — still has the old dir; tracked on `ada-voice-rename-cleanup` (ADA-0681).
- Dispatch layer: `dispatch_repos.repos()` on dell resolves `ada-voice` and the legacy `ada-pi` alias → `~/CascadeProjects/ada-voice`. idc02/idc03/omen have no installed repos.conf — they use BUILTIN_REPOS (old table resolves via the symlink until the merge lands).
- Systemd: patched at rename time by the script (idc03: 23 units, omen: 3); unit *names* intentionally keep `ada-pi-pwa`/`ada-pi-orch-bench`.

## What this session changed (commit 25fcc4e37 + job-doc commit)

1. **Merge-gate fix.** `test_draft_hit_frame::test_patches_apply_and_compile` held the merge because the staged `integrations/ada-voice/` drops had *already landed upstream*: 16/21 patches reverse-apply clean; the other 4 landed with evolved code (`SESSION_CHAT` moved to `tool_runner/common.py`; image/file-ingest call sites refactored). Retired the 4 apply-tests + 20 landed patches. Kept `calendar_providers.create-dedup.patch` — genuinely **never applied** (18/158 lines upstream); flagged on card `calendar-write-idempotency` that the double-write guard is not live.
2. **Card sweep:** `action.repo: ada-pi` → `ada-voice` on 88 kanban cards (comms/history untouched; one stray comms mention left deliberately).
3. Minor: `spend-ledger.py` comment, drop README now records landed-vs-pending per drop.

## Verify (card step 5)

- deploy-ada.sh green run: **done** — idc03 prod deploy via `~/.local/bin/deploy-ada.sh`: fetch+ff to 8eaab27, tool-lint clean, **1467 tests pass**, 8 services restarted and active (`ada-ha-tony/michael`, `ada-pi-pwa`, `ada-dev`, `ada-kk-dev`, `ada-kk`, `ada-line-relay`, `ada-tg-relay`).
- tool-lint + pytest on prod checkout: covered by the same run (gates are inside deploy-ada.sh).
- dispatch claim on renamed repo: mechanism verified (`repos()` resolves both names → correct path); no organic `repo: ada-voice` claim has occurred yet — remains on ADA-0681's done-condition.
- Merged-tree gate suite verified on a dell replica of this branch: **223 passed, 37 skipped** (`python3 -m pytest tests -x -q`, system interpreter — same resolution the gate uses).

## Left open (by design — owned by `ada-voice-rename-cleanup` / other cards)

- mn01 rename when reachable (`rename-ada-voice.sh run mn01` from dell + `stacks/mn01` units).
- Compat shim retirement (per-host `ada-pi` symlink + `ada-pi` alias lines in repos.conf / `BUILTIN_REPOS` / `REPO_TESTS` / `devin-dispatch.sh`) once the board carries no `ada-pi` repo refs and mn01 is done.
- `calendar_providers.create-dedup.patch` needs regeneration/hand-apply on ada-voice — real unshipped fix.
- `ssot.apps.ada_pi.yml` filename kept (slug, cosmetic); `ada-pi-pwa` env/unit/route names kept per scope.
