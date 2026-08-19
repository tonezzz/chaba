---
category: operations
---

# Gemini API Integration for Yomi Summarization

## What it is

Integration of Google's Gemini API as an alternative to Llama for Yomi conversation summarization, with support for Thai/English/mixed language detection and language-specific prompts.

## Context/Background

Implemented on 2026-08-06 to provide an alternative to the local Llama Phi-3 model for Yomi summarization. The integration includes language detection capabilities to handle Thai, English, and mixed-language conversations with appropriate prompts for each language type.

## Key Details

### Integration Architecture

**Environment Variables:**
- `USE_GEMINI` - Enable/disable Gemini integration (default: false, uses Llama)
- `GEMINI_API_KEY` - Google API key for Gemini access (required when USE_GEMINI=true)
- `GEMINI_MODEL` - Model selection (default: gemma-4-31b-it, configurable)

**Model Options:**
- See `docs/ssot/infrastructure/ssot.gemini-models.yml` for the canonical model registry, free-tier rate limits, and active/fallback assignments.
- Default: `gemma-4-31b-it`
- Alternative: `gemini-flash-latest`
- Other Gemini models can be selected via the `GEMINI_MODEL` environment variable.

### Language Detection

**Language Types:**
- `thai` - >60% Thai characters (U+0E00-U+0E7F)
- `english` - <5% Thai characters
- `mixed` - 5-60% Thai characters
- `unknown` - Empty or undetectable content

**Detection Functions:**
- `detectLanguage(text)` - Analyzes text content for language detection
- `detectConversationLanguage(messages)` - Detects language from multiple messages
- Optimized thresholds for better mixed-language detection

### Language-Specific Prompts

**Thai Prompts:**
- Conversation summary: Thai language instruction for concise summaries
- Daily summary: Thai JSON extraction instructions for events/actions/topics
- Batch daily: Thai multi-date JSON extraction with date keys

**English Prompts:**
- Standard English instructions for all summary types
- JSON format specifications for structured data extraction

**Mixed Language:**
- Uses Thai prompts for mixed content (Thai + English combinations)
- Ensures proper handling of bilingual conversations

### Integration Points

**Files Modified:**
- `scripts/yomi/gemini-integration.mjs` - Main Gemini integration module
- `scripts/yomi/process-conversations.mjs` - Added Gemini integration hooks
- `scripts/yomi/update-conversations.mjs` - Added Gemini integration with language detection
- `scripts/yomi/yomi-api.mjs` - API endpoint configuration for Gemini-enabled re-summarization
- `scripts/yomi/language-detection.mjs` - Language detection utilities

**API Endpoints:**
- `/api/yomi/resummarize` - Triggers re-summarization with Gemini when USE_GEMINI=1
- Automatically sets environment variables for Gemini-enabled processing

### Rate Limiting

**Current Configuration:**
- Yomi uses a conservative app throttle of 15 requests per minute
- 1-minute rate window (60,000ms)
- Model free-tier rate limits are recorded in `docs/ssot/infrastructure/ssot.gemini-models.yml`
- Configurable via RATE_LIMIT constant

## Usage

### Enable Gemini Integration

**Environment Setup:**
```bash
export USE_GEMINI=1
export GEMINI_API_KEY=your-api-key
export GEMINI_MODEL=gemma-4-31b-it  # Optional
```

**API Integration:**
```javascript
import { geminiConversationSummary, geminiDailySummary, geminiBatchDailySummary } from './gemini-integration.mjs';

// Conversation summary
const summary = await geminiConversationSummary(chatId, prompt);

// Daily summary with language detection
const language = detectLanguage(prompt);
const dailySummary = await geminiDailySummary(chatId, date, prompt, language);

// Batch daily summary
const batchSummary = await geminiBatchDailySummary(chatId, dates, prompt, language);
```

**Testing Connection:**
```javascript
import { testGeminiConnection } from './gemini-integration.mjs';

const isConnected = await testGeminiConnection();
console.log(`Gemini connection: ${isConnected}`);
```

### Language Detection Usage

```javascript
import { detectLanguage, detectConversationLanguage, getLanguageSpecificPrompt } from './language-detection.mjs';

// Detect language from text
const language = detectLanguage(messageText);
console.log(`Detected language: ${language}`);

// Detect from conversation
const convLanguage = detectConversationLanguage(messages);

// Get language-specific prompt
const prompt = getLanguageSpecificPrompt(language, name, lines);
```

## Configuration

### Gemini Integration Configuration

**File:** `scripts/yomi/gemini-integration.mjs`

**Key Settings:**
```javascript
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemma-4-31b-it';
const RATE_LIMIT = 15; // requests per minute
const RATE_WINDOW = 60000; // 1 minute in ms
```

**Model Selection:**
- Default: `gemma-4-31b-it`
- Alternative: `gemini-flash-latest`
- Custom: Set via GEMINI_MODEL environment variable
- Free-tier limits and current assignments: `docs/ssot/infrastructure/ssot.gemini-models.yml`

### Language Detection Configuration

**File:** `scripts/yomi/language-detection.mjs`

**Thresholds:**
```javascript
// Thai dominant: > 60% Thai characters
if (thaiRatio > 0.6) return 'thai';

// Mixed: 5-60% Thai characters  
if (thaiRatio > 0.05) return 'mixed';

// English: < 5% Thai characters
return 'english';
```

## Troubleshooting

**Gemini API Key Not Set:**
- Error: "GEMINI_API_KEY environment variable not set"
- Solution: Set GEMINI_API_KEY environment variable before running scripts

**Rate Limiting Issues:**
- Error: "Rate limit exceeded"
- Solution: Increase RATE_LIMIT constant or implement exponential backoff

**Language Detection Issues:**
- Problem: Incorrect language classification
- Solution: Adjust thresholds in language-detection.mjs based on content patterns

**JSON Parsing Failures:**
- Error: "no json in response"
- Solution: Check Gemini response format and adjust JSON extraction regex

**Model Not Available:**
- Error: "Model not found or access denied"
- Solution: Verify GEMINI_MODEL value and API key permissions

## Advantages Over Llama

**Language Support:**
- Native Thai language prompts
- Better mixed-language handling
- Configurable model selection

**API Reliability:**
- Cloud-based (no local GPU dependency)
- Higher rate limits on free tier
- Better error handling

**Flexibility:**
- Easy model switching via environment variables
- No GPU resource contention
- Consistent performance

## Limitations

**API Dependency:**
- Requires internet connection
- API key management required
- Potential API costs at scale

**Latency:**
- Network latency vs local Llama
- Dependent on Google API performance
- Rate limiting may affect throughput

**Context Window:**
- Different context limits than Llama
- May require prompt truncation for long conversations

## Related Documentation

- `scripts/yomi/gemini-integration.mjs` - Main integration module
- `scripts/yomi/language-detection.mjs` - Language detection utilities
- `scripts/yomi/process-conversations.mjs` - Process integration
- `scripts/yomi/yomi-api.mjs` - API endpoint configuration
- `docs/ssot/infrastructure/ssot.gemini-models.yml` - Canonical model registry and rate limits
- `docs/kb/yomi.md` - Yomi system overview
- `docs/kb/yomi-summary-corruption.md` - Summary quality and corruption handling

## Tags

- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **language**: language
- **detection**: detection
- **nlp**: nlp
- **gemini**: gemini
- **google**: google
- **2026**: 2026
