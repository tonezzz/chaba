# DevNest news watch procedure

Status: defined 2026-11-26 (card `devnest-news-watch-procedure`, ref OPS-0900;
first landed run: `docs/ssot/jobs/devnest/2026-11-26-news-watch-first-scan.yml`)

Keeps member-facing news current as DevNest advances, without turning every
routine run into a news item. The scan is cheap and runs often; publication
is rare and gated.

## Cadence

- **Daily scan** — last ~24h of activity. Cheap pass; most days produce zero
  items.
- **Weekly scan** — last ~7d. Catches slower threads (benchmarks, audits,
  spend trends) the daily pass would miss.

A dispatch of this card performs whichever window the trigger implies;
when in doubt run the weekly window — the publish gate, not the scan width,
controls noise.

## Scan sources

| source | where to look | what counts |
|---|---|---|
| board comments/status | `docs/ssot/kanban/cards/*.yml` comms (newest first), board-api `/comment` stream in git log | milestones Tony/agents marked verified, approvals, closures with evidence |
| git commits | `git log --since=<window>` — filter out `board-api comment/action`, `board: live card`, merge/checkpoint noise | feat/fix/docs with substance, job records |
| pack artifacts | `scripts/colab/packs/*/pack.yml`, `reports/` bench outputs, pack job records `docs/ssot/jobs/bench/` | completed benchmark runs with artifacts, not just pack prep |
| benchmark results | `reports/*bench*`, `reports/model-efficiency-*`, `reports/bench-*`, job yml `results:` blocks | measured deltas vs prior run, pass/fail changes |
| lessons | WP lesson CPT via board-api `/lesson op:list` (recent `learned_at`), `docs/kb/` additions | durable knowledge worth a pointer, not the lesson itself |
| audit reports | `docs/reports/audits*`, `docs/ssot/jobs/security|infrastructure` recent, `scripts/audit-*.py` outputs | confirmed root causes, fixed failure loops |
| cost/usage | `reports/lane-savings-*`, `docs/reports/*spend*`, ada-spend-ledger cards, LiteLLM budget-watch cards | verified savings or material spend changes — never estimates |

## Publish gate — newsworthy triggers only

Publish (or update) ONLY when an item hits one of:

1. **First production milestone** — a capability went live for real users
   (e.g. actuation enabled on pilot hosts).
2. **Verified benchmark delta** — measured before/after or vs-baseline result
   with artifacts (`confidence: measured|verified`).
3. **Real savings** — evidenced cost reduction with numbers and source.
   Estimates and "should save" do not qualify.
4. **New capability** — a lane/tool/pack proven working end-to-end.
5. **Important failure/root cause** — a crash loop, wedge, or incident with
   confirmed root cause and fix evidence.
6. **User-visible interface** — something Tony actually sees changed.

NOT newsworthy: routine dispatches, card bookkeeping, defer/claim churn,
runner-agent drift notices, heartbeat/progress events, pack *prep* without
results, budget cap changes that are pure ops hygiene.

## Item contract

Every published item carries:

- **evidence link** — at least one: card id, commit sha, report path, or job
  yml. `/publish` rejects `kind:news` without `evidence[]`.
- **date** — `occurred_at` of the underlying event, not the scan date.
- **impact** — one line: what changes for Tony/the fleet.
- **before/after** — concrete states, not adjectives.
- **confidence** — `observed|measured|verified`; `public` visibility
  requires `verified`.
- **next step** — what happens next or what to watch.

## Clustering and threading

- One news story = one canonical event = one WP `news` CPT post.
- The WP slug is derived from `event_id` (`pub-<event_id minus evt->`), so
  **re-using the same `event_id` updates the same post in place** — that is
  the "same evolving thread" path. Give each story a stable
  `evt-nw-<slug>-<date>` id and bump a `rev` in the body/meta on updates.
- A genuinely new thread gets a new `event_id` → new parent post. Never
  fork a story by varying the id.
- Cross-link, don't duplicate: news → Education (`/lesson`) for depth,
  SSOT job yml / card for decision state. The news body links to both.

## Publish mechanics

`POST https://idc03.taila0626a.ts.net:10000/publish` with a canonical
PublicationEvent (see `docs/kb/board-api-write-door.md` §/publish):

```json
{
  "kind": "news",
  "event_id": "evt-nw-<story>-<yyyymmdd>",
  "title": "...",
  "body": "impact + before/after + next step (markdown-ish; <h4>/<ul> render)",
  "source": "devin",
  "card": "<related card id>",
  "visibility": "members",
  "confidence": "verified",
  "occurred_at": "<ISO-8601 of the event>",
  "evidence": ["card:<id>", "docs/ssot/jobs/...yml", "reports/...md", "commit:<sha>"]
}
```

- **Visibility is private-first.** `private` → board comms + json ledger +
  wiki-private only. `members` → + WP private news post + Telegram. Use
  `members` for internal fleet milestones; reserve `public` for items Tony
  has confirmed (the governed `news-promotion-runner.py` path owns
  private→public promotion — never flip visibility ad hoc).
- Default `kind:news` sinks are `news, wiki, wiki-private, board,
  telegram`; capability gating drops sinks above the declared visibility,
  so `members` never touches the public wiki sink.
- Idempotency: identical events dedupe on `idempotency_key`; a changed body
  with the same `event_id` still upserts the same WP post — safe to re-run.
- Sibling sinks record per-sink receipts (`delivered|queued|skipped|
  suppressed`); a `skipped` with reason is information, not failure. Run
  `{op:"drain"}` if `pending` is non-zero.

## Verify (consumer proof, not just producer proof)

1. `/publish` response receipts — every expected sink `delivered`.
2. Fetch the member news surface (WP `news` CPT list / board page) and
   confirm the post exists with the expected slug `pub-nw-...`.
3. Write the scan record: `docs/ssot/jobs/devnest/<date>-news-watch-scan.yml`
   listing scanned sources, candidates rejected by the gate (with reason),
   and items published with their event ids.

## Failure modes to avoid

- Publishing pack-prep or "ready to run" as if the benchmark ran.
- Counting card `done`/merge-sweep closures as news — they are bookkeeping;
  the *content* of the verified work is the story.
- Secrets, speculation, or savings without a measured baseline.
- Letting the news CPT become a second SSOT — it links to SSOT/job records,
  it does not restate them.
