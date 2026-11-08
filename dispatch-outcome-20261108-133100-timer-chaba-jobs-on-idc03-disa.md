# Dispatch outcome — timer-alert-idc03-chaba-jobs (4th dispatch on same alert, idc02)

## Verdict

`chaba-jobs.timer` disabled on idc03 is **deliberate** (OPS-0790 retirement
end-state, Tony-approved 2026-10-29). Do NOT re-enable. Confirmed for the
4th time today; the real subject of this session was the *respawn loop*
that kept regenerating this alert.

## Live verification (2026-11-08 ~13:32 +07)

- `ssh idc03`: `chaba-jobs.timer` = `disabled`/`inactive` — matches census
  (`ssot.audit.hosts.yml` idc03 entry, `expected_state: inactive`).
- Replacements armed and firing on idc03: `yomi-update-active` (10 min
  ago), `embed-lane-news` (45 min), `yomi-update-all` (31 min),
  `embed-lane-lessons` (daily, 21 h). Nothing starved.

## Root cause of the respawn loop (new finding this session)

Card comms showed `re-spawned from report page` at 13:10 and 13:29 — each
re-arms `action.status=queued`, and kanban-dispatch spawns a session.
Source: the **stale sentinel on tony-omen**. Its exec checkout still had
`chaba-jobs` in `timer-sentinel.py` CRITICAL because tony-omen's
`chaba-repo-sync.timer` runs **hourly** (last pull 13:00; the sentinel fix
merged to master at ~13:15). Sequence per ~10-min sentinel sweep:
disabled timer → card closed → `POST /card on_exists:queue` → re-arm →
dispatch. Four dispatches (131205, 131613, 131641, 133100) for one false
alert.

## Action taken

- `systemctl --user start chaba-repo-sync.service` on tony-omen (ran its
  own git-safe-pull early — safe, routine). Finished 13:33:18; checkout
  now at `a2657537d` with the fixed CRITICAL set (`chaba-jobs` removed).
- Verified post-sync: `timer-sentinel.py` line 52 `CRITICAL =
  {"kanban-commit", "kanban-dispatch", ...}` — no chaba-jobs.
- Posted evidence comment; closed card via `/action do=close`
  (`moved to done`). Next sentinel fire 13:39 uses fixed code + census
  `expected_state: inactive` → cannot re-arm.

## Residuals / follow-ups

- **tony-omen repo-sync cadence is hourly** while dell/idc03 run 15-min —
  up to ~60 min of stale-sentinel window after any sentinel fix merges.
  Worth a card if today repeats: either tighten tony-omen's cadence or
  give sentinel-declaration fixes a faster propagation path. (Duplicate-
  spawn race already carded: `kanban-dispatch-spawned-duplicate-sessio-f49ed8`.)
- idc03 `~/.config/systemd/user/chaba-jobs.{service,timer}` files remain;
  removal belongs to the OPS-0790 cleanup commit (flip census to
  `expected_state: absent` if deleted).
- tony-dell `chaba-jobs.timer` still enabled doing no-op ticks +
  `lesson-drift-check.timer` never armed — tracked on
  `chaba-jobs-dispatcher-dead-fleet-wide-di-765e5b`.

## How to verify

```
ssh idc03 systemctl --user is-enabled chaba-jobs.timer   # -> disabled
ssh tony-omen 'grep -n "CRITICAL =" ~/CascadeProjects/chaba/scripts/ada/timer-sentinel.py'
# -> no chaba-jobs
# board: timer-alert-idc03-chaba-jobs stays column=done past 13:39 sentinel fire
```
