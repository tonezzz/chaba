---
category: operations
---

# Language Detection System (2026-08-03)

### Detection Algorithm

Yomi automatically detects the language of LINE conversations to provide appropriate summarization:

**Thai Character Detection:**
- Unicode range: U+0E00-U+0E7F (Thai character block)
- Calculates ratio of Thai characters to total characters
- Threshold: > 30% Thai characters = Thai language

**Language Categories:**
- **Thai**: > 30% Thai characters
- **English**: < 10% Thai characters
- **Mixed**: 10-30% Thai characters (Thai/English mix)

### Language-Specific Prompts

**Thai Prompt:**
```
สรุปการสนทนา LINE กับ ${name} เป็นประโยคเดียวสั้นๆ (ไม่เกิน 20 คำ) เน้นหัวข้อหลัก คำถาม หรือการตัดสินใจ

${content}

สรุป:
```

**English Prompt:**
```
Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Focus on the main topic, question, or decision.

${content}

Summary:
```

**Mixed Language Prompt:**
```
Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Use the same language as the messages (Thai/English mix). Focus on the main topic, question, or decision.

${content}

Summary:
```

### Implementation

**File:** `scripts/yomi/process-conversations.mjs`

**Functions:**
- `detectLanguage(text)`: Analyzes text to determine language
- `detectConversationLanguage(messages)`: Aggregates language detection across all messages
- `getLanguageSpecificPrompt(language, name, lines)`: Returns appropriate prompt based on detected language

**Detection Process:**
1. Extract text content from all messages
2. Count Thai characters (U+0E00-U+0E7F)
3. Calculate Thai character ratio
4. Classify as Thai, English, or Mixed
5. Select appropriate summarization prompt

### Benefits

- **Improved Accuracy**: Language-specific prompts produce better summaries
- **Mixed Language Support**: Handles conversations with both Thai and English
- **Cultural Context**: Thai prompts use culturally appropriate phrasing
- **User Experience**: Summaries match the language of the conversation

### Limitations

- Some encoding issues remain for certain conversations
- Detection based on character count, not semantic analysis
- May misclassify short conversations with few characters
- Mixed language conversations may have inconsistent results

