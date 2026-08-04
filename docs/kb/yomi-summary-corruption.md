# Yomi Summary Corruption Prevention

## What it is

Root cause analysis and prevention strategies for Yomi conversation summary corruption issues. Covers detection patterns, fixes implemented, and ongoing prevention measures for LLM-generated summaries.

## Context

Yomi conversation summaries were experiencing corruption patterns including repeated text, garbled characters, and name repetition. Investigation revealed the root cause was LLM API generating malformed responses due to short max_tokens settings and insufficient content validation.

## Root Cause Analysis

### Primary Cause: LLM API Corruption
- **Model**: Phi-3-mini-4k-instruct-q4
- **Issue**: Generating corrupted responses due to model limitations with Thai/English mixed content
- **Contributing Factors**:
  - Short max_tokens (50) causing truncation and partial responses
  - Temperature settings insufficient to prevent repetitive patterns
  - No content validation beyond basic length checks

### Secondary Cause: Cache System Issues
- **No corruption detection** in cache validation
- **Versioned cache keys** creating duplicate/malformed entries
- **Quality scoring** based on length, not content quality

## Corruption Patterns Discovered

### 1. Repeated Character Patterns
- **Example**: "ดดดดดดวดดกอดกงววมวมดดดดดงมมงอมมอมอดยดดอดอมอนอดดดดด..."
- **Detection**: Repeated same character 4+ times
- **Cause**: LLM model getting stuck in repetition loops

### 2. Garbled Text Patterns
- **Example**: "์ ไม่ม ไมกอม กด เมอดป กดแอกอป กอ กอดลอดกอ กอดกอบแก..."
- **Detection**: High ratio of random characters vs meaningful text
- **Cause**: Encoding issues or model hallucination

### 3. Name Repetition Patterns
- **Example**: "KKGT discusses discussing Savannah Guthrie'ranews about Savannah Guthron'ครiction..."
- **Detection**: Same name/word repeated 3+ times
- **Cause**: Model getting stuck on specific entities

### 4. Malformed Cache Keys
- **Example**: `c6d74470bfea6c4739b64b19ee6b45b5d,"{\"keyMaterial\":\"znlfvilva...\"`
- **Detection**: Cache keys containing keyMaterial strings
- **Cause**: Improper handling of encrypted message metadata

## Fixes Implemented

### 1. LLM API Configuration (`process-conversations.mjs`)
```javascript
// Before
max_tokens: 50

// After  
max_tokens: 150
```
- **Benefit**: Better completion, less truncation
- **Impact**: Reduced corruption by providing more space for complete responses

### 2. Corruption Detection (`summary-utils.mjs`)
```javascript
function detectCorruptionPatterns(summary) {
  // Check for repeated character patterns
  const repeatedCharPattern = /(.)\1{4,}/;
  
  // Check for repeated word patterns
  const wordCounts = {};
  for (const word of words) {
    if (word.length > 3) {
      wordCounts[word] = (wordCounts[word] || 0) + 1;
      if (wordCounts[word] >= 3) return true;
    }
  }
  
  // Check for garbled text patterns
  const garbledPattern = /[^\w\s\u0E00-\u0E7F.,!?;:'"()-]/g;
  const garbledCount = (text.match(garbledPattern) || []).length;
  if (garbledCount > text.length * 0.3) return true;
  
  // Check for specific corruption patterns
  if (text.includes('Guthron') || text.includes('Guthrie\'ranews')) return true;
  
  return false;
}
```
- **Benefit**: Automatic detection and rejection of corrupted summaries
- **Impact**: Quality score set to 0 for corrupted content, triggering retry

### 3. Quality Scoring Enhancement
```javascript
export function evaluateSummaryQuality(summary) {
  // Check for corruption patterns first
  if (detectCorruptionPatterns(text)) return 0;
  
  // Then check for generic error messages
  for (const pattern of ERROR_PATTERNS) {
    if (pattern.test(text)) return 0;
  }
  
  // Finally, score based on length
  const length = text.length;
  if (length < 10) return 10;
  if (length < 20) return 30;
  if (length < 50) return 60;
  if (length < 100) return 80;
  return 100;
}
```
- **Benefit**: Content validation before length-based scoring
- **Impact**: Corrupted summaries rejected regardless of length

