# Dispatch outcome — weather-bakeoff-ha-config-bounded-retry

## What changed

`scripts/ada/weather-bakeoff.py`:

- Added `_urlopen(req, timeout)` — wraps `urllib.request.urlopen` with
  bounded retry: `_RETRY_ATTEMPTS = 3` total attempts, `_RETRY_BACKOFF_S =
  (0.5, 1.0)` (worst-case added sleep 1.5s, well under the 5s cap).
- Retryable: `ConnectionResetError`, `ConnectionAbortedError`,
  `socket.timeout`/`TimeoutError`, `urllib.error.URLError`,
  `http.client.RemoteDisconnected`/`IncompleteRead`, and `HTTPError`
  with `code >= 500`.
- `HTTPError` < 500 and all non-transient exceptions raise on the first
  attempt, unchanged. The success path is untouched — same request
  construction, same `timeout` semantics, same return values.
- `http_json()` and `http_bytes()` both route through `_urlopen`, so the
  `{ha_url}/api/config` read in `main()` (~line 534) and every other
  fetcher using these helpers get the retry. `ha_daily()` still calls
  `urlopen` directly — left alone per scope (it is already wrapped in
  try/except at the call site in `main()`/`rain_check()`).

New test: `tests/ada/test_weather_bakeoff_http_retry.py` — 7 tests:
reset-then-success, persistent failure raises last error with bounded
calls/delays, HTTP 5xx retried, HTTP 4xx immediate, non-transient
immediate, `http_bytes` shares retry, success path single-attempt.

## Result

- Branch: `dispatch/20261127-182454-root-cause-scripts-ada-weather`
- Commit: `ce1c4ef8ad3` (not pushed — per dispatch rules)
- `python3 -m py_compile scripts/ada/weather-bakeoff.py` — clean
- `python3 -m pytest tests/ada/test_weather_bakeoff_http_retry.py -x -q`
  — **7 passed in 0.79s**

## Verify

```
python3 -m py_compile scripts/ada/weather-bakeoff.py
python3 -m pytest tests/ada/test_weather_bakeoff_http_retry.py -x -q
```

## Notes / follow-ups

- The chaba merge test gate (`REPO_TESTS["chaba"]` in
  `scripts/board/dispatch_repos.py`) runs a fixed file list; this new
  test module is not in it, so it contributes no merge-gate evidence.
  Adding it there is a separate decision (it would lengthen the gate).
- Deployment to idc03 (kraut-rain-watch unit) requires separate approval
  per card guardrails — no deploy, no ssot.jobs.yml or rendered-unit
  changes were made.

lessons:
- weather-bakeoff.py is hyphenated — tests load it via
  `importlib.util.spec_from_file_location` (same pattern as
  test_flood_alert.py / test_bank_inspect.py), not sys.path import.
- `urllib.error.HTTPError` is a `URLError` subclass — except order must
  check HTTPError first to keep 4xx loud while retrying 5xx.
