# nest-io-fabric — the I/O fabric daemon (v1)

**Result: done (code + spec + tests; not deployed per dispatch rails).**

## What landed

- `stacks/services/nest-io/` — `nest-io.py` (self-contained, stdlib-only,
  same shape as nest-mgr), `nest-io.service` (user unit, `--serve` on
  `127.0.0.1:8795`), `install.sh` (default host idc03), `verify.sh`,
  `README.md`.
- `tests/nest_io/test_nest_io.py` — 29 unittest cases, all green.
- `docs/ssot/infrastructure/ssot.nest-io-fabric.yml` — the fabric
  contract (surfaces, sessions, tiers, broker, routing, lanes, ops).
- `docs/ssot/jobs/nest/2026-10-10-nest-io-fabric.yml` — job record with
  decisions, verification, caveats, next steps.
- `ssot.nest-training.yml` related list links the new SSOT.

## The four fabric pieces

1. **Session/surface registry** — `POST /v1/surfaces` registers
   voice/screen/card/note surfaces; input-bridge `/displays` mirrors
   every paired vcast screen automatically each 30s tick. Inputs bind to
   the origin surface's open session (120s gap); a second surface with
   the same user/room joins `co_listeners` — receives speak fan-out,
   never steals `reply_surface`.
2. **Ingestion tiers** — every `POST /v1/inputs` returns
   `tier`+`tier_reason` and lands in `GET /v1/ledger`. Order:
   discard (noise/empty/dup-60s/filler) → cold (explicit "remember" or
   unaddressed declarative fact → `cold-queue.jsonl`, kind=sensitive
   never egresses, MDDB write opt-in) → hot (addressed/question/command
   or short continuation) → warm (ambient content → extractive session
   summary flushed on close).
3. **Response broker** — `POST /v1/respond` picks the surface by
   precedence explicit phrase ("answer on the TV"/"on screen 3"/"reply
   here"/"silently") > session pin > room screen > last-active screen >
   origin. Adapters: input-bridge `speak`/cast, board-api comment, MDDB
   bank note, HA `tts/speak`. Fallback chain ends at a note — a reply is
   never dropped; `reply_text` always returns for the ws caller.
4. **Lane advisory** — every input returns `lane: gemini-live|local` +
   reason; `NEST_IO_GEMINI=degraded|down` forces all-local (the quota
   breaker). Caller `lane` pin wins.

## Verified

- `python3 -m unittest tests.nest_io.test_nest_io` — 29 green
  (tiers, routing precedence, co-listen no-steal, broker adapters +
  fallback, lanes, persistence, sweep).
- `nest-io.py --selftest` — 8-case in-process scenario, hard-offline.
- YAML safe_load clean on both new docs; `py_compile` clean.

## Caveats

- One early selftest ran before the offline guard: it emitted a `speak`
  to input-bridge room vcast-2 (harmless broadcast) and one MDDB doc
  into `ada-ha-bank-general` (`note-*`, "quiet note"); a board comment
  attempt 400'd. `--selftest` now forces offline — zero egress always.
- Not deployed. `./install.sh idc03 && ./verify.sh idc03` when approved.
- Card `verify` (PWA speak → TV answer + co-listen) needs the ada-pi
  side to adopt `/v1/inputs` + `/v1/respond` — separate repo, separate
  card; the fabric is curl-testable standalone meanwhile.

## Board

Progress + result comments posted to `nest-io-fabric` via board-api.
