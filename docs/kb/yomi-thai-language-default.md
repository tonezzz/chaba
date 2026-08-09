# Yomi Thai Language Default Change

## What it is

A system-wide change to default Yomi language detection and processing to Thai instead of English for LINE conversations. This change affects media analysis, daily summaries, and conversation summarization across all Yomi processing functions.

## Context

**Date Implemented**: 2026-08-08

**Rationale**: Most LINE conversations in the system are in Thai language. The previous default to English was causing incorrect language detection and suboptimal AI processing for Thai content. By defaulting to Thai, the system now provides better language-specific prompts and processing for the majority of conversations.

**Scope**: This change affects all Yomi language detection functions and prompt generation across the codebase.

## Technical Details

### Language Detection Thresholds (Unchanged)

The Thai character ratio thresholds remain the same:
- **>60% Thai characters**: Detected as 'thai'
- **5-60% Thai characters**: Detected as 'mixed'
- **<5% Thai characters**: Previously defaulted to 'english', now defaults to 'thai'

### Default Language Change

**Before**: Default language for unknown/empty content was 'english'
**After**: Default language for unknown/empty content is 'thai'

### Files Modified

1. **analyze-media.mjs**
   - Updated `detectConversationLanguage()` to return 'thai' instead of 'english' for empty text
   - Updated prompt generation to use Thai prompts for 'unknown' language cases

2. **language-detection.mjs**
   - Updated default return value from 'english' to 'thai' in detection functions
   - Maintained existing threshold logic for Thai character ratio detection

3. **update-conversations.mjs**
   - Updated `detectConversationLanguage()` to return 'thai' instead of 'english' for empty text
   - Updated prompt generation to use Thai prompts for 'unknown' language cases

4. **process-conversations.mjs**
   - Updated `detectConversationLanguage()` to return 'thai' instead of 'english' for empty text
   - Updated prompt generation to use Thai prompts for 'unknown' language cases

### Code Changes Summary

**Empty Text Handling**:
```javascript
// Before
if (!text || text.trim().length === 0) {
  return 'english';
}

// After
if (!text || text.trim().length === 0) {
  return 'thai';
}
```

**Unknown Language Prompts**:
```javascript
// Before
case 'unknown':
  return getEnglishPrompt(); // or similar English prompt

// After
case 'unknown':
  return getThaiPrompt(); // or similar Thai prompt
```

## Impact

### Media Analysis
- Media analysis now defaults to Thai language processing
- Thai-specific prompts used for media content analysis when language cannot be determined
- Improved accuracy for Thai media content descriptions

### Daily Summaries
- Daily summary generation defaults to Thai language prompts
- Unknown language cases now use Thai instructions for event/action/topic extraction
- Better extraction quality for Thai conversations with low text content

### Conversation Summarization
- Main conversation summaries default to Thai language processing
- Unknown language cases use Thai prompts for summarization
- Improved handling of conversations with minimal text content

### Language Detection Behavior
- Conversations with <5% Thai characters now default to Thai instead of English
- Empty text content now defaults to Thai instead of English
- Mixed language detection (5-60% Thai) unchanged
- Pure Thai detection (>60% Thai) unchanged

## Benefits

1. **Improved Thai Content Processing**: Majority of LINE conversations now receive optimal Thai language processing
2. **Better AI Extraction**: Thai-specific prompts provide better context for Thai content analysis
3. **Reduced False Positives**: Less misclassification of Thai content as English
4. **Consistent User Experience**: Thai users see more accurate and culturally appropriate summaries

## Potential Considerations

### English Content Impact
- Pure English conversations (<5% Thai characters) will now be processed with Thai prompts
- May reduce extraction quality for minority English conversations
- Trade-off accepted given 70%+ Thai content in system

### Mixed Language Content
- Mixed language detection (5-60% Thai) unchanged, still uses appropriate mixed/English prompts
- No impact on existing mixed language handling

### Migration Considerations
- Existing summaries not automatically regenerated
- New processing will use Thai defaults
- Manual reprocessing may be needed for affected conversations

## Testing Recommendations

1. **Thai Content Verification**: Test Thai conversations show improved extraction quality
2. **English Content Monitoring**: Monitor English conversations for any quality degradation
3. **Empty Content Handling**: Verify conversations with minimal text default to Thai appropriately
4. **Mixed Language Validation**: Ensure mixed language detection still works correctly

## Rollback Plan

If issues arise, the change can be reverted by:
1. Changing default return values back to 'english' in all four modified files
2. Reverting prompt generation for 'unknown' cases back to English prompts
3. Testing affected conversations after rollback

## Related Documentation

- `docs/kb/yomi-daily-summaries.md` - Daily summaries documentation
- `docs/kb/yomi.md` - Main Yomi documentation
- `scripts/yomi/analyze-media.mjs` - Media analysis with language detection
- `scripts/yomi/language-detection.mjs` - Language detection utilities
- `scripts/yomi/update-conversations.mjs` - Conversation update processing
- `scripts/yomi/process-conversations.mjs` - Conversation processing logic

## Tags

yomi, thai-language, language-detection, default-language, media-analysis, daily-summaries, conversation-summarization, prompt-generation
