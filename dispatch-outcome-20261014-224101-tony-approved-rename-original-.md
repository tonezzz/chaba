# Dispatch outcome — ada-pi -> ada-voice rename (attempt 2)

Card: `ada-pi-rename-ada-voice` · Runner: idc03 · Branch: `dispatch/20261014-224101-tony-approved-rename-original-`

## What this session did

Attempt 1 (220238, tony-dell) had already landed the heavy half: GitHub repo renamed
(`tonezzz/ada-pi` -> `tonezzz/ada-voice`, verified: ada-voice=200, ada-pi=301 redirect),
ada-voice self-sweep merged to its main, the 307-file chaba sweep + `rename-ada-voice.sh`
executor + job runbook on its (then-unmerged) branch, and renames on tony-omen,
tony-macbook, idc03.

1. **Merged attempt-1's branch** (`origin/dispatch/20261014-220238-*`) into this branch —
   the sweep was not yet on master. Conflicts resolved: `integrations/ada-voice/README.md`
   (kept ada-voice naming + HEAD's ninth drop; refreshed Drop 9's stale ada-pi paths),
   the two new `*.whisper-url.patch` files relocated into the renamed dir, and
   `scripts/cam-wall/zones.yml` (kept HEAD's CAMWALL_ZONE_GROUPS comment, ada-voice naming).
2. **Fleet re-check via `rename-ada-voice.sh status`**: every reachable host
   (tony-dell, idc02, idc03, tony-omen) now shows real `ada-voice` dir + `ada-pi`
   back-compat symlink + **zero ada dispatches in flight** — tony-dell and idc02 cleared
   the quiet gate between attempts. tony-macbook was renamed in attempt 1 (ssh from idc03
   lacks a key, can't re-verify). **mn01 unreachable both attempts** (ssh timeout).
3. **Verify (card step 5), all green on idc03**:
   - `~/.local/bin/deploy-ada.sh` installed copy == canonical repo copy (no drift), already
     references `~/CascadeProjects/ada-voice`.
   - `deploy-ada.sh` green run: fetch+ff at `8eaab27`, tool-lint clean,
     **pytest 1467 passed**, all 8 ada services restarted `active`
     (ada-ha-tony/michael, ada-pi-pwa, ada-dev, ada-kk-dev, ada-kk, ada-line-relay, ada-tg-relay).
   - Dispatch resolution verified: `BUILTIN_REPOS` + `REPO_TESTS` answer both `ada-voice`
     (canonical) and `ada-pi` (legacy alias) -> `~/CascadeProjects/ada-voice`;
     `devin-dispatch.sh` fallback map + `dispatch-repos.conf` carry both.
   - No systemd unit on idc03 references `CascadeProjects/ada-pi`.
4. **Live-card sweep**: 6 non-done cards' `action.repo: ada-pi` -> `ada-voice`
   (ada-memory-dev-lane-runtime, webchat-lane-boards, ada-render-video-bypasses-*,
   local-image-lane-sd-server-*, render-flow-quality-pass, ada-render-job-wp-log).
   91 done cards keep `ada-pi` as history — the alias resolves them.
5. **Runbook updated** (`docs/ssot/jobs/infrastructure/2026-10-14-ada-pi-rename-ada-voice.yml`):
   checkouts block corrected to all-renamed, `verified:` section added.

## Remaining

- **mn01**: still ssh-unreachable — run `scripts/devin/rename-ada-voice.sh run mn01` when it's
  back (stacks/mn01 units reference the dir).
- Retire `ada-pi` compat symlinks + repos.conf/dispatch alias lines once no ada-pi repo
  references remain on the board.
- Historical mentions deliberately untouched: dispatch-outcome-*, backups/,
  docs/kb/archive, `.triage/` snapshots, done cards, unit NAMES `ada-pi-pwa`/`ada-pi-orch-bench`.

## How to verify

- `bash scripts/devin/rename-ada-voice.sh status` — expect `new_dir=1 old_link=1 inflight: none`
  on every host except mn01.
- `git -C ~/CascadeProjects/ada-voice remote -v` on any host -> `tonezzz/ada-voice.git`.
- `python3 -c "import sys;sys.path.insert(0,'scripts/board');import dispatch_repos as d;print(d.BUILTIN_REPOS['ada-voice'])"`.
