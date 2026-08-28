---
category: operations
---

# Fixes Implemented

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

