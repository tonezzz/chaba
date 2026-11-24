# Dispatch outcome — rk600-empty-sensors-ok

## Finding

The requested fix is **already deployed upstream** — no code change was
needed in this worktree.

- `get_rk600_weather` (tool_runner/ha.py) delegates to
  `HomeAssistantClient.rk600_weather()` in the **ada-voice** repo
  (`~/CascadeProjects/ada-voice` on tony-dell — the edit point per
  ada-voice AGENTS.md). The chaba repo only holds staged patch drops
  under `integrations/ada-voice/`; none is required here.
- ada-voice commit `50fec81` ("OPS-0222: rk600_weather fails loud when
  station sensors absent", 2026-10-17) added exactly the requested
  behavior: empty `sensors` dict → `ok:false` +
  `"RK600 station offline/unreachable — no sensor.rk600* entities in
  Home Assistant. Do not retry; tell the user the station appears
  offline instead."` It also fails loud when all rk600* entities are
  `unavailable`/`unknown`.
- Commit `a67bea0` added a RikaCloud fallback (`_rk600_cloud_fallback`)
  that serves data when the HA path fails but the station is reachable
  via cloud — the offline verdict only surfaces when both paths fail.
- This matches the CMS `get` on-miss pattern (`ok:false` + actionable
  `error`/`note`, no silent success).

## Testable done-condition — verified

`tests/test_home_assistant.py` already contains
`test_rk600_weather_returns_ok_false_when_no_sensors` (plus
all-unavailable, present-sensors, cloud-fallback, and re-raise cases).
Ran the rk600 slice in a scratch uv venv:

```
/tmp/ada-test-venv/bin/python -m pytest tests/test_home_assistant.py -k rk600 -x -q
5 passed, 14 deselected
```

Note: tony-dell's ada-voice checkout has no project venv/pytest; tests
were verified in a throwaway `/tmp/ada-test-venv` (uv + python3.13,
pytest/httpx/websockets). The checkout is `main...origin/main [behind
123]` but already contains both fix commits.

## Card state

Posted a comms entry on `rk600-empty-sensors-ok` with the verification
evidence. The card can move to review/close — the work it describes was
completed by OPS-0222 on 2026-10-17 and simply never closed the card.

## Verify

```
cd ~/CascadeProjects/ada-voice
git log --oneline -3 -- backend/home_assistant.py   # 50fec81, a67bea0
grep -n "offline/unreachable" backend/home_assistant.py
grep -n "rk600" tests/test_home_assistant.py
```

lessons:
- The card's "chaba repo" phrasing is loose — `get_rk600_weather` lives
  in the ada-voice repo; check `integrations/ada-voice/` README before
  assuming chaba holds the source (it holds patch drops only).
- Before implementing a carded tool fix, `git log` the target file in
  the real repo — this one was already fixed under the same OPS ref
  (OPS-0222) a week before the card was dispatched.
- tony-dell ada-voice checkout has no venv; `uv venv` + `uv pip install
  pytest httpx websockets` into /tmp is enough to run
  tests/test_home_assistant.py.
