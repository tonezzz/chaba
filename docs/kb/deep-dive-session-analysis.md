# Deep-dive session flow — analysis, improvements, benchmark

Date: 2026-09-27 · scenario: `tests/scenarios-live/deep_dive_flood_report.yaml`

## What the flow should be

Discuss → drill → analyze → improve → benchmark. Tony picks an artifact
(a flood report page), talks it over with Ada, she critiques, improves it,
and re-verifies — all inside one conversation.

## Live run findings (2026-09-27)

| Turn | Expectation | Ada did | Verdict |
|---|---|---|---|
| "pull up the flood report" | `cms_get_page`/list/search | fetched + summarized correctly | ✓ |
| "analyze it like an editor" | (was: must call tool) | answered inline — no call, and the critique was genuinely good (imprecision, staleness) | ✓ behavior — scenario was wrong |
| "improve it — restructure + save + verify" | `cms_publish_page` | reached for `web_search` first, hit the 20/day grounding quota, then asked permission instead of publishing | partial |
| "yes, go ahead" | publish + verify | drafted new structure; publish handshake fired ("jumped the gun" → pending) | handshake working |

### Issues surfaced

1. **Quota trap**: when asked to *improve* a page she defaulted to
   fetching fresher data (`web_search`) instead of restructuring what
   exists — and hit the free-tier cap. Improve-with-what-we-have should
   be the default; research is a separate ask.
2. **Editorial turns shouldn't tool-call** — once the page is fetched,
   analysis is in-context. Fixed the scenario to assert `no_calls_except`
   (the L0-index design already predicted this).
3. **No benchmark turn yet** — the scenario needs a 5th step: "how do we
   measure if the report got better" → she should propose metrics
   (freshness, coverage, cite count, structure completeness) and ideally
   score the page.

## Improvements to land

- Ada instruction: "improve a page = restructure existing content; only
  reach for web_search when the user asks for new information"
- `cms_verify_page` block-report already returns structure — extend the
  improvement turn to compare before/after (report diff)
- Add a `benchmark` turn: she rates the updated page on a rubric
  (freshness/specificity/sources/structure 0-2 each) — gives a numeric
  before/after we can track in the ledger

## Benchmark proposal (report quality score)

Per report/page, score 0–8: specificity (proper names/dates), freshness
(timestamps within window), sources cited, structure completeness. Store
score in the page meta on each update — `cms_verify_page` could emit it.
Then "dig deep → improve" sessions become measurable: score should rise
each pass, and the trend is reviewable in the CMS report list.
