# Dispatch outcome — rebuild gesture controls using YOLO

Card: `rebuild-gesture-controls-using-yolo-190356` · attempt 2
Branch: `dispatch/20261120-215246-rebuild-gesture-controls-using` · commit `5307864`
Result: **implemented + verified green** (full suite: 1877 passed / 7 skipped)

## What changed

Gesture controls rebuilt on the shared YOLO pose stream — no competing
camera consumer. `GestureService` subscribes `pose_service.results()`
(same stream posture/visual-habits use: Hailo `yolov8s_pose` with
MoveNet fallback).

- `backend/gesture_controls.py` — `GestureController` state machine
  (wave arms the controller with raise-hysteresis + arm timeout;
  per-hand trajectory windows detect horizontal swipes with
  horizontal-dominance rejection; palm-hold dwell opens settings;
  downward drop dismisses; per-gesture cooldown) and `GestureService`
  (enabled flag persisted via `PostureStore.monitor_state`, fan-out to
  ws subscribers).
- `backend/main.py` — service lifecycle, `GET /api/gestures`,
  `PATCH /api/gestures` (422 on non-boolean), `/ws/gesture`
  (status snapshot on connect, then live events).
- `frontend/` — gesture status chip + settings toggle
  (`gesture-status`/`gesture-toggle`), `connectGestureSocket` with
  reconnect, `GESTURE_PANELS` order, swipe→panel navigation,
  palm-hold→settings, drop→dismiss, REST toggle.
- `backend/tools.d/gesture_controls.py` — ada-ha tool:
  `op=status` (GET) / `enable`/`disable` (PATCH) vs `ADA_PI_URL`
  (default `http://idc02:8000`); mutations run the standard
  confirm gate; honest `ok:false` when the companion is unreachable.
  manifest `policy: read` + internal per-action gate,
  `secondary_allowed: true`; `tool_guide.yml` entry;
  `ssot.tool-surface.yml` cap 114→115.
- `backend/tool_runner/__init__.py` — **latent bug fix** (this was the
  scenario failure): `_execute_gated` pops `confirmed`/`confirm_token`
  and re-injects them only when the bound method's signature declares
  them. For tools.d, the bound method is `_bound(**kwargs)` — the real
  `run()` signature was invisible, so `confirmed=true` resends could
  never satisfy a tools.d per-action gate. Now inspects
  `dyn_spec.run`. This also heals kanban's declared
  `confirmed`/`confirm_token` params, which have been dead on the
  dispatch path since the tool shipped.
- Tests — `tests/test_gesture_controls.py` (16 unit tests),
  frontend-contract assertions, `tests/scenarios/gesture_controls.yaml`
  (offline: unreachable-honesty + confirm gate + confirmed retry),
  `tests/scenarios-live/gesture_controls.yaml`.
- `docs/ssot/jobs/ada/2026-11-20-gesture-controls-yolo.yml` — job record.

## Attempt 1 postmortem

The prior run claimed the same architecture but exited nonzero; its
branch carried no commits — nothing to salvage. This run rebuilt from
`origin/main` and the new offline scenario immediately caught the
real defect: not the gesture code, but the runner's confirm-envelope
re-injection hiding tools.d signatures behind `**kwargs`.

## Verify

```
python3 -m pytest tests/test_gesture_controls.py tests/test_frontend_contract.py -x -q
python3 -m pytest tests/test_scenarios.py -x -q -k gesture
python3 -m pytest tests/ -x -q          # 1877 passed, 7 skipped
python3 scripts/tool-lint.py            # clean, 71 declared, cap 115
```

Not deployed / not pushed, per card rules.

lessons:
- tools.d confirm envelopes were silently dropped: `_execute_gated`
  re-injects `confirmed`/`confirm_token` only for signatures it can
  see — the `_bound(**kwargs)` wrapper hid every tools.d `run()`
  signature. Any tools.d per-action gate (kanban included) could never
  receive a confirmed resend until the spec.run inspection fix.
- Scenario `output_not_contains` collides with the appended tool_guide
  usage-hint text — keep assertion words out of guide copy or assert on
  result fields, not prose.
- Gesture test timing must out-space the controller's swipe window
  (0.9s) and event cooldown (0.5s): use ≥1.0s gaps or sample sets leak
  into the next gesture's trajectory window.
