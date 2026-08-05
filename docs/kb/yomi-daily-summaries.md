# Yomi Daily Summaries Quality and Coverage

## What it is

Daily summarization is a Yomi feature that extracts events, actions, and topics from LINE conversations on a per-day basis using AI (Phi-3-mini-4k-instruct-q4 model). The system groups messages by date and generates structured summaries for timeline viewing.

## Current Status (2026-08-05)

### Coverage Statistics
- **Total Daily Summaries**: 313
- **Conversations with Summaries**: 48 out of 71 (67.6% coverage)
- **Date Range**: July 12, 2026 → August 4, 2026
- **Recent Activity**: 8-24 summaries per day

### Quality Variability

**High-Quality Extraction Example** (c9cf46c3bb69167020264110420942e24 - "The Gang Promenade SsK"):
- Aug 3: 9 events, 7 actions, 3 topics (85 messages)
- Rich extraction of Thai conversation content
- Topics include: "เจอกาแฟ", "กาแฟ", "การขับขี่", "บริการ"

**Low-Quality Extraction Example** (uba31d18039c01a902eb9830a83fb6f8f):
- Most recent summaries show empty events/actions/topics arrays
- Only message_count being tracked
- Possible LLM extraction failure or low content quality

**Commercial Content Example** (u1af0dd1cbe6d9105523d59cc4571c063 - LINE Shopping bot):
- Consistent extraction: 4-8 events, 3-7 actions, 4-5 topics per day
- Commercial/promotional content being extracted
- Topics include: "ไอเทมแทนใจ", "คูปองส่วนลด", "รับพอยท์คืน"

## API Endpoints

### Get Daily Summaries
```bash
curl "http://localhost:3000/api/yomi/daily?chat=<chatId>"
```

Returns daily summaries with:
- `date`: Date of the summary (UTC)
- `events`: Array of events extracted from messages
- `actions`: Array of actions extracted from messages  
- `topics`: Array of topics extracted from messages
- `message_count`: Number of messages for that day
- `updated_at`: When the summary was last updated

### Quality Metrics
```bash
curl "http://localhost:3000/api/yomi/summary-quality"
```

Returns per-conversation quality metrics including:
- Average events/actions/topics per summary
- Empty summary percentage
- Coverage by date range
- Language distribution

### Summarization Status
```bash
curl "http://localhost:3000/api/yomi/summarization-status"
```

Returns overall system statistics:
- Total summaries generated
- Conversations with/without summaries
- Date range coverage
- Recent activity trends

## Known Issues

### Variable Extraction Quality
**Problem**: Some conversations consistently show empty events/actions/topics arrays despite having messages.

**Possible Causes**:
- LLM model not extracting meaningful content from certain message types
- Low-quality or repetitive content (e.g., automated messages)
- Language detection issues for mixed Thai/English content
- Insufficient context for extraction (too few messages per day)

**Investigation Steps**:
1. Check `/api/yomi/summary-quality` for per-conversation metrics
2. Review raw messages for affected conversations
3. Test LLM extraction manually with sample messages
4. Check Llama API logs for extraction failures

### Commercial Content Summarization
**Problem**: LINE Shopping bot and similar automated services are being summarized with commercial/promotional content.

**Impact**: Low-value summaries cluttering the system with promotional content.

**Solution**: Consider implementing exclusion filters for:
- Known automated service chat IDs
- Pattern matching for promotional content
- Low-engagement conversations (high message count, low human interaction)

### Coverage Gap
**Problem**: 23 conversations (32.4%) have no daily summaries.

**Possible Causes**:
- New conversations not yet processed
- Conversations with insufficient message volume
- Processing failures during overnight batch jobs
- Excluded conversations due to denylist

**Solution**: 
1. Check `/api/yomi/activity-status` for processing state
2. Trigger manual processing for specific conversations: `/api/yomi/process?chat=<id>&force=true`
3. Review overnight processing logs for failures

## Language Considerations

### Thai Content Handling
- Thai language detection implemented (2026-08-03)
- Thai topics and actions extracted successfully in active conversations
- Some encoding issues remain for certain conversations
- Mixed Thai/English content handled with language-aware prompts

### English Content Handling
- English content extraction works reliably
- Commercial/promotional English content (LINE Shopping) extracted consistently
- Technical English content extracted well

### Mixed Language Handling
- Language-aware summarization prompts used
- Detection based on message content analysis
- Some conversations show mixed extraction quality

## Monitoring

### Health Check Integration
Yomi daily summarization is monitored via:
- `/api/yomi/summarization-status` - Overall statistics
- `/api/yomi/summary-quality` - Per-conversation quality metrics
- `/api/yomi/activity-status` - Processing state and recent activity

### Key Metrics to Monitor
- Daily summary generation rate (target: 20-30 per day)
- Empty summary percentage (target: <20%)
- Coverage percentage (target: >80% of conversations)
- Extraction quality (average events/actions/topics per summary)

## Troubleshooting

### Empty Summaries
If daily summaries show empty events/actions/topics:
1. Check Llama API is accessible: `curl http://localhost:8001/v1/chat/completions`
2. Review conversation message content for extraction potential
3. Check `/api/yomi/summary-quality` for patterns
4. Test manual extraction: `/api/yomi/process?chat=<id>&force=true`

### Missing Summaries for Conversations
If conversations lack daily summaries:
1. Check if conversation is in denylist
2. Verify conversation has sufficient message volume
3. Trigger manual processing: `/api/yomi/process?chat=<id>&force=true`
4. Check overnight processing logs: `journalctl -u yomi-process.timer`

### Language Extraction Issues
If Thai/English content not extracted properly:
1. Check language detection in `process-conversations.mjs`
2. Review LLM prompts for language-specific handling
3. Test with known Thai/English content samples
4. Check encoding of stored messages in database

## Related Documentation

- `docs/kb/yomi.md` - Main Yomi documentation
- `scripts/yomi/process-conversations.mjs` - Daily summarization logic
- `scripts/yomi/summary-utils.mjs` - Summary generation utilities
- `docs/kb/yomi-summary-corruption.md` - Summary corruption issues

## Tags

yomi, daily-summaries, quality, coverage, thai, english, language-detection, llm-extraction