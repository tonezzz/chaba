# DevNest performance and parallel research procedure

Status: defined 2026-10-26

## Performance model

DevNest is prefill-heavy: the same system prompt, repository map, tool
definitions, and prior turns are repeatedly sent. The primary optimization is
therefore **prefix/cache reuse**, not merely a faster tokenizer.

### Cache layers

1. **Provider prompt cache** — keep a stable system/tool prefix and append the
   changing task at the end. Measure `cached_input_tokens` and cache-hit ratio
   per provider. Never assume an OpenAI-compatible proxy preserves cache keys.
2. **LiteLLM/provider cache** — use only where the provider explicitly reports
   cache reads/writes. Record cache-aware cost, not headline input price.
3. **Local file caches** — cache repository file digests, AST/index results,
   embeddings, model weights, prompt embeds, and fetched research pages under
   content-addressed keys. Never cache secrets or mutable live cards.
4. **Session cache** — keep a compact task state and artifact manifest instead
   of replaying raw logs. Summarize only at stable boundaries; preserve the
   source paths and hashes.

### Tokenization

Pre-tokenizing the whole repository is usually the wrong optimization:
tokenizers are fast, token IDs depend on the selected model, and the useful
unit is the stable prefix plus a small retrieval set. Pre-tokenization is
worthwhile for repeated fixed corpora (bench fixtures, news batches, prompt
embeds, and document shards), but it must be keyed by:

```text
model/tokenizer revision + normalization version + content sha256
```

Do not share token IDs between models. Store source text and token metadata
next to the cache so a tokenizer upgrade invalidates it safely.

### Safe high-value optimizations

- Keep system instructions, tool schemas, and repository conventions byte-stable.
- Send a compact manifest and relevant file windows, not the entire checkout.
- Use deterministic codemods and pattern retrieval before an LLM.
- Batch independent research fetches and embedding calls; do not batch
  unrelated agent turns that need conversational state.
- Cache HTTP research responses with URL + ETag/Last-Modified + checked date.
- Persist HF/model weights and T5/LTX prompt embeds in Drive/Nest caches.
- Record cold/warm latency, input/output/cache tokens, error rate, and verifier
  pass rate for every lane.

## Parallel research standard

Every research request is split into independent lanes with a shared contract:

```yaml
research_id: YYYYMMDD-topic
question: ...
lanes:
  - internal-state
  - primary-web
  - github-precedent
  - benchmark/pricing
  - implementation-fit
artifact:
  - sources.json
  - findings.md
  - recommendation.md
  - education.html
  - evidence.json
```

Each lane returns source URL, checked timestamp, claim, evidence excerpt,
confidence, and relevance. The reducer deduplicates URLs, separates
measured/claimed facts, resolves conflicts by primary source, and produces:

1. a short decision table;
2. an implementation recommendation;
3. explicit rejects and unknowns;
4. an Education lesson update or new lesson;
5. a Kanban comment/card when work remains.

Parallelism is allowed for read-only fetch/search/bench lanes. Writes are
serialized through board-api, lesson-add, and artifact publication. A lane
cannot mark the research complete until its artifact exists and the reducer
has re-fetched it.

## News integration

The existing News CPT remains the raw chronological store. The morning AI
brief should run after `wp-news-fetch`, reuse `wp-news-digest` clustering, and
publish a private brief with: 60-second scan, model/provider table,
Chaba-relevance, TRY/WATCH/NO-ACTION, primary sources, confidence, and lesson
updates. Telegram/tony-ha delivery is a notification projection of that brief,
not a second database.

Use `board_notify`/the existing `ada-tg-relay` for delivery. Resolve the
destination chat ID from the configured `BOARD_NOTIFY_TG_CHAT_ID` or the
tony-ha/ada-ha group registry; never guess a group or put a bot token in a
research artifact. Before enabling, send a dry-run message, verify the
consumer group receives it, then enable the timer with a kill switch.
