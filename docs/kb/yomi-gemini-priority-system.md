# Yomi Gemini Priority System
## What it is

Selective re-summarization system for Gemini API to manage quota and prioritize high-value content.

## Context/Background

Created 2026-08-06 as part of Chaba infrastructure documentation.


## Overview
Selective re-summarization system for Gemini API to manage quota and prioritize high-value content.

## Environment Variables

### USE_GEMINI
- **Default**: `false` (use Llama)
- **Purpose**: Enable Gemini API for summarization
- **Usage**: `USE_GEMINI=true node scripts/yomi/update-conversations.mjs`

### GEMINI_MAX_DATES
- **Default**: `10`
- **Purpose**: Maximum number of dates to process per run with Gemini
- **Usage**: `GEMINI_MAX_DATES=5 USE_GEMINI=true node scripts/yomi/update-conversations.mjs`

### GEMINI_PRIORITY_MODE
- **Default**: `recent`
- **Options**: `recent`, `high-activity`, `all`
- **Purpose**: Determine which dates to prioritize for Gemini summarization

## Priority Modes

### `recent` (Default)
- **Behavior**: Process most recent dates first (descending chronological order)
- **Use Case**: Focus on current/relevant conversations
- **Example**: Last 10 days of messages

### `high-activity`
- **Behavior**: Process dates with most messages first (descending message count)
- **Use Case**: Focus on conversations with most content/complexity
- **Example**: 10 most active days regardless of date

### `all`
- **Behavior**: Process all dates within last 30 days chronologically
- **Use Case**: Full re-summarization (no prioritization)
- **Example**: All dates in last 30 days

## Implementation

### prioritizeDates Function
```javascript
function prioritizeDates(datesArray, mode, limit) {
  if (mode === 'all') {
    return datesArray.sort((a, b) => a[0].localeCompare(b[0]));
  }
  
  if (mode === 'recent') {
    return datesArray
      .sort((a, b) => b[0].localeCompare(a[0]))
      .slice(0, limit);
  }
  
  if (mode === 'high-activity') {
    return datesArray
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, limit);
  }
  
  return datesArray.sort((a, b) => a[0].localeCompare(b[0]));
}
```

### Integration in generateDailySummaries
```javascript
if (USE_GEMINI && GEMINI_PRIORITY_MODE !== 'all') {
  datesArray = prioritizeDates(datesArray, GEMINI_PRIORITY_MODE, GEMINI_MAX_DATES);
  console.log(`Gemini priority mode: ${GEMINI_PRIORITY_MODE}, processing ${datesArray.length} dates (limit: ${GEMINI_MAX_DATES})`);
} else {
  datesArray.sort((a, b) => a[0].localeCompare(b[0]));
}
```

## Usage Examples

### Process recent 5 days with Gemini
```bash
GEMINI_MAX_DATES=5 GEMINI_PRIORITY_MODE=recent USE_GEMINI=true node scripts/yomi/update-conversations.mjs
```

### Process 10 most active days with Gemini
```bash
GEMINI_MAX_DATES=10 GEMINI_PRIORITY_MODE=high-activity USE_GEMINI=true node scripts/yomi/update-conversations.mjs
```

### Process all dates (no limit)
```bash
GEMINI_PRIORITY_MODE=all USE_GEMINI=true node scripts/yomi/update-conversations.mjs
```

## Migration Strategy

### Phase 1: Recent Dates (Week 1-2)
```bash
GEMINI_MAX_DATES=5 GEMINI_PRIORITY_MODE=recent USE_GEMINI=true
```
- Focus on most recent 5 days
- Daily runs to gradually re-summarize recent content
- Monitor quality and quota usage

### Phase 2: High Activity (Week 3-4)
```bash
GEMINI_MAX_DATES=10 GEMINI_PRIORITY_MODE=high-activity USE_GEMINI=true
```
- Process 10 most active days
- Focus on conversations with most value
- Evaluate quality improvement

### Phase 3: Full Migration (Month 2+)
```bash
GEMINI_PRIORITY_MODE=all USE_GEMINI=true
```
- Process all dates within last 30 days
- Full Gemini migration
- Consider paid tier if needed

## Quota Management

### Gemma 4 31B Free Tier
- **Model**: `gemma-4-31b-it`
- **Limits**: Higher than Gemini Flash (exact limits vary by account)
- **Strategy**: Use priority system to stay within quota

### Batch Processing
- **Batch Size**: 4 dates per API call
- **Efficiency**: Reduces API calls by 75%
- **Rate Limiting**: 15 requests/minute (conservative)

### Monitoring
- Check console output for "Gemini priority mode" messages
- Monitor API quota in Google AI Studio
- Adjust GEMINI_MAX_DATES based on usage

## Files Modified
- `/home/tony/CascadeProjects/chaba/scripts/yomi/update-conversations.mjs`
  - Added GEMINI_MAX_DATES environment variable
  - Added GEMINI_PRIORITY_MODE environment variable
  - Added prioritizeDates() function
  - Integrated prioritization in generateDailySummaries()

## Related Documentation
- [Gemini API Integration](./gemini-api-limits.md)
- [Yomi Daily Calendar Timezone](./yomi-daily-calendar-timezone.md)
- [Gemma 4 Model Card](https://ai.google.dev/gemma/docs/core/model_card_4)

## Tags

- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **2026**: 2026
