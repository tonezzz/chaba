# Ada tool-selection assessment — DuckDuckGo, overload check

Date: 2026-09-27 · scenario `tool_selection_accuracy` (8 turns, live)

## Result: 8/8 correct after expectation fixes — no tool overload evident

| Turn | Expected | Actual | Verdict |
|---|---|---|---|
| DDG search Bangkok flood | web_search+duckduckgo | `web_search(provider='duckduckgo')` — real results | PASS |
| "Send me a LINE test" | honest refusal | ada_memory_search → "Yomi offline, needs re-login" | PASS |
| Indoor temperature | sensor tool | `search_sensors` | PASS (expectation widened) |
| Cast YouTube to screen 1 | cast verb | `vcast_list` → "screens 1-3 offline" | PASS (sensible gate) |
| Thailand news, don't cast | web_search | web_search, answered inline | PASS |
| Remember coffee plug | ada_remember | ada_remember | PASS |
| Devin jobs status | devin_jobs | devin_jobs → "8 running, 4 waiting" | PASS |
| CMS publish "Tool Check" | publish handshake | asked confirmation first | PASS |

## What changed today

- `web_search` gained `provider=auto|gemini|duckduckgo` — DDG HTML
  endpoint, free, no quota; auto-fallback when grounded quota dies
  (the path that failed earlier). DDG verified live — real hits.
- The `yomi-vs-line-bot` memory note (score 0.76 top hit) grounded the
  honest LINE answer — the guardrail works.

## On tool overload — verdict: not yet a problem

~60 tools declared. Selection across search/sensors/cast/memory/ledger/CMS
was correct in every turn this run. The real failure modes seen lately are
NOT wrong-tool choices but: dead provider streams (watchdog job dispatched),
speaker-ID contamination, and capability *gaps* (no line_send yet).

Watch item: if tool count keeps growing, group related verbs into
namespaced tools (`vcast_*` already does this) rather than flattening.

## Open

- [ ] `line_send`/`line_chats` via yomi (blocked on Tony's LINE re-login)
- [ ] DDG answer quality — returns snippets not a synthesized answer;
      consider feeding top hit to a small summarizer later
