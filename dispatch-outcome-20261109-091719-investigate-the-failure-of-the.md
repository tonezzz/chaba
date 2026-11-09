# Dispatch outcome — timer-alert-idc03-ada-memory-sync (2026-11-09)

## Task
Investigate `ada-memory-sync.service` exit-code failure on idc03 (card note: last
run 10-16 14:00). Inspect `journalctl --user -u ada-memory-sync.service` on idc03
and reference CMS `timer-timeline-idc03`.

## What was found (root cause)

`ada-memory-sync.timer` runs hourly on idc03; it invokes
`scripts/ada/sync-ada-memory-to-mddb.py` (in the `~/CascadeProjects/chaba-vault`
checkout) twice per run — `--export-inbox` then `--resolve-voice`. The unit talks
to MDDB at `http://100.102.134.91:11023/v1` (mddb memory plane on idc03 itself).

Failures in the journal (user journal covers current boot from 2026-10-29):

- **2026-11-08 05:00:12 — RemoteDisconnected** on `POST /v1/add` inside `sync()`.
  The weekly `mddb-restart.timer` (Sun 05:00, next 11-15) restarted `mddb.service`
  exactly while the sync's add request was in flight — server closed the
  connection mid-request.
- **2026-11-09 04:01:07 — ReadTimeout (read timeout=20s)** on `POST /v1/add` in the
  same code path (`sync-ada-memory-to-mddb.py:267 -> Mddb.add -> _post:147`).
  Correlated mddb.service log shows the embedding path fully degraded ~03:58–07:01:
  `embed-pool-shim` reported "all same-space providers down (OR circuit-open +
  Gemini failed)" and the Gemini fallback returned HTTP 429 (rate limit). mddb
  retries embeds inline (~3 attempts × ~10 s ≈ 30 s per doc), so an `/add` that
  needed an embed blew past the client's fixed 20 s read timeout.
- The **original 2026-10-16 14:00 failure** predates the journal's oldest entry
  (boot starts 10-29), but it was already diagnosed on 10-24 (card comms): the
  script exits 1 BY DESIGN when unresolved vault-vs-MDDB conflicts exist — it's a
  residual "finding-reporter" not yet migrated to the exit-0 contract
  (`docs/kb/timer-expectations.md`). Resolved then via `--take-remote`.

Both new failures are **transient infrastructure events** (mddb restart; embed
pipeline degradation), not script bugs — and the sentinel alert was CORRECT:
each was a genuine non-completion that self-healed on the next hourly run.

## Current state — verified

- `systemctl --user show ada-memory-sync.service` on idc03: `Result=success`,
  `ExecMainStatus=0`; last run 2026-11-09 09:02.
- CMS `timer-timeline-idc03` (ada-cms-pages on mddb-cms :11027): `ada-memory-sync`
  row = enabled / last 11-09 09:02 / **success / 0 consecutive failures**.
- Embed errors ceased ~07:01; all hourly runs 05:00–09:02 on 11-09 succeeded.

## Actions taken

- Posted full root-cause diagnosis to card `timer-alert-idc03-ada-memory-sync`
  via board-api `/comment` (done-condition: root cause documented in card
  context; unit also green).
- Filed follow-up card `ada-memory-sync-transient-mddb-hardening` (MEM-1253):
  retry/backoff in `Mddb._post`, timeout bump, or move timer off :00 to avoid
  the Sun-05:00 mddb-restart collision; fold into pending exit-0 contract
  migration.

## How to verify

```
ssh idc03 'systemctl --user show ada-memory-sync.service -p Result,ExecMainStatus'
# -> Result=success ExecMainStatus=0
ssh idc03 'journalctl --user -u ada-memory-sync.service --since "2026-11-09 03:50" --until "2026-11-09 05:00" --no-pager | tail -60'
# -> ReadTimeout traceback to 100.102.134.91:11023 at 04:01:07
# CMS: ada-cms-pages key "timer-timeline-idc03" on :11027 -> success / 0 failures
```
