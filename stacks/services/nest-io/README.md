# nest-io — the Nest I/O fabric

Card: `nest-io-fabric`. One daemon (default host **idc03**, loopback
`127.0.0.1:8795`) that decouples the input surface from the response
surface: an utterance on the iPhone PWA can be answered on the TV, pushed
to a kanban card, or filed as a silent note — and every input gets a
recorded tier decision (hot/warm/cold/discard). Gemini Live becomes one
lane among others; each input also returns a lane recommendation.

## Pieces

- **Surface registry** — `POST /v1/surfaces {id,kind,room,caps,target}`.
  Kinds: `voice` (a mic/chat endpoint, e.g. pwa-iphone), `screen`
  (`target.vcast_screen` or `target.ha_media_player`), `card`, `note`.
  vcast displays are auto-mirrored from input-bridge `/displays` each
  30 s tick. Stale after `SURFACE_TTL_S` without a heartbeat
  (`{active:true}` re-registers).
- **Session registry** — an input binds to the open session of its
  origin surface (120 s gap → new session). A second surface in the same
  room/user joins as a **co-listener** — it receives `speak` deliveries
  but never steals the reply surface.
- **Ingestion tiers** — `POST /v1/inputs` returns `tier`+`tier_reason`
  for EVERY input; the ledger (`GET /v1/ledger`) is the triage record.
  `hot` keeps turns verbatim in-session · `warm` folds ambient content
  into an extractive session summary (flushed on close) · `cold`
  extracts fact candidates to `cold-queue.jsonl` (optional MDDB write
  with `NEST_IO_MDDB_COLD=1`; `sensitive` kind never leaves the box) ·
  `discard` drops after logging (empty/filler/dup-60s/noise).
- **Response broker** — `POST /v1/respond {session_id|surface|screen,
  kind:speak|cast|card|note|auto, text|url, ...}`. Adapters: input-bridge
  `/pub` (`speak`/`nav`/`play`/`image`/`audio` to a vcast screen),
  board-api `/comment` (card push), MDDB `ada-ha-bank-<bank>` add (note),
  HA `tts/speak` (media_player, needs `HA_URL`+`HASS_TOKEN`). Failed
  surfaces fall back through the chain target → session reply surface →
  origin; the final fallback is always a note — a reply is never
  dropped. Every response returns `reply_text` so a ws caller always has
  something to speak in-session.
- **Lane advisory** — each input returns `lane: gemini-live|local` +
  `lane_reason`: interactive/tool turns → gemini-live; ambient/batch/
  low-risk Q&A → local (the student/encoder tier owns it). The
  `NEST_IO_GEMINI=degraded|down` breaker forces everything local — the
  quota escape hatch.

## Route rule precedence

explicit phrase ("answer on the TV" / "on screen 3" / "reply here" /
"silently") > session-pinned route > room match (live screen in the
input's room) > last-active screen > origin surface.

## API

```
GET  /health                       ok, surfaces, sessions_open, offline
GET  /metrics                    counters + tier_decisions histogram
POST /v1/surfaces                register/heartbeat  DELETE /v1/surfaces/<id>
GET  /v1/surfaces                registry snapshot
POST /v1/inputs {surface,text,..}  tier+session+route+lane; dry_run:true = no writes
POST /v1/respond {..}              broker a reply to a surface
GET  /v1/sessions[/<id>]           sessions (hot turns only in <id> view)
POST /v1/sessions/<id>/close       close + flush warm summary
POST /v1/sweep                     force expiry sweep
GET  /v1/ledger?n=                 the triage/delivery audit trail
```

## Offline-safe

`NEST_IO_OFFLINE=1` records every intended delivery in the ledger without
emitting egress — dev machines and tests run with zero external calls.
Unconfigured adapters (no HA creds, unreachable bridge) degrade to
recorded/`unsupported` deliveries, not crashes.

## Verify

```bash
python3 nest-io.py --selftest     # in-process scenario: tiers, routing, broker
./verify.sh idc03                 # unit active + /health + selftest
curl -s http://127.0.0.1:8795/v1/ledger | python3 -m json.tool
```

Tests: `python3 -m unittest tests.nest_io.test_nest_io` from the repo
root.

## Integration points (ada-pi side, not this repo)

The PWA/backend adopts the fabric incrementally: fire `POST /v1/inputs`
on every utterance (text or STT result), then route the reply through
`POST /v1/respond` — or consult with `dry_run:true` first and keep the
ws reply when `reply.surface == origin`. The `speak` msg type already
ships in the vcast display (client-side speechSynthesis, RIFF/WAVE
fallback) so a TV-side answer needs no new display code.
