---
category: operations
---

# Batch Daily Summarization (2026-08-03)

### Overview

Daily summarization processes conversation messages grouped by date to extract structured information:

**Structured Output Format:**
```json
{
  "events": ["Event 1", "Event 2"],
  "actions": ["Action 1", "Action 2"],
  "topics": ["Topic 1", "Topic 2"]
}
```

**Database Schema:**
- Table: `daily_summaries`
- Fields: chat_id, date, events (array), actions (array), topics (array), message_count
- Index: chat_id + date for efficient lookups

### Batch Processing Strategy

**Batch Size:** 4 dates per API call
- Reduces Llama API calls by 60-75%
- Processes multiple dates in single request
- Falls back to single-date processing on errors

**Date Range:** Last 30 days
- Reduces processing load by 40-60%
- Focuses on recent activity
- Configurable for different use cases

**Processing Order:**
1. One-on-one conversations (highest priority)
2. Recent conversations (last 30 days)
3. Older conversations (historical data)

### Implementation

**File:** `scripts/yomi/process-conversations.mjs`

**Functions:**
- `groupMessagesByDate(messages)`: Groups messages by date
- `generateDailySummaries(chatId, messages, name)`: Main batch processing function
- `saveDailySummary(chatId, date, events, actions, topics, messageCount)`: Saves to database
- `processSingleDate(chatId, date, dayMessages, name, total, processed)`: Fallback for single dates

**Batch Processing Flow:**
1. Group messages by date
2. Filter to last 30 days
3. Create batch prompts (4 dates each)
4. Submit to Llama API with daily rate limiter
5. Parse structured JSON response
6. Save individual date summaries to database
7. Handle errors with circuit breaker logic

### Daily Summary Prompt

```
Extract structured information from this LINE conversation for each date. Return JSON with date keys and values containing events, actions, and topics arrays.

${messagesByDate}

Return format:
{
  "YYYY-MM-DD": {
    "events": ["event1", "event2"],
    "actions": ["action1", "action2"],
    "topics": ["topic1", "topic2"]
  }
}
```

### Performance Optimizations

**Parallel Processing:**
- Process 3 conversations simultaneously for daily summaries
- Uses daily rate limiter (3 concurrent)
- Balances speed with GPU load

**Selective Processing:**
- Skip dates with < 5 messages
- Skip conversations with < 10 total messages
- Prioritize active conversations

**Error Handling:**
- Circuit breaker prevents cascading failures
- Automatic fallback to single-date processing
- Retry with exponential backoff
- Log errors for troubleshooting

### API Integration

**Endpoint:** `/api/yomi/daily?chat=<id>`
- Returns daily summaries for a conversation
- JSON format with date keys
- Includes message count per date

**Example Response:**
```json
{
  "2026-08-01": {
    "events": ["Meeting scheduled", "Project deadline discussed"],
    "actions": ["Sent email", "Created task"],
    "topics": ["Project management", "Deadlines"]
  },
  "2026-08-02": {
    "events": ["Code review completed"],
    "actions": ["Merged PR", "Updated documentation"],
    "topics": ["Development", "Code review"]
  }
}
```

### Database Integration

**Query for Daily Summaries:**
```sql
SELECT date, events, actions, topics, message_count
FROM daily_summaries
WHERE chat_id = $1
ORDER BY date DESC
```

**Statistics Tracking:**
- Total daily summaries per conversation
- Latest summary date
- Average messages per day
- Coverage percentage (days with summaries / total days)

