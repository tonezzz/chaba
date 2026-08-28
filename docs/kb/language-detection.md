---
category: operations
---

# Language Detection for Yomi Summarization

## What it is

Language detection utilities for identifying Thai, English, and mixed-language content in Yomi LINE conversations. Enables language-specific prompt generation for improved summarization accuracy across multilingual conversations.

## Context/Background

Implemented on 2026-08-06 to address language mismatch issues in Yomi summarization where English prompts were used for Thai conversations, resulting in poor summary quality. The system now automatically detects conversation language and selects appropriate prompts.

## Key Details

### Language Detection Algorithm

**Thai Character Detection:**
- Thai Unicode range: U+0E00-U+0E7F
- Uses regex pattern: `/[\u0E00-\u0E7F]/g`
- Counts Thai characters vs total characters

**Detection Thresholds:**
```javascript
const thaiRatio = thaiChars.length / totalChars;

// Thai dominant: > 60% Thai characters
if (thaiRatio > 0.6) return 'thai';

// Mixed: 5-60% Thai characters
if (thaiRatio > 0.05) return 'mixed';

// English: < 5% Thai characters
return 'english';
```

**Threshold Rationale:**
- **60% for Thai**: Ensures content is truly Thai-dominant
- **5% for mixed**: Catches any meaningful Thai content
- **95% for English**: Allows minimal Thai characters (names, loanwords)

### Detection Functions

**Text-Level Detection:**
```javascript
import { detectLanguage } from './language-detection.mjs';

const language = detectLanguage(messageText);
// Returns: 'thai', 'english', 'mixed', or 'unknown'
```

**Conversation-Level Detection:**
```javascript
import { detectConversationLanguage } from './language-detection.mjs';

const language = detectConversationLanguage(messages);
// Analyzes all messages in conversation
// Returns: 'thai', 'english', 'mixed', or 'unknown'
```

**Message Filtering:**
```javascript
// Filters out null/empty/invalid text
const textContent = messages
  .map(m => {
    const text = m.text || '';
    if (text === 'null' || text === 'undefined' || !text.trim()) return '';
    return text;
  })
  .filter(Boolean)
  .join(' ');
```

### Language-Specific Prompts

**Thai Prompts:**
```javascript
// Conversation summary
"สรุปการสนทนา LINE กับ ${name} เป็นประโยคเดียวสั้นๆ (ไม่เกิน 20 คำ) เน้นหัวข้อหลัก คำถาม หรือการตัดสินใจ"

// Daily summary
"สกัดข้อมูลจากข้อความ LINE วันที่ ${date} ในการสนทนากับ ${name}:
- เหตุการณ์ (สิ่งที่เกิดขึ้น)
- การกระทำ (สิ่งที่คนทำหรือวางแผนจะทำ)
- หัวข้อ (เรื่องหลักที่พูดคุย)
รูปแบบ JSON: { events: [...], actions: [...], topics: [...] }"
```

**English Prompts:**
```javascript
// Conversation summary
"Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Focus on the main topic, question, or decision."

// Daily summary
"Extract from these LINE messages for ${date} in conversation with ${name}:
- Events (things that happened)
- Actions (things people did or plan to do)
- Topics (main subjects discussed)
Format as JSON: { events: [...], actions: [...], topics: [...] }"
```

**Mixed Language Prompts:**
```javascript
// Uses Thai prompts for mixed content
// Ensures proper handling of Thai/English combinations
// Same structure as Thai prompts but for mixed-language content
```

### Integration Points

**Gemini Integration:**
```javascript
import { geminiDailySummary, geminiBatchDailySummary } from './gemini-integration.mjs';
import { detectLanguage } from './language-detection.mjs';

const language = detectLanguage(prompt);
const response = await geminiDailySummary(chatId, date, prompt, language);
```

**Prompt Generation:**
```javascript
import { getLanguageSpecificPrompt, getLanguageSpecificDailyPrompt, getLanguageSpecificBatchDailyPrompt } from './language-detection.mjs';

const prompt = getLanguageSpecificPrompt(language, name, lines);
const dailyPrompt = getLanguageSpecificDailyPrompt(language, date, name, lines);
const batchPrompt = getLanguageSpecificBatchDailyPrompt(language, name, dates, dateSections);
```

## Usage

### Basic Language Detection

```javascript
import { detectLanguage, detectConversationLanguage } from './language-detection.mjs';

// Detect from single text
const text = "สวัสดีครับ ผมเช้าฟ้าง";
const language = detectLanguage(text);
console.log(language); // 'thai'

// Detect from conversation
const messages = [
  { text: "Hello world" },
  { text: "สวัสดีครับ" },
  { text: "How are you?" }
];
const convLanguage = detectConversationLanguage(messages);
console.log(convLanguage); // 'mixed'
```

