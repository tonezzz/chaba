# AI news to Education procedure

Status: defined 2026-10-25

This procedure turns the morning AI/model/news scan into a compact reading
surface without polluting the Education lesson CPT with one-off headlines.

## Surfaces

1. **News CPT** remains the chronological source of raw articles and
   multi-source story digests. The existing `wp-news-fetch` -> `wp-news-digest`
   -> `wp-news-situation` schedule owns that flow.
2. **Education lesson CPT** stores durable explanations, comparisons, and
   decisions. It is updated in place by topic slug rather than forked for
   every daily article.
3. **Morning brief page** is the reading index: today's five-minute scan,
   links to the important News digests, links to changed Education lessons,
   and an explicit "no meaningful change" line when nothing qualifies.
4. **On-demand query** searches the News and Education surfaces together and
   returns the newest source-backed items first.

## Daily pipeline

1. **Collect** — fetch configured AI/model/provider/GitHub/RSS sources after
   the ordinary news fetch. Prefer official model blogs, release notes,
   model cards, provider pricing/rate-limit pages, and upstream repositories.
2. **Normalize** — capture `published_at`, `source`, `canonical_url`, title,
   model/provider, modality, license, price, context, hardware, and
   `freshness_until`. Reject items without a source URL.
3. **Deduplicate and cluster** — reuse the News CPT title embedding clusterer;
   keep one parent per story and preserve all source children.
4. **Filter for Tony** — score relevance to video generation, Gaussian/4D
   scenes, local/Colab/Nest deployment, model efficiency, Ada/Chaba
   operations, and practical cost. Exclude generic launch hype without a
   measurable change.
5. **Verify** — require one primary source for a factual claim; add a second
   independent source for a recommendation or benchmark. Mark unverified
   claims as `reported`, never as fact.
6. **Summarize** — write the fixed brief shape below. The LLM drafts prose;
   deterministic code owns links, dates, prices, model IDs, and deduplication.
7. **Decide** — classify each item as `try`, `adopt`, `watch`, `reject`, or
   `no-action`. A cost/spend, production, privacy, or destructive change is
   never auto-applied by the digest.
8. **File** — raw story and daily digest go to News; durable comparison or
   lesson goes to Education; implementation work gets a Kanban card with the
   evidence and proposed gate.
9. **Publish and verify** — update the private morning page, verify its
   consumer URL, and leave a card/CMS reference. A successful generator
   without a readable page is not a successful run.

## Fixed morning brief shape

```text
# AI + technology morning brief — YYYY-MM-DD

## 60-second scan
- 3 bullets: what changed and why it matters

## Model/provider watch
| model | provider | modality | measured/claimed efficiency |
| use | cost | hardware | decision |

## What changed for us
- video generation
- Gaussian/4D scene work
- local/Colab/Nest
- Ada/Chaba operations

## Recommended actions
- TRY: one bounded experiment with a success gate
- WATCH: interesting but missing evidence
- NO-ACTION: irrelevant, duplicate, or hype-only

## Sources and confidence
- primary links, independent links, date checked, confidence

## Education updates
- lessons updated or created, with links
```

## Model efficiency record

Every model comparison uses the same small fixture:

- one short coding/reasoning prompt;
- one structured JSON/tool-call prompt;
- one long-context summarization prompt;
- one vision prompt when supported;
- warm and cold latency;
- input/output tokens and error/429 rate;
- cost or free-quota status;
- license and data-retention notes;
- verifier result, not the model's self-report.

Report `quality per dollar`, `quality per second`, `quality per GB`, and
`failure rate` separately. Never collapse all providers into one score without
showing the workload and route.

## Education filing rule

Update an existing lesson when the topic, audience, and decision remain the
same. Create a new lesson only when the model/provider has a distinct
concept or operational procedure. Every update includes the checked date,
source links, what is measured versus claimed, and the next review date.
