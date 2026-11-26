# Dispatch outcome — state-write-atomic-truncate-crash-loop

## What was wrong

Three idc03 services crash-looped because their JSON state files were
truncated to 0 bytes: `open(STATE, "w")` / `Path.write_text` truncates
immediately, so a SIGKILL/timeout mid-`json.dump` leaves a file that
exists-checks pass but `json.load` dies on — every subsequent run fails
on JSONDecodeError. Verified live: all three state files were 0 bytes
(chaba-nag.json since Nov 24, wp-timeline-state.json and
rika-wx-alert/state.json since Nov 19).

## What changed (repo, this branch)

- `scripts/chaba-nag.py` — new `load_state()` (tolerant: missing/empty/
  corrupt -> {}) and `save_state()` (write `STATE.tmp` + flush + fsync +
  `os.replace`); `main()` uses both.
- `scripts/ada/line-chat-timeline.py` — same helpers; `state["media"]`
  shape re-validated on load so a wrong-shape file can't KeyError later.
- `scripts/rika-wx-alert.py` — NEW canonical repo copy (previously
  existed only as `~/.local/bin/rika-wx-alert.py` on idc03, unversioned).
  Same helpers, plus torn `token.txt` now falls back to re-login instead
  of crashing.

Pattern matches the repo's existing tmp+replace idiom
(scripts/ada/lane-retention.py, wp-comment-sync.py) with fsync added per
scripts/board/card_io.py's ENOSPC/delayed-allocation rationale.

## Live repair on idc03 (task explicitly targeted these services)

- Deployed repo copies to `~/.local/bin/` (md5-verified identical);
  originals kept as `*.bak-20261125`.
- Parked the three 0-byte state files as `*.0byte-20261125`.
- `systemctl --user start` on all three units -> `Result=success`,
  `ExecMainStatus=0`; all three state files re-written as valid JSON.
  line-chat-timeline posted all 4 lane updates (kk-ha 207, tony-ha 98,
  ada-ha 0, ops 1723 items) — first clean run since Nov 19. chaba-nag
  pushed its LINE nag successfully — first clean run since Nov 24.
- Note: `~/.local/bin/line-chat-timeline.py` was a stale Oct-14 copy
  missing the merged activity-dedupe feature; deploying the canonical
  repo version also resolved that drift.
- `chaba-nag.service` runs from the served checkout
  (`~/CascadeProjects/chaba-tony-dell`), so it picks up the atomic-write
  fix on the next pull after this branch merges — it already recovered
  via the parked state file and is not crash-looping meanwhile.

## Sweep result

`find ~/.local/state ~/.local/share/ada -name '*.json' -size 0` on idc03
shows no other 0-byte state files. Repo-wide audit: ~20 other scripts
share the non-atomic `STATE.write_text(json.dumps(...))` pattern but all
have tolerant loads (no crash-loop today) — filed as follow-up card
OPS-1364 (`systemic-sweep-non-atomic-state-write-te-040822`).

## How to verify

- `python3 -m py_compile scripts/chaba-nag.py scripts/ada/line-chat-timeline.py scripts/rika-wx-alert.py`
- On idc03: `systemctl --user status rika-wx-alert line-chat-timeline chaba-nag` — all `Result=success`;
  `python3 -c "import json; json.load(open('<state-file>'))"` on each state path.
- Trail: `docs/ssot/jobs/infrastructure/2026-11-25-atomic-state-writes.yml`

lessons:
- line-chat-timeline's live unit runs `~/.local/bin/` copy, not the repo path — repo fixes don't reach it without an explicit deploy; the deployed copy had also drifted stale (missing merged activity-dedupe). Check `systemctl --user cat <unit>` ExecStart before assuming repo==live.
- rika-wx-alert.py had no repo home at all — ops scripts deployed straight to ~/.local/bin drift invisibly; bringing it into scripts/ was part of the fix.
- The fatal combo is strict-load + non-atomic-write; most repo scripts already tolerate bad state, which is why only these 3 crash-looped — audit both halves before scoping a sweep.
