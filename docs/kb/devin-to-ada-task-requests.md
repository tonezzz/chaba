# Devin → Ada task requests — proven channel (tested 2026-09-22)

How to hand Ada a task that she will actually find and execute, verified
end-to-end via a headless WebSocket session against `ada-ha-tony`.

## The pattern that works

1. **Write the request as a `status: draft` doc in `ada-ha-bank-general`**
   (scope = the target instance, `valid_from` = today). Drafts surface in
   `ada_memory_search` **only** for draft-visible banks — default
   `personal,general` (env `ADA_DRAFT_VISIBLE_BANKS`) — and only for the
   same instance and recent docs. This is the intended "pending review"
   surface.
   - Key convention that worked: `extract-YYYY-MM-DD-devinreq-0`
   - Meta: `kind: note`, `status: draft`, `source: devin`,
     `written_by: devin`, `scope: tony`, `valid_from: today`,
     `subject: "pending task request: <what>"`
   - Content: imperative contract — "EXECUTE these steps, don't answer
     questions about it", numbered steps using ONLY tools she actually
     has, plus a "say the error out loud, don't invent tool names" rule.

2. **Trigger phrase** (what Tony or a test says to Ada):
   > "Search your general memory bank — include inactive — for a pending
   > task request about X. Execute the steps in it."

   `include_inactive: true` is what makes drafts visible to her search.

3. **Confirmation gate**: writes to shared banks (`general`) are gated —
   `ada_remember` returns "requires confirmation … confirmed=true" until
   the user says yes. Tony just answers "yes / go ahead" when she asks.

## What does NOT work

- **Request docs in `ada-ha-bank-devin-tony`** — that bank holds ~950 raw
  Devin session transcripts; semantic search buries task docs under them
  (top hits were transcript chunks at 0.77-0.81 vs the request at ~0.73).
- **Searching by literal key** — `ada_memory_search` is semantic; a key
  like `request-2026-09-22-distill-rika-rk600` embeds poorly. Always use
  natural-language queries.
- **`ada_session_recall`** — routes to NotebookLM deep recall, answers
  async in the background; the answer often never lands in-session. Not
  suitable for task execution.
- **Vague task docs** — attempt 1 read like context, so Ada answered
  "what is the weather station" and published a mini-site page instead of
  executing. Lead with "TASK REQUEST — act on this".
- **Asking for tool capabilities she lacks** — `ada_remember` writes
  `status: active` only and generates its own keys; there is no
  draft-writing or arbitrary-meta-update tool. Design steps around:
  `ada_memory_search`, `ada_remember`, `ada_forget`, `ada_outcome`,
  `ada_decision_check`, `ada_session_recall`, `ada_resolve_action`,
  `get_*`, `set_facial_expression`, `devin_dispatch`, `devin_status`,
  `devin_followup` (devin tools live since 2026-09-23 — dispatch/followup
  need `confirmed=true`).

## Headless test harness

`/tmp/ada-test*.py` on idc01 (transient — recreate from this recipe):
`POST /api/auth/session {api_key}` (key in
`~/.config/secrets/ada-ha-tony.env` on idc01) → cookie →
`ws://127.0.0.1:8002/ws` with Cookie header → wait `{"type":"ready"}` →
send `{"type":"text","text":"…"}` → read `tool_call` / `tool_result` /
`assistant_transcript_delta` / `response_completed`. To pass the confirm
gate send a second text turn "Yes — confirmed, go ahead."

Session transcripts distill into `ada-ha-recall-summary-<instance>` as
`session-<date>-<session_id>`; conversation extracts land as
`extract-<date>-<session_id>-<n>` drafts in the banks.

## Progressive-deepening scenario (tested 2026-09-23)

Quick memory answer → persist → deepen only on explicit confirmation →
update the summary. Verified end-to-end; the summary doc
(`general/weather-station`) gained a provenance/coverage line naming its
sources.

Refined convention — put this in the request/summary doc itself:

```
Coverage: L1 — distilled from general-bank curated memories (date).
Not yet searched: devin session transcripts, live API/device.
To deepen: ask "go deeper" — fold new facts in, update this line.
```

Levels: L0 quick answer (memory only) · L1 confirmed deep-dive (other
banks + KB docs) · L2 live sources (cloud API, device). Each deepen
updates the SAME doc via `ada_remember` (verb `correct`) + coverage line.

### Pitfalls found in this scenario

- **Wrong-bank first guess** — on a bare topic query she picked
  `tony-projects` and found nothing; `bank='all'` (fan-out) exists and
  works — tell her "search all banks" or name the bank explicitly.
- **Fact contamination** — an unrelated personal fact ("no longer
  general manager") leaked into the topic summary during the deepen
  fold. Add a rule: "fold in only facts about THIS topic".
- **Stale facts propagate** — the deepened summary repeated the outdated
  "rain never reported" claim because the request text predated the
  overnight rain verification. Deepen prompts should say "prefer newer
  sources over older memory text".
- **Turn-1 noise** — `ada_resolve_action` dismissals + expression calls
  can consume a whole turn; keep the first ask short and don't stack
  multiple asks in one turn.

## Watch for

- Ollama embedding outages (`127.0.0.1:11435` on idc01) — new docs are
  invisible to semantic search while it's down; doc writes still succeed.
- Occasional model drift: hallucinated tool names (`ada_ nhớ`) and bank
  names (`toni-projects`) — the request doc should list valid bank names.
