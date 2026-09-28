# Gemini Deep Research agent — capability assessment for Chaba/Ada

Date: 2026-09-27 · Sources: ai.google.dev deep-research & interactions docs, Google dev blog (Dec 2025), AI Studio forum

## What it is

Google's autonomous research agent, exposed to developers via the **Interactions API**
(the new GA single endpoint for models *and* agents — `generateContent` is now legacy).
Three agents:

| Agent id | Character | Est. cost/task |
|---|---|---|
| `deep-research-preview-04-2026` | fast, streamable, ~80 queries / ~250k in / ~60k out | ~$1–3 |
| `deep-research-max-preview-04-2026` | max comprehensiveness, ~160 queries / ~900k in / ~80k out | ~$3–7 |
| `deep-research-pro-preview-12-2025` | older Gemini 3.1 Pro version | — |

Powered by Gemini 3 Pro (SOTA on HLE + DeepSearchQA per Google; best-on-BrowseComp claim).
DeepSearchQA benchmark itself is open-sourced — usable for our own evals.

## API shape

- `interactions.create` with `agent=deep-research-*`, **`background=true` required**,
  `store=true` (retention: 55d paid / 1d free tier)
- Poll `interaction_id` until `completed`/`failed`, or `stream=true` for live steps
- `collaborative_planning=True` → agent returns a research *plan* first; a follow-up
  turn confirms/edits it before execution — **this maps 1:1 onto our confirm gates**
- `visualization="auto"` → generates charts/graphs inline in the report
- `tools` override: `google_search`, `external_data_mcp` (**it can call MCP servers**),
  `vertex_search`, File Upload/File Search for private docs (PDF/CSV)
- `service_tier="deferred"` → off-peak scheduling at **50% discount**
- Multiple concurrent background tasks allowed; label `is_deep_research` tracks cost

## Fit with our stack

### Ada voice tool — `ada_deep_research(topic, depth="standard"|"max")`

Natural fit for the dispatch/awaiting-user model:

1. Ada registers an MDDB job doc + starts interaction (`background`, `store`)
2. She answers immediately: "research queued, job X — I'll tell you when it lands"
3. A watcher (or poll-on-ask via `ada_deep_research_status`) detects completion
4. Report → `cms_publish_page` (via the new pending-confirm handshake for publish) +
   extract summary into memory bank + notify via `/api/notify`
5. Verification: CMS slug + interaction_id recorded on the job doc

The `collaborative_planning` option is the interesting one for voice: Ada reads the
plan aloud, Tony says "yes" or edits it, then she proceeds — exactly the
confirmation pattern we already want.

### Devin dispatch lanes

For project research (codebases, vendor comparisons): the dispatch JSONL ledger
already models long-running jobs — DR calls could be steps inside dispatched
sessions rather than separate plumbing.

### NotebookLM

DR is coming to NotebookLM natively — overlaps our NotebookLM summarization path;
watch for it replacing our digest step rather than duplicating it.

### Benchmarking

DeepSearchQA (open-source, Google) = a real benchmark corpus for complex web
research — could score Ada's `web_search`+synthesis path against DR directly.

## Constraints / watch-outs

- **Preview** — agents ids are dated previews; expect churn
- **Paid tier required** — our key is free tier now (web_search hit the 20/day
  grounding cap today); DR has no free quota worth using; also API keys must be
  restricted to generativelanguage.googleapis.com by June 2026 policy
- Runs take **minutes** — never inline on a live voice turn; always background
- Retention: free=1d (too short for our job ledger), paid=55d — we must snapshot
  the report to MDDB/CMS on completion regardless
- `store=true` means queries live on Google's side — no sensitive content in prompts

## Recommendation

Yes — adopt as Ada's `ada_deep_research` tool (standard tier default, `max` opt-in,
`deferred` when not urgent). It's the strongest missing piece between quick
`web_search` and full Devin dispatch: ~$1–3 for a cited multi-source report lands
squarely in our "control desk → job → notify → verify" architecture.

Prereqs: paid-tier API key (restricted scope), watcher for completion,
CMS publish on land. MVP ~half a day of plumbing.
