# Ada session health — quiet/off-focus, shared memory, CMS publish bug

Date: 2026-09-27 · evidence: idc01 journals + transcripts + live scenarios

## 1. "Ada goes quiet / speaks off-focus / can't resume"

**Reproduced live**: `shared_memory_audit` scenario — first user turn got
**0 tool calls and an empty response**. Ada said nothing after connect.

Likely mechanisms (evidence-ranked):

1. **Session churn** — 7+ websocket sessions opened/closed on the morning
   of 2026-09-27 (scenario runs + real reconnects + service restarts).
   Each new session replays "welcome back" + injects the prior session's
   focus, so mid-conversation context resets and the CURRENT topic is lost
   while an OLD one resurfaces. That matches "speaks out of other focus
   randomly".
2. **First-turn-after-connect fragility** — the empty turn-1 response
   suggests the greeting injection races the user's first message; the
   turn may get consumed without a response.
3. **Sticky speaker identity** — transcripts show Ada reporting "Tony,
   75%" identically on every voice test including a YouTube voice. The
   reported confidence appears session-sticky rather than per-utterance.

### Root cause — ambient audio becomes user turns (confirmed)

Transcript `2026-09-27-67d22d0e08` shows TV/YouTube audio logged as
`## User` turns verbatim: "Goose meat represented less than 2.1 million
tons…", "Industrial civilization cannot survive…", "nation, China…",
"Inside the fifth dynasty tomb at Saqqara…". Ada then answers the
*video's* content — English input biases her reply to English → this is
the "suddenly switches to English + speaks out of another focus"
symptom. The mic path has no speaker gate: any loud-enough audio is a
conversation turn.

**Consequence — profile pollution**: `NewSpeaker` and `EnglishSpeaker`
are TV/YouTube voices enrolled through the same leak. The enroll guard
refusing Murph→"Kung" was correct defense — a playing video's voice
matched its own auto-created profile.

**Fixes to implement**:
- Tag each user turn with speaker attribution; suppress or
  context-mark turns not attributable to an enrolled household speaker
- Gate `ada_enroll_speaker` on an enrolled-speaker utterance — never
  enroll audio that speaker-ID can't attribute to a person in the room
- Delete junk profiles: `NewSpeaker`, `EnglishSpeaker`, `Timmy`

## 2. Shared memory (Devin ↔ Ada ↔ Tony)

**It exists** — `ada-ha-bank-devin-handoff` (job ledger + handoff specs)
and `ada-ha-bank-devin-tony` (session outcomes). Both are writable
memory-bank entries, the watch writes job docs, Ada reads them via
`devin_jobs`/`devin_pending`/`ada_memory_search`, Tony reads them via the
Report tab and CMS.

**Gap found**: Ada described it as "file based" — her instructions don't
describe the shared bank accurately. New tool `devin_jobs` (added today)
gives her the ledger view. Scenario `shared_memory_audit` now audits this
— turn 2 passed (3 calls), turn 1 caught the quiet bug.

## 3. The CMS problem Ada mentioned — ROOT CAUSE FOUND

Symptom she reported (03:17): "tried to publish, system says page not
found."

Actual chain (journal `session=e2d5ab19c8` + `3d8f84fabf`):

```
cms_publish_page args={'confirmed': True, ...}
→ "self-asserted confirmed=true without user affirmation — stripping"
→ error: requires confirmation
```

The user-affirmation gate (`_CONFIRM_RE`) honors `confirmed=true` only
when Tony's own speech matched its regex — which lacked the Thai/soft
affirmatives he actually uses: โอเค, ต่อไป, ไปเลย, ส่งเลย, mhm, uh huh,
sounds good. So Tony said yes in Thai, the gate stripped `confirmed`,
publish denied, and Ada misread the failure as "page not found".

**Fixed** (086de1b): regex extended — `โอเค|ออเค|เออ|อือ|ต่อไป|จัดไป|
เอาสิ|ไปเลย|ทำไป|เผยแพร่เลย|ส่งเลย|mhm|uh huh|sounds good`.

## 4. Also surfaced — enroll refusal was correct

The Murph→"Kung" enroll refusal at 08:38 was the contamination guard
working: the voice matched stale profile `NewSpeaker` (a duplicate of
Tony, cosine 0.427) at 63%. Cleanup of `NewSpeaker` + `Timmy` (dup of
กุ้ง) still pending Tony's approval.

## Action queue

| # | Item | Status |
|---|---|---|
| 1 | `_CONFIRM_RE` Thai affirmatives | deployed |
| 2 | `devin_jobs` ledger tool | deployed |
| 3 | Quiet/first-turn race — needs provider-level repro (turn consumed without response) | open |
| 4 | Speaker profile dedup (NewSpeaker, Timmy) | awaiting Tony approval |
| 5 | Instruction nudge: describe shared bank accurately | open |
| 6 | Shared-memory audit scenario | live, catching bugs |

### Confirmed Ada-side language flips (added 12:35)

Beyond ambient-media ingestion, real output-language flips confirmed:

- **05:58:31** (session 681e1d6817) — Thai question answered in English
  ("In memory, Devin does have a proper failure path…"); user had to say
  "ภาษาไทยเด้อ". Cause class: model mirrors whatever English context
  (tool/memory hits) dominated the turn.
- **"ฮ่องกงอีกแล้ว"** — twice across sessions 40620e99d7 / d55e2767cf,
  the reconnect greeting came out sounding Chinese. Cause class: Gemini
  Live picks a language for the greeting turn; system instructions are
  English and the voice sits near a CJK register when primed that way.

Fix deployed (`39309f8`): LANGUAGE FIDELITY instruction — reply in the
user's most-recent-turn language; reconnect greetings use the
conversation's dominant language; English tool/system context never
changes spoken language.

Still open: speaker-ID kept addressing Tony as คุณกุ้ง in session
d55e2767cf — the Timmy/NewSpeaker contamination needs profile cleanup.
