# board-api — the read door (card ops-manual-command-api-mcp-efficiency-audit, AUD-1033)

**Status:** merged on dispatch branch; promotion to idc03's served
checkout happens through the normal merge path (board-api runs from
`chaba-tony-dell`). Companion to `board-api-write-door.md` — the write
side is unchanged.

## Rule

**Never fetch the whole board to answer one question.** `/cards` is
5.2 MB and growing (1136 cards / 15.7k comms entries measured
2026-10-31). Every read has a smaller projection — use the narrowest one
that answers the question.

| need | call | cost class |
|---|---|---|
| one card's state | `GET /card/<id>` | ~2-4 KB |
| one field of one card | `GET /card/<id>?fields=column,updated` | <300 B |
| board index / "what's where" | `GET /cards?compact=1` | ~220 KB |
| queued/claimable set | `GET /cards?action_status=queued&fields=id,title,action,blocked_by,priority,updated` | ~2 KB |
| or the ready projection | `GET /queue` | ~2 KB |
| "did anything change since T" | `GET /cards?since=<updated-string>&fields=id,updated` | KBs |
| one column | `GET /cards?column=doing[&fields=…]` | small |
| whole rendered board (export only) | `GET /cards` | 5.2 MB — last resort |

## Response contract

`GET /cards?<query>` → `{ok, count, total, offset, truncated, cards[]}`.

- **filters** (AND): `id`, `column`, `action_status`, `since`
  (lexicographic compare vs `updated` — same "YYYY-MM-DD HH:MM" format).
- **projection**: `fields=a,b,c` — top-level keys only; absent keys are
  dropped, unknown ignored. `compact=1` is the canned slim set
  `{id,title,column,updated,priority,ref}` and wins over `fields`.
- **pagination**: `limit` (cap 1000), `offset`; `truncated:true` means
  more pages exist. Order: filters → pagination → projection, so
  `total` is the filtered count.
- `GET /card/<id>` → `{ok, card}` | 404 `{error:"card not found",id}`;
  `GET /card` bare → 400 with `hint`.
- Bare `GET /cards` is the legacy payload, untouched — existing
  consumers keep working.

## Read-side checklist for agents

1. One card → `/card/<id>` (never `/cards` + grep).
2. "My card" during a dispatch → `/card/<id>?fields=` the fields you
   need (usually `column,updated,requests,comms` — comms only when you
   actually read them; it's the heavy field).
3. Watching for a change → `since=` + `fields=id,updated`, not a full
   re-fetch; the payload's `generated` stamp is the version token.
4. Fleet/queue state → `/queue` (already the compact projection with
   per-runner verdicts).
5. Writes stay exactly as before — POST door, tailnet identity; nothing
   in this doc changes mutation rules.

## Notes

- Reads are open (same as `/cards` today — the board renders this data
  to the tailnet anyway). No new secret surface.
- Every GET logs one stderr line → journald `chaba-board-api` — that
  request log is the audit event; there is no per-read event record.
- Served from the rendered `cards.json` — bounded file read, no upstream
  call, no timeout risk beyond disk. If the render is stale the read is
  stale; `/queue` faces the same caveat.
- Idempotent by construction; retry freely. For change detection prefer
  `since=` over diffing full payloads.
- Benchmark + fixture harness: `scripts/board/board_read_bench.py`
  (numbers: `docs/reports/board-read-bench-2026-10-31.md`) — claim-poll
  shape is 99.97% smaller than the dump at equal evidence.
