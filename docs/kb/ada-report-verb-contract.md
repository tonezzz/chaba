# Ada Report-Verb Read Path Contract

How Ada answers "how are jobs" (and sibling fleet-status asks) — producer/consumer
split: a scheduled job renders the artifact, Ada only ever reads it.

## Trigger intents

Voice/chat asks that map to the `fleet-jobs-report` page:

- "how are jobs" / "job status" / "what is the fleet doing"
- "are any timers failing" / "which hosts are having trouble"
- "how much did we spend" (LiteLLM section) / "what are the lanes doing"
- "is the dispatch queue moving" / "who's working on what"

## Read path (the only permitted path)

1. `POST {MDDB_BASE_URL}/get`
   `{collection: "ada-cms-pages", key: "fleet-jobs-report", lang: "en"}`
   → returns `{contentMd, meta}` in one local read. Sub-second; no compute.
2. Apply the freshness gate (below) on `meta.updated` vs `meta.fresh_for`.
3. Summarize 2–4 spoken sentences from the rendered sections — never
   paste tables or raw JSON at the user.

Fallback order if the primary key is absent: none — say the report has not
been generated yet and offer to file it. Do not substitute live sources.

## Freshness gate

| `meta.updated` age vs `fresh_for` (4h) | Ada's answer |
|---|---|
| fresh | answer normally from the page |
| stale | same answer, prefixed "as of <updated> …" — flag that the producer may be down |
| page missing / MDDB unreachable | "the fleet jobs report hasn't been generated yet" — offer to card it; never improvise from other tools |

## NEVER on a voice turn

- Never run `scripts/fleet-jobs-report.py` or any producer.
- Never call board-api `/cards`, `/queue`, or the kanban directly to
  assemble an answer.
- Never `psql`, `ssh`, `systemctl`, or journal-grep a host.
- Never spawn a dispatch/sub-agent for a status question.

Rationale: every one of those costs seconds-to-minutes and load; the page
is rebuilt on a fixed cadence so the answer is always one read away. If the
page is stale, the correct action is surfacing the staleness (and letting
report-watch/inbox do its job), not recomputing inline.

## Producer contract (what keeps the page true)

- Job `fleet-jobs-report` in `docs/ssot/infrastructure/ssot.jobs.yml`
  (host: idc03, `every: 4h`, deterministic — no LLM).
- `scripts/fleet-jobs-report.py` reads: MDDB `ada-cms-pages/timer-timeline`
  rollup, board-api `/queue` + `/cards` projection, LiteLLM spend ledger,
  `scripts/board/lane-savings.py`, `docs/ssot/generated/jobs.<host>.yml`.
- Writes `reports/fleet-jobs-<date>.md` + `reports/meta.fleet-jobs-report.yml`
  (L2-domain node in `ssot.reports.yml`), appends the report timeline, and
  upserts the `fleet-jobs-report` page via board-api `POST /report`
  (mode=create, meta `fresh_for: 4h`, `layer: L2-domain`).
- Meta `status`: `ok` clean, `delta` findings present (e.g. failing
  timers), `error` a source or the publish failed — `source_errors` /
  `publish_error` in `meta.extra` say which.

## Page anatomy (what Ada can cite)

`## Fleet Claim Totals` (queued/claimed/running/done/failed + unassigned),
`## Runner Fleet` (queue depth + per-runner heartbeat age/stale/active work),
per-host `## Host: <h>` (declared vs observed timers, ok/late/failing/off
counts, failing-timer table, assigned card actions), `## Lanes` (action
status by lane + evidence-bound usage), LiteLLM 24h spend table.

## Wiring status

The ada-voice tool that binds the trigger intents to this contract is the
follow-up card `ada-voice-fleet-jobs-verb` (separate repo, action: manual).
This document is its spec; keep the two in sync if the read path changes.