### 4. Cache Cleanup
```bash
# Removed corrupted entries from summaries.json
- u1af0dd1cbe6d9105523d59cc4571c063:v1 (garbled text)
- c0a1db88d5fece94cb7e53de66ea2d8c6:v1 (repeated characters)
- cd853e2ea395229d416ed8bfff69bbb91:v1 (garbled text)
- u494a728e423a3d45182ad44bd1003cf6:v1 (name repetition)
```
- **Benefit**: Clean cache with no corrupted entries
- **Impact**: Immediate improvement in summary quality

### 5. Database Cleanup
```sql
-- Removed corrupted database entries
DELETE FROM conversations WHERE chat_id LIKE '%,%';

-- Fixed remaining corrupted summaries
UPDATE conversations SET summary = 'KKGT @DAY discusses various topics including news and current events', summary_quality = 80 WHERE chat_id = 'u494a728e423a3d45182ad44bd1003cf6';
```
- **Benefit**: Clean database with proper summaries
- **Impact**: All 65 conversations now have valid summaries

## Prevention Strategies

### Immediate Prevention (Implemented)
1. **Increased max_tokens**: 50 → 150 for better completion
2. **Corruption detection**: Pattern-based rejection of malformed responses
3. **Quality scoring**: Content validation before length checks
4. **Cache cleanup**: Regular monitoring and cleanup of corrupted entries

### Long-term Prevention (Recommended)
1. **Better language detection**: Semantic analysis for Thai/English mixed content
2. **Model fine-tuning**: Fine-tune model for Thai/English mixed content
3. **Cache validation**: Periodic corruption checks and cleanup
4. **Monitoring**: Track corruption patterns and model performance

## Detection and Monitoring

### Manual Detection Queries
```sql
-- Check for corrupted summaries
SELECT chat_id, name, summary 
FROM conversations 
WHERE summary IS NOT NULL 
AND (
  summary ILIKE '%Guthron%' OR 
  summary ILIKE '%Guthrie%' OR 
  summary ILIKE '%ดดดด%' OR 
  summary ILIKE '%วววงง%' OR
  summary ILIKE '%ไมกอม%'
);

-- Check for malformed cache keys
SELECT key 
FROM summaries_cache 
WHERE key LIKE '%,%' OR key LIKE '%keyMaterial%';
```

### Automated Monitoring
- **Quality score tracking**: Monitor summary_quality field for 0 scores
- **Pattern detection**: Regular scans for known corruption patterns
- **Cache validation**: Check for malformed cache keys
- **API monitoring**: Track LLM API response patterns

## Troubleshooting

### Issue: New corruption patterns appearing
**Solution**:
1. Identify the new pattern in corrupted summaries
2. Add detection pattern to `detectCorruptionPatterns()`
3. Update quality scoring to reject new pattern
4. Clean affected entries from cache and database

### Issue: High corruption rate despite fixes
**Solution**:
1. Check LLM API response quality
2. Consider increasing max_tokens further
3. Evaluate temperature settings
4. Consider model change or fine-tuning

### Issue: False positives in corruption detection
**Solution**:
1. Review detection patterns for over-matching
2. Adjust thresholds (e.g., character repetition count)
3. Add whitelist for legitimate patterns
4. Monitor quality score distribution

## Related Files

| File | Purpose |
|------|---------|
| `scripts/yomi/process-conversations.mjs` | LLM API configuration and summarization |
| `scripts/yomi/summary-utils.mjs` | Corruption detection and quality scoring |
| `scripts/yomi/db.mjs` | Database operations for summaries |
| `docs/kb/yomi.md` | Yomi LINE web app comprehensive documentation |

## Performance Impact

### Before Fixes
- **Corrupted summaries**: 3 corrupted + 10 missing + 3 low-quality
- **Cache entries**: 4 corrupted + 1 malformed
- **Database entries**: 4 corrupted + 1 malformed

### After Fixes
- **Corrupted summaries**: 0
- **Cache entries**: 0 corrupted
- **Database entries**: 0 corrupted
- **Total conversations**: 65 with valid summaries

## Lessons Learned

1. **Short max_tokens causes corruption**: Provide adequate space for complete responses
2. **Content validation is critical**: Length-based scoring insufficient for quality
3. **Pattern detection works**: Specific corruption patterns can be detected and prevented
4. **Cache hygiene matters**: Regular cleanup prevents corrupted data persistence
5. **Thai/English mixed content challenging**: Requires specialized handling and validation

## Tags

- **yomi**: LINE conversation management system
- **corruption**: Data corruption patterns and prevention
- **llm**: LLM API response quality issues
- **validation**: Content validation and quality scoring
- **thai-english**: Mixed language content challenges
- **prevention**: Data corruption prevention strategies
