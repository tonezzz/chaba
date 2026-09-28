# Ada tools report — call structure, shared memory, and proposals

Date: 2026-09-27

## How Ada calls tools today (current structure)

```
mic → pwa_server (ws :8002) → realtime_provider (Gemini Live)
                                  │  declares ~60 tools to the model
                                  ▼
                          tool_runner.execute(name, args)
                                  │
            ┌──────────────┬──────┴─────────┬────────────────┐
        READ tools     CONFIRMED tools   CMS tools        memory banks
        (free)         DEVIN_CONFIRMED    pending→confirm  ada_memory_*
                       _CONFIRM_RE gate   handshake        per-bank write
                                                          policy
```

- **Declarations**: tool schemas live in `realtime_provider.py`
  (`DEVIN_TOOLS` set + JSON decls); execution dispatches to
  `tool_runner` methods.
- **Write gates**: two layers — (a) `confirmed=true` honored only when
  the user's own speech matches `_CONFIRM_RE` (Thai/EN affirmatives —
  fixed today, was stripping โอเค/ต่อไป); (b) per-tool pending
  handshakes (cms_publish_page registers pending → user yes → retry
  with confirmed).
- **Identity**: `SpeakerSession` identifies the voice →
  `current_speaker`/`speaker_identity` → memory routes to person-scoped
  banks (`personal-kk`, `personal-testo`, …); media-flagged profiles
  steer Ada to ignore ambient audio (added today).
- **Ledger**: `devin_jobs`/`devin_pending`/`devin_answer` read-write
  job docs in `ada-ha-bank-devin-handoff` — the dispatch ledger.

## Three-way shared memory (Tony ↔ Ada ↔ Devin)

| Bank | Tony writes | Ada writes | Devin writes |
|---|---|---|---|
| `devin-handoff` | specs, decisions | distilled specs, job status, answers | job docs, outcomes, needs-input |
| `general`/`personal-*` | direct asks | extracted facts, prefs | (read) |
| `cms` (read-only) | reports via Devin | published pages | reports via /v1/add |
| `devin` (session history) | — | read | sync-devin-summaries.py |

Efficient pattern: **handoff is the queue, cms is the record, general
is the context**. Specs enter `devin-handoff` (Ada `ada_remember`),
dispatched sessions read them via mddb MCP, results land back as job
docs, reports graduate to `cms`. Keep entries atomic — one subject per
key, `status=superseded` on replace.

## Proposal: per-report input box → shared memory

Goal: Tony types a response under any CMS page; it lands in the shared
bank so Ada and Devin can act.

1. `POST /api/respond` on ada backend: `{slug, text, ts}` → writes
   `response/<slug>-<ts>` into `devin-handoff` (kind=response,
   status=pending) + optional `job/<id>` link when the page came from a
   dispatched job.
2. CMS renderer adds a `<textarea>` + button per page footer; on
   submit → POST → flash "saved".
3. `devin_pending`/`devin_jobs` surface responses so this control desk
   and Ada see them; `devin_answer` can deliver a response straight
   into a resumable session.

Effort: small — one endpoint + ~30 lines in `pwa/cms/index.html`.

## Proposal: software-dev skills for Ada, gated to Tony

Ada can already *dispatch* dev work; "dev skill" means she uses the
devin-* toolset + github/docs MCP plus focused prompt cards. Gate by
**caller identity**, which already exists:

- `provider.current_speaker_ha_person` / `session_caller_name` — allow
  `devin_dispatch`, `devin_followup`, `devin_answer`, `ada_deep_research`
  only when speaker is `tony` (or the session's issued key is Tony's).
- Others (kk, testo, guests): dispatch tools hidden/refused — same
  mechanism as `allowed_tools` on person-scoped banks.
- Add `ADA_DEV_TOOLS_ENABLED_FOR=[tony]` env; fail-closed default.

## Weaviate continuation — see `ada-recall-architecture` page
(updated: staged plan, decision gate, and metrics)

## Connect UX — system boot voice (added 2026-09-27)

Mic click → flat machine voice narrates each stage until Ada takes over:

| Stage | Line |
|---|---|
| click | "Initializing voice link." |
| mic ready | "Microphone ready. Establishing channel." |
| ws open | "Channel open. Handing over to Ada." |
| `ready` | "Ada online. Listening." |
| failure | "Link failed. <reason>" |

Implementation: browser `speechSynthesis` — pitch 0.85, rate 1.15,
en-US voice — crisp and non-emotional by construction. The mic click
is the user gesture that unlocks it on iOS/Safari. `systemHush()`
cancels pending announcements on `response_started` (Ada speaks),
ws close, and disconnect. Files: `pwa/app.js`.

Next-step options if you want it more sci-fi: pre-baked WAV clips
(synthesized once, zero TTS variance), a soft hum while connecting,
or a distinct "Ada online" chime before the voice.

## CMS ops assessment — 2026-09-27 (`cms_ops_assessment`, 9 turns, all PASS)

Full lifecycle works end to end: list → read → publish (handshake) →
verify → update → delete → honest not-found. Mechanical competence is
fine — the pain Tony reports is *friction*, not failure:

- **Stale pending handshakes bleed across sessions.** `_cms_pending`
  lives on the shared `tool_runner` — a confirm request registered in
  session A that never resolved greets session B with "should I delete
  that page?" mid-conversation. Fix: namespace pending by session or
  expire them.
- **Confirmation phrasing is stricter than natural speech.** Turn 6
  denied "Confirm the update." — Ada demanded an explicit "ใช่". The
  `_CONFIRM_RE` + pending-handshake double gate means any soft
  affirmative outside the regex loops her back to asking. Widened
  earlier (`086de1b`) but the edge persists for phrasing like
  "confirm the update" / "go ahead with it".
- Both are UX-level, not correctness — every denied call refused safely
  rather than publishing unwanted content.
