# Dispatch outcome — devnest-tg-command-router (OPS-0911)

## What changed

Extended `scripts/devnest/devnest-tg-relay.py` from capture-only into a
board command router:

- **Parsing**: anchored whole-message commands only — `explain|status
  <ref|card-id>`, `APPROVE <ref>`, `REJECT <ref>`; a bare verb returns a
  usage hint; embedded commands (`please explain 0905`) are ignored.
- **Normalization**: `0905`/`905` → `OPS-0905`, `ops 0905`/`OPS-0905` →
  `OPS-0905`, other 3-letter cats (`ada-0042`) preserved, else exact card
  slug. Anything else → refusal.
- **Reads**: live card via board-api `GET /cards` (loopback :8787);
  exact ref-or-id resolution — 0 hits = "unknown ref", >1 = "ambiguous".
- **Summary** (deterministic, same-topic reply): `status` (column +
  action), `phase` (dispatch phase/column stage), `verified` (latest
  `checks` verify entry else verify-mention comm), `next` (action-aware
  note), `ask` (open ask / open requests / none).
- **Mutations** — board-api HTTP only, never YAML/shell: exactly one open
  request → `POST /respond {request_id, answer:'<verb> via devnest-tg',
  from:tony}`; open card ask → `/respond`; review-column card →
  `POST /action` (`approve`→`close`, `reject`→`hold`). >1 open request,
  nothing pending, unknown/ambiguous ref, or non-approver sender →
  refused + audited + in-topic refusal reply.
- **Auth**: `TELEGRAM_APPROVER_IDS` env (set to 8960073266 on idc03);
  default = callers labelled `*tony`.
- **Audit**: `~/.local/share/devnest/telegram/audit.jsonl` — one JSON
  line per command (result, detail, normalized ref, card, sender).
- **Routing**: replies keep `chat_id` + `message_thread_id`.
- **Robustness**: a poison update is logged and skipped — the poll offset
  still advances instead of wedging the loop.
- `systemd/devnest-tg-relay.service` description updated; SSOT trail at
  `docs/ssot/jobs/devnest/2026-10-26-tg-command-router.yml`.

Commits on branch `dispatch/20261026-171856-implement-the-next-ops-0905-sl`:
`4c62a1bcf` (feature+tests), `8ea6b866e` (SSOT doc). No push (rails).

## Verification

- `pytest tests/test_devnest_tg_relay.py` — **19/19 pass** (venv at
  /tmp/pytest-venv; host had no pytest/pip). Covers normalization,
  read-only explain (zero board POSTs), approver gating, /respond +
  /action paths, unknown-ref refusal+audit, multi-request ambiguity,
  nothing-pending refusal, and same-thread replies.
- **Deployed**: script + unit scp'd to idc03 (`~/CascadeProjects/chaba`
  exec checkout + `~/.config/systemd/user/`); env file gained
  `TELEGRAM_APPROVER_IDS` + `BOARD_API_BASE`; `daemon-reload` + restart →
  active, `/health` 200.
- **Real Telegram smoke**: harness on idc03 ran the deployed module end
  to end — `explain 0905` → real summary sent into DevNestHA; `APPROVE
  OPS-0912` → refused+audited; marker `sendMessage` returned message_id
  20. Then **organic proof**: Tony's real `explain 0905` (update
  954573590, msg 21) was processed by the running service at 17:30:47 —
  `explained` in audit.jsonl, summary delivered in-group.

## Caveats / open items

- Exec checkout has the relay file as an uncommitted modification until
  this branch merges (git-safe-pull autostash tolerates it; content then
  matches upstream).
- Card request `tg-live-smoke` remains open asking Tony to confirm an
  organic `APPROVE` round-trip (his `explain` already confirmed).
- Telegram cannot re-serve consumed updates, so offset-replay of Tony's
  earlier commands was impossible — the harness + organic message covered
  the same path instead.

## How to verify later

- `ssh idc03 'systemctl --user status devnest-tg-relay.service'`
- `ssh idc03 'tail ~/.local/share/devnest/telegram/audit.jsonl'`
- Send `explain 0905` or `APPROVE <ref>` in DevNestHA as an allowlisted
  sender; replies land in the same topic.
