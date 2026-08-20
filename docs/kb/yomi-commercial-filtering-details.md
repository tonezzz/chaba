---
category: operations
---

# Key Details

### Problem
- Commercial entities (7-Eleven, CP ALL) send frequent promotional messages
- These messages dominated daily summaries with low-value content
- Processing time wasted on non-personal promotional content
- Reduced usefulness of daily summaries for personal communication insights

### Solution
- Pattern-based exclusion system in daily summarization
- Regex pattern matching for commercial entity names
- Configurable exclude list for easy maintenance
- Reduces processing load while preserving personal messages

## Implementation

### Location
`scripts/yomi/process-conversations.mjs` - daily summarization logic

### Patterns Added
```javascript
// Commercial entity patterns
/7-Eleven/i
/CP\s*ALL/i
```

### Exclude List
- CP ALL 7-Eleven TH added to commercial exclude list
- Extensible for additional commercial entities

### Processing Logic
- Pattern matching applied during daily summary generation
- Messages matching commercial patterns excluded from daily summaries
- Original messages still stored in database for full conversation view
- Only affects daily summarization, not conversation categorization

## Configuration

### Adding New Commercial Patterns
Edit `scripts/yomi/process-conversations.mjs`:
```javascript
const commercialPatterns = [
  /7-Eleven/i,
  /CP\s*ALL/i,
  // Add new patterns here
];
```

### Pattern Guidelines
- Use case-insensitive matching (`/pattern/i`)
- Include common variations (e.g., `CP\s*ALL` for "CP ALL", "CPALL")
- Test patterns against sample messages before deployment
- Consider false positives when adding broad patterns

## Technical Details

### Impact Assessment
- Reduces daily summary processing time
- Improves signal-to-noise ratio in daily summaries
- Preserves full conversation history in database
- No impact on conversation categorization or search

### Performance
- Minimal performance overhead (regex matching)
- Reduces LLM API calls for filtered messages
- Faster daily summary generation

### Data Integrity
- Original messages preserved in database
- Filtering only affects summary generation
- No data loss from filtering
- Reversible by removing patterns

## Verification

### Testing
```bash
# Test pattern matching
node -e "console.log(/7-Eleven/i.test('Promo from 7-Eleven'))"

# Run daily summarization with test data
node scripts/yomi/process-conversations.mjs
```

### Validation
- Check daily summaries for absence of commercial content
- Verify personal messages still included in summaries
- Monitor processing time improvements
- Review conversation categorization accuracy

## Troubleshooting

### False Positives
- If legitimate messages filtered, refine patterns
- Use more specific patterns (e.g., include context)
- Consider whitelisting specific conversations
- Review filtered messages in database

### False Negatives
- If commercial messages still appear, expand patterns
- Add common variations and misspellings
- Include brand-specific terminology
- Monitor commercial message content for new patterns

### Pattern Performance
- Complex regex patterns may impact performance
- Test pattern complexity before deployment
- Consider pre-compiling frequently used patterns
- Monitor processing time after pattern changes

