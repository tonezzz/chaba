# Ada ↔ kanban access — design

**Status:** proposed (kanban: `ada-kanban-access`)
**Ask (2026-10-06, Tony):** Ada should be able to review and take action
on the kanban — how, and with what standard.

## 1. The channel already exists

`scripts/board/board-api.py` (tony-dell :8787) is the sanctioned write
path — its own docstring: *"ALL card writes must go through this API —
any direct card-YAML edit races the served checkout."* Endpoints:

| Verb | Endpoint | Effect |
|---|---|---|
| list | `GET /cards` | board payload |
| act | `POST /action {id, do}` | queue/close/hold/retry/claim/move/finish |
| comment | `POST /comment {id, from, text}` | `from: ada` already allowed |
| ask | `POST /request {id, ask}` | file a question on a card |
| file | `POST /cards` (or request flow) | new card |

Writes land in the served checkout (`chaba-tony-dell/cards/`), the
`kanban-commit.timer` single-writer pushes them. No new git writer.

**The gap:** board-api binds `127.0.0.1` — reachable from idc03 only via
the Caddy `/apps/board-api` route, whose write gate wants a tailnet user
login. Ada is a headless service → denied.

## 2. The fix (small)

Mirror what report-api got today (`REPORT_API_BIND=0.0.0.0` +
`REPORT_API_TOKEN` bearer, 2026-10-06):

- board-api: `BOARD_API_BIND` + `BOARD_API_TOKEN` envs. `Authorization:
  Bearer <token>` → identity `'svc:ada'`; Caddy route unchanged for
  humans. Token in `~/.config/secrets/` on both hosts, never in repo.
- ada-pi: new tool group `kanban` (`backend/tools.d/kanban.py` +
  manifest):
  - `kanban_list(column?)` — titles+ids, capped
  - `kanban_read(id)` — full card incl. comms
  - `kanban_comment(id, text)`
  - `kanban_move(id, column, evidence=None)`
  - `kanban_ask(id, ask)` — requests to Tony
  - `kanban_file(title, note, priority?)` — new backlog card

## 3. The standard — what Ada may do

Scope: **triage and housekeeping, not judgment.**

| Action | Ada | Tony |
|---|---|---|
| list / read / comment / file backlog card | ✅ always | — |
| move `backlog→doing`, `doing→backlog` (her own work) | ✅ max 2 doing | — |
| move `review→done` | ✅ **only with `evidence:` arg** — a checkable fact she verified with a tool (service state, page live, log line) | — |
| triage `*-auto-*` cards (logs/disk/cms findings) | ✅ verify condition → comment + close if resolved | — |
| `review→done` on `priority: high` or prod/security posture | ❌ → `kanban_ask` instead | decides |
| `decide` review_kind cards | ❌ comment only | decides |
| delete / archive / reorder / reprioritize silently | ❌ | yes |
| move cards to `doing` >2 claimed | ❌ (same SLA as agents) | — |

**Audit:** every write must append a comms entry `from: ada` — already
the API's behavior. `kanban_move(..., evidence=...)` writes the evidence
into the comms text (`"verified: <evidence>"`), which is what makes a
machine-done card trustworthy.

## 4. Review loop (the "review HER kanban" part)

Reactive first: *"Ada, review the board"* → she walks `review`, verifies
each card's claim with tools, comments findings, closes resolved,
asks on undecidable. That alone covers the manual sweep done today
(`logs-auto-*`, `cms-auto-*`).

Later (not v1): a `ada-kanban-triage` nightly job doing the same sweep
unattended — gated until the reactive loop proves she doesn't
over-close.

## 5. Build order

1. board-api: `BOARD_API_BIND`/`BOARD_API_TOKEN` (copy report-api's gate)
2. ada-pi `tools.d/kanban.py` + manifest + instructions stanza
   (authority matrix in §3, compressed)
3. token in secrets on idc03 + tony-dell; env wiring
4. `kanban_review` live scenario — she triages one seeded card:
   list → read → verify via tool → comment → close
5. Benchmark: `tools` suite + a `kanban_move` policy case in jev

## 6. Non-goals

- No direct file/DB writes from Ada — board-api only.
- No auto-closing `priority: high` cards.
- No kanban writes from voice for Guests — board ops are Tony-tier
  (person.kk gets list/read at most).
