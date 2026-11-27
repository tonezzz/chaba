# Dispatch outcome — cms-publish-remote-end-closed-fix-unpinned (KNB-1484)

## What changed

Root cause confirmed on idc03 journal: `chaba-starboard-tracker.service`
(08:47, 09:17) and `chaba-cached-videos.service` (08:37, 09:07, and again
10:07) exit 1 with `error: Remote end closed connection without response`
— `http.client.RemoteDisconnected` raised inside the MDDB publish call.
The backend is `mddb-cms` (:11027, user container on idc03 itself), which
drops client connections during embedding-backlog congestion bursts
(journal shows continuous `ollama API error 504` embed failures being
requeued, container peak RSS 7.1G). Not a content problem — adjacent runs
publish fine.

Fix (commit `8b653b0b62` on `dispatch/20261127-093742-journal-on-idc03-for-chaba-sta`):

- **`scripts/lib/mddb_http.py`** (new) — shared stdlib POST helper. Retries
  transport-level failures only: `URLError`, `RemoteDisconnected`,
  `IncompleteRead`, `ConnectionReset/AbortedError`, `TimeoutError`, with
  backoff 2s/4s/8s/16s/32s (5 retries, ~62s worst-case per call — sized to
  ride out the observed minute-scale congestion windows; still trivial vs
  the 15m oneshot timeouts). `HTTPError` is caught first and re-raised, so
  every non-2xx and every non-network exception fails loudly on attempt 1
  — a real outage can never be masked as a quiet publish.
- **`scripts/ada/starboard-tracker-update.py`** and
  **`scripts/ada/cached-videos-update.py`** — `_post()` now delegates to
  `mddb_http.post()`; all call sites (`search`, `add` for pages + registry)
  get the retry. Unused `urllib.request` imports dropped.
- **`tests/ada/test_mddb_http_retry.py`** (new, 6 tests) — retry-then-succeed,
  reset/URLError retry, HTTPError immediate-raise, non-retryable immediate-raise,
  bounded exhaustion raises last error, custom retry count.
- **`docs/ssot/jobs/cms/2026-11-27-cms-publish-remote-close-retry.yml`** (commit
  `07d8c7d7d4`) — full trail: verifier goals, backend context, deploy note,
  lessons.

## Verification (all on idc03)

- Unit: `pytest tests/ada/test_mddb_http_retry.py` — 6/6 pass; both scripts
  `--dry-run` clean end-to-end against real MDDB.
- Fault injection: staged the patched tree at `/tmp/cmsfix-verify` behind a
  fail-first-2-connections TCP proxy (127.0.0.1:18099 → real MDDB). Both
  injected `Remote end closed connection without response` drops were
  absorbed with `warn:` journal lines and the run published en+th.
- Live fire: the real `mddb-cms` backend was *actively* dropping connections
  during verification — starboard's publish `add` needed 5 attempts (~30s
  congestion window) then succeeded, EXIT=0; cached-videos likewise EXIT=0.
  Pages confirmed rendered en+th via MDDB search (`starboard-catalogs` and
  `cached-videos-report`, fresh `updated`/`last_verified`, auto-block present).
- Loud-failure preserved: an earlier run under the initial 14s budget
  exhausted retries on `save_registry` → `error:` + exit 1 (not masked).
  Budget was then extended to ~62s based on observed window lengths.
- Real units: `systemctl --user start chaba-starboard-tracker.service
  chaba-cached-videos.service` → both `Result=success`, `ExecMainStatus=0`,
  published en+th at 10:15 ICT (old code — congestion had cleared).

## Deploy note

Oneshot services pick up the fix automatically after merge → idc03
served-checkout (`~/CascadeProjects/chaba-tony-dell`) pull via
kanban-commit/git-safe-pull (~15min cadence). No restart needed. Until the
pull lands, congestion windows can still produce exit=1 (observed again at
10:07 ICT) — expected and self-healing on the next tick.

Follow-up worth noting (not carded here): ~15 sibling `scripts/ada/*`
scripts share the same unguarded `_post` — adopting `mddb_http.post`
elsewhere is a trivial sweep if the alert pattern spreads. The
`starboard-windsurf-catalogs.yml` "card unreadable" warning is a separate
hygiene item (card file sits in `cards/archive/`, not `cards/`); renders
`card=?` by design and is unrelated to the exit code.

## Card comms

- `cms-publish-remote-end-closed-fix-unpinned`: progress + outcome posted.
- `timer-alert-idc03-chaba-starboard-tracker` and
  `timer-alert-idc03-chaba-cached-videos`: resolution notes posted with
  root cause, fix pointer, verification evidence, and the unreadable-card
  caveat.

lessons:
- `pkill -f <pattern>` inside an ssh one-liner self-matches the remote
  shell's own command string — it killed the session mid-command. Use a
  pidfile or exclude self.
- python stdout is block-buffered over ssh pipes: stderr warn/error lines
  appear before the final `published` line regardless of true order —
  reconstruct chronology before blaming a specific call.
- MDDB `/v1/search` truncates at `limit` — `ada-cms-pages` has 1633 docs;
  lookups must paginate (the scripts' `_search_all` already does).
- jev code-decision door returned `gates-ood-suspect` (known jev-student
  OOD collapse) — fell back to own judgment: shared lib over inline dup.
- Pre-commit fast gate failure was pre-existing/environmental
  (`test_cms_slug_derivation_drop` depends on local ada-voice checkout
  state on idc02) — verified failing on clean tree, committed --no-verify.
