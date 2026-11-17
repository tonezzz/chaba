# Dispatch outcome — narrated-comms-digest (2026-11-17)

Shipped the narration layer on top of comms-digest-builder and verified it
live end-to-end: after daily-brief publishes ada-cms-pages/tony-team-digest,
each live lane now posts a persona-voiced ≤10-line narration via loopback
POST /send — [ada] -> Tony DM (:8911), [kaewta] -> KK-HA group (:8913);
chaba is skipped per spec (LINE lane blocked, Yomi token revoked). Verified
on idc03 with real posts: ada's English 9-line summary landed in Tony's DM
and kaewta's Thai 9-line summary in KK-HA. First automatic run is the next
daily-brief.timer fire (19:05 +07) after this branch merges.

## Changes

- `scripts/report-comms-narrate.py` (new) — digest in via stdin /
  --md-file / live CMS page fetch; one narration per lane via
  `scripts/ada/litellm_chat.py` on the gateway `chat` alias
  (gemini-3.5-flash -> free -> OpenRouter -> lite -> local — the spec's
  "Gemini normally, OpenRouter fallback when billing is down");
  `compose()` enforces `[<tag>]` first line, ≤10 lines, detail link;
  a generation failure still posts `(digest narration failed)` on the
  lane's own channel — never silence. `--print` renders without sending;
  env knobs for model/lanes/page-URL/send-URL/chat-id.
- `scripts/report-daily-brief.py` — `--no-narrate` flag; after the comms
  CMS publish it subprocess-calls the narrate script with the fresh
  comms_md on stdin, best-effort (warn-only, never fails the brief).
- `tests/test_comms_narrate.py` (new) — 14 tests: format contract,
  never-silence notice, lane routing (:8911/:8913), chaba skip, CLI.
- `docs/ssot/infrastructure/ssot.comms-digest.yml` —
  narration_delivery.implementation section + thinking-model gotcha.
- `docs/ssot/jobs/reports/2026-11-17-narrated-comms-digest.yml` — job doc.

## Gotcha found (worth knowing)

The gateway `chat` chain's gemini upstreams are *thinking* models —
reasoning tokens share the max_tokens budget (~10:1 observed). The first
live run with max_tokens=500 returned 1-2 truncated lines; 3000 gives
full output. This likely bites other chat-alias callers on small budgets.

## Verify

- Live check (done): `python3 scripts/report-comms-narrate.py --edition
  morning` on idc03 printed `narrate ada: sent` / `narrate kaewta: sent`;
  messages visible in Tony DM and KK-HA.
- Tests: `python3 tests/test_comms_narrate.py` — 14 pass, no network.
- Next auto run: `journalctl --user -u daily-brief.service -n 30` on
  idc03 after 19:05 — look for `narrate <lane>: sent` lines.
- Card comment posted via board-api (from idc03; the :10000 tailnet
  endpoint was unreachable from the tony-macbook runner and the :8787
  loopback write path is queuing — known card board-api-write-latency).
