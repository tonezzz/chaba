# Dispatch outcome — timer-alert-tony-dell-chaba-board-render

## What was found

- **Root cause (verified in journal on tony-dell):** `render-board.py`
  `compute_checks()` crashed with `AttributeError: 'str' object has no
  attribute 'get'` — card `stt-omen-large-v3` had a bare string in its
  `comms` list and the deploy-mention genexpr assumed dicts. 114
  `result=exit-code` failures between 2026-10-15 12:59 and 10-16 ~19:30.
- **Already fixed:** commit `d4545bc1` (10-16 19:31, "render-board:
  tolerate non-dict comms entries") added `isinstance(m, dict)` filtering;
  renders succeeded from the next tick.
- **Migration state:** the dell units were parked (`*.parked`) the same
  evening by the phase-2 single-writer move to idc03 — no dell runs since
  10-16 19:32, which is why the sentinel stopped re-flagging. On idc03 the
  60s timer is healthy (verified today, 828 cards rendered). The one idc03
  failure (10-18 22:12, file-not-found) coincided with the .git-corruption
  repair window, not a code fault.

## What changed

- **idc03 unit drift fixed:** the installed `chaba-board-render.service`
  predated the `board-render-guard` wrapper (ExecStart ran both renderers
  directly). Deployed the canonical `systemd/chaba-board-render.service`
  (guard ExecStart, from `71adbc26`) to `~/.config/systemd/user/` on idc03,
  `daemon-reload` + manual run verified exit 0, next timer tick clean. Old
  unit kept at `chaba-board-render.service.bak-pre-guard`.
- **Trail:** `docs/ssot/jobs/monitoring/2026-10-20-chaba-board-render-timer-alert.yml`
- **Card:** findings posted as comment; card closed via board-api
  (`moved to done`).

## How to verify

- `ssh idc03 'systemctl --user status chaba-board-render.service'` —
  ExecStart must be `scripts/board/board-render-guard.py`, status 0.
- `ssh idc03 'journalctl --user -u chaba-board-render.service -n 20'` —
  clean 60s ticks.
- `ssh tony-dell 'ls ~/.config/systemd/user/ | grep board-render'` —
  `.parked` (intentional post-migration).
