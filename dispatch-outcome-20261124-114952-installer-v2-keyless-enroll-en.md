# Dispatch outcome — installer v2 keyless enroll endpoint (attempt 2, stale re-run)

**Card:** fleet-installer-v2 · **Runner:** idc02 · **Branch:** dispatch/20261124-114952-installer-v2-keyless-enroll-en

## Result: ALREADY COMPLETE — card was done+archived 2026-11-08; re-verified live today, no code change needed

### What I found

- The card's full trail (archived copy at
  `docs/ssot/kanban/cards/archive/fleet-installer-v2.yml`) shows the work
  finished on **2026-10-26** across two dispatches: `/enroll` endpoint
  live on input-bridge, installer v2 report-back deployed, CF DNS record
  created, both verified end-to-end, auto-closed by merge-sweep, and the
  card archived 2026-11-08 ("13d in done, verified"). The "prior failure"
  note in the dispatch primer has no detail because there was no failure —
  this run is a **stale re-dispatch of an archived card**.
- The card is absent from the live board (`/cards` on board-api returns
  699 cards, none matching) — only the archive file exists.

### Re-verification performed today (consumer proof, not memory)

- `POST https://api.surf-thailand.com/enroll` `{hostname:
  dispatch-verify-20261124, lan_ip: 192.0.2.10, tailnet_ip:
  100.127.255.254, role: audit}` → `200 {ok:true, event:true,
  deduped:false}` — node registry upserted AND ops event emitted.
- `POST https://app.surf-thailand.com/enroll` (same payload) →
  `200 {ok:true, deduped:true, enrolls:2}` — second edge routes to the
  same input-bridge; dedupe window suppressed a duplicate ops event
  exactly as designed.
- MDDB `ada-ha-events-tony` confirmed holding
  `ops-host-enroll-dispatch-verify-20261124-1795496172048` with meta
  `written_by=input-bridge-enroll`, host/lan_ip/tailnet_ip/ts — the
  stick-announce `host_online` contract shape.
- `GET https://app.surf-thailand.com/install` → 200 (v2 script);
  `GET https://api.surf-thailand.com/install` → 200 v2 script;
  `dig app./api.surf-thailand.com` → Cloudflare proxy IPs (A record
  `app. → 157.85.102.125` proxied, minted 2026-10-26).
- `GET /nodes` intentionally not routed publicly (404 via edge) — matches
  the documented limit.

### Changes made this run

- `docs/ssot/jobs/infrastructure/2026-10-26-installer-v2-enroll-endpoint.yml`
  — appended a `reverification:` block recording today's evidence.
- Card comms: posted a status comment via board-api (tailnet endpoint
  `https://idc03.taila0626a.ts.net:10000` — 127.0.0.1:8787 is idc03-local
  and unreachable from idc02). Comment landed on the archived card
  without resurrecting it (verified: still absent from `/cards`).

### Process note for the dispatcher

The dispatch queue re-armed an archived card. If this recurs, the
queue/sweep that feeds devin-dispatch should filter `column: done` /
archived cards before spawning — the card YAML's `action.status: done`
+ `verified: true` was already set on 2026-10-26.

### Verify

```
curl -sX POST https://api.surf-thailand.com/enroll \
  -H 'Content-Type: application/json' \
  -d '{"hostname":"<any>","lan_ip":"192.0.2.1","tailnet_ip":"100.127.0.1"}'
# -> 200 {ok:true,event:true|deduped}
curl -s https://app.surf-thailand.com/install | head -3   # v2 script
```

lessons:
- devin-dispatch can re-fire on archived kanban cards — check the card's `column`/archive status and comms BEFORE doing work; a stale re-run should verify-and-report, not redo.
- board-api is not on 127.0.0.1:8787 from non-idc03 hosts — use `https://idc03.taila0626a.ts.net:10000` (tailnet serve) or `scripts/board/board-cli.py --ssh idc03`.
- Posting a /comment to an archived card via board-api succeeds without resurrecting it — safe way to leave a note on done work.