### Language-Specific Prompt Generation

```javascript
import { getLanguageSpecificPrompt, getLanguageSpecificDailyPrompt } from './language-detection.mjs';

const language = detectLanguage(conversationText);
const prompt = getLanguageSpecificPrompt(language, name, lines);
const dailyPrompt = getLanguageSpecificDailyPrompt(language, date, name, lines);
```

### Integration with Summarization

```javascript
// In process-conversations.mjs or update-conversations.mjs
import { detectLanguage } from './language-detection.mjs';
import { geminiDailySummary } from './gemini-integration.mjs';

const language = detectLanguage(prompt);
const response = await geminiDailySummary(chatId, date, prompt, language);
```

## Configuration

### Threshold Configuration

**File:** `scripts/yomi/language-detection.mjs`

**Adjustable Thresholds:**
```javascript
// Thai dominant threshold
const THAI_DOMINANT_THRESHOLD = 0.6; // 60%

// Mixed language threshold  
const MIXED_LANGUAGE_THRESHOLD = 0.05; // 5%

// English threshold (implicit)
// Anything below 5% Thai characters
```

**Customization Guidelines:**
- Increase THAI_DOMINANT_THRESHOLD for stricter Thai detection
- Decrease MIXED_LANGUAGE_THRESHOLD for more sensitive mixed detection
- Adjust based on actual conversation patterns

## Validation

### Detection Accuracy Testing

```javascript
// Test cases
console.assert(detectLanguage("สวัสดีครับ") === 'thai');
console.assert(detectLanguage("Hello world") === 'english');
console.assert(detectLanguage("Hello สวัสดี") === 'mixed');
console.assert(detectLanguage("") === 'unknown');
```

### Conversation-Level Testing

```javascript
// Test conversation detection
const thaiConversation = [
  { text: "สวัสดีครับ" },
  { text: "เช้าฟ้างครับ" }
];
console.assert(detectConversationLanguage(thaiConversation) === 'thai');

const mixedConversation = [
  { text: "Hello" },
  { text: "สวัสดีครับ" }
];
console.assert(detectConversationLanguage(mixedConversation) === 'mixed');
```

## Troubleshooting

**Incorrect Language Classification:**
- **Problem**: English content classified as mixed
- **Solution**: Increase MIXED_LANGUAGE_THRESHOLD from 0.05 to 0.10
- **Problem**: Thai content classified as mixed
- **Solution**: Increase THAI_DOMINANT_THRESHOLD from 0.6 to 0.7

**Empty Content Detection:**
- **Problem**: Returns 'unknown' for valid content
- **Solution**: Check text normalization and filtering logic
- **Problem**: Returns 'english' for Thai content
- **Solution**: Verify Thai character regex pattern is correct

**Prompt Selection Issues:**
- **Problem**: Wrong language prompt selected
- **Solution**: Verify language detection returns expected value
- **Problem**: Mixed content gets English prompt
- **Solution**: Ensure mixed language uses Thai prompts (current behavior)

## Performance Considerations

**Detection Speed:**
- Single text detection: <1ms
- Conversation detection: O(n) where n = message count
- Minimal performance impact on summarization pipeline

**Memory Usage:**
- No significant memory overhead
- Processes text in streaming fashion
- No large intermediate data structures

## Best Practices

**Always Detect Language:**
- Detect language before prompt generation
- Use conversation-level detection for accuracy
- Handle 'unknown' language gracefully (default to English)

**Test with Real Data:**
- Validate thresholds with actual conversation data
- Monitor classification accuracy over time
- Adjust thresholds based on real-world patterns

**Document Language Patterns:**
- Track common language patterns in your conversations
- Note any special cases (code, technical terms, etc.)
- Consider custom handling for edge cases

**Fallback Strategy:**
- Default to English prompts for 'unknown' language
- Provide manual language override option if needed
- Log classification decisions for debugging

## Related Documentation

- `scripts/yomi/language-detection.mjs` - Language detection implementation
- `scripts/yomi/gemini-integration.mjs` - Gemini integration with language support
- `scripts/yomi/process-conversations.mjs` - Process integration
- `scripts/yomi/update-conversations.mjs` - Update integration with language detection
- `docs/kb/gemini-integration.md` - Gemini API integration details
- `docs/kb/yomi.md` - Yomi system overview

## Tags

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
- **ai**: ai
- **google**: google
- **2026**: 2026
