# Thailand Timezone Standard for Date Handling

## What it is

Standardized approach for handling Thailand calendar dates across the Yomi system using UTC 17:00 (midnight Thailand time) as the canonical storage format. This ensures consistent date representation and display across different timezones and locales.

## Context/Background

Implemented on 2026-08-06 to resolve date handling inconsistencies in Yomi daily summaries and calendar views. Previous implementations had timezone conversion issues causing date misalignment between storage, processing, and display layers.

## Key Details

### Timezone Fundamentals

**Thailand Timezone:**
- UTC+7 (Indochina Time)
- No daylight saving time
- Consistent year-round offset

**The Problem:**
- Database stores UTC timestamps
- UI displays Thailand calendar dates
- Conversion logic was inconsistent across components
- Midnight Thailand = 17:00 UTC previous day

### The Standard: UTC 17:00

**Canonical Storage Format:**
- Thailand calendar date "2026-08-03" stored as "2026-08-02T17:00:00.000Z"
- This represents midnight Thailand time in UTC
- 17:00 UTC = 00:00 Thailand (next day)

**Conversion Formula:**
```javascript
// Thailand calendar date to UTC 17:00
const [year, month, day] = thailandDate.split('-').map(Number);
const utcDate = new Date(Date.UTC(year, month - 1, day, 17, 0, 0));
const utcDateStr = utcDate.toISOString();

// UTC 17:00 to Thailand calendar date
const utcDate = new Date(summary.date);
const thailandDate = new Date(utcDate.getTime() + (7 * 60 * 60 * 1000)); // Add 7 hours
const thailandDateStr = thailandDate.toISOString().split('T')[0];
```

### Implementation Locations

**Files Updated:**
- `scripts/yomi/process-conversations.mjs` - Date grouping for Thailand calendar
- `scripts/yomi/update-conversations.mjs` - Database storage with UTC 17:00
- `stacks/web/public/apps/yomi/daily2/index.html` - UI date conversion and display

**Database Storage:**
```sql
-- Daily summaries table stores Thailand calendar dates as UTC 17:00
INSERT INTO daily_summaries (chat_id, date, events, actions, topics, message_count)
VALUES ($1, $2, $3, $4, $5, $6)
-- $2 is UTC 17:00 timestamp for Thailand midnight
```

### Date Grouping Logic

**Process-Changes (Message Grouping):**
```javascript
// Group messages by Thailand calendar day
function groupMessagesByDate(messages) {
  for (const m of messages) {
    const timestamp = normalizeTimestamp(m.deliveredTime);
    // Group by Thailand calendar day (UTC+7)
    const thailandDate = new Date(timestamp + (7 * 60 * 60 * 1000));
    const date = thailandDate.toISOString().split('T')[0];
    // ... group by date
  }
}
```

**Update-Conversations (Database Storage):**
```javascript
async function saveDailySummary(chatId, date, events, actions, topics, messageCount) {
  // Store Thailand calendar date as 17:00 UTC (midnight Thailand time)
  const [year, month, day] = date.split('-').map(Number);
  const utcDate = new Date(Date.UTC(year, month - 1, day, 17, 0, 0));
  const dateWithTime = utcDate.toISOString();
  
  await pool.query(`
    INSERT INTO daily_summaries (chat_id, date, events, actions, topics, message_count)
    VALUES ($1, $2, $3, $4, $5, $6)
  `, [chatId, dateWithTime, events, actions, topics, messageCount]);
}
```

### UI Display Logic

**Daily2 Calendar (Date Display):**
```javascript
// Database stores Thailand calendar dates as 17:00 UTC
// Convert UTC 17:00 to Thailand calendar date for display
const utcDate = new Date(summary.date);
const thailandDate = new Date(utcDate.getTime() + (7 * 60 * 60 * 1000));
const localYear = thailandDate.getFullYear();
const localMonth = thailandDate.getMonth();
const localDay = thailandDate.getDate();
const dateKey = `${localYear}-${String(localMonth + 1).padStart(2, '0')}-${String(localDay).padStart(2, '0')}`;
```

**Daily2 Calendar (Re-summarization):**
```javascript
// Convert Thailand calendar date to UTC 17:00 for API
const [localYear, localMonth, localDay] = date.split('-').map(Number);
const utcDate = new Date(Date.UTC(localYear, localMonth - 1, localDay, 17, 0, 0));
const utcDateStr = utcDate.toISOString();

await resummarizeDay(chatId, utcDateStr);
```

## Usage

### Standard Conversion Pattern

**Thailand Date → UTC Storage:**
```javascript
function thailandToUTC(thailandDate) {
  const [year, month, day] = thailandDate.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day, 17, 0, 0)).toISOString();
}

// Example: "2026-08-03" → "2026-08-02T17:00:00.000Z"
```

**UTC Storage → Thailand Display:**
```javascript
function utcToThailand(utcTimestamp) {
  const utcDate = new Date(utcTimestamp);
  const thailandDate = new Date(utcDate.getTime() + (7 * 60 * 60 * 1000));
  return thailandDate.toISOString().split('T')[0];
}

// Example: "2026-08-02T17:00:00.000Z" → "2026-08-03"
```

### Database Queries

**Query by Thailand Date:**
```sql
-- Query daily summaries for Thailand date "2026-08-03"
SELECT * FROM daily_summaries 
WHERE date >= '2026-08-02T17:00:00.000Z' 
  AND date < '2026-08-03T17:00:00.000Z'
  AND chat_id = $1;
```

**Date Range Queries:**
```sql
-- Query summaries for Thailand date range
SELECT * FROM daily_summaries 
WHERE date >= '2026-08-01T17:00:00.000Z' 
  AND date < '2026-08-04T17:00:00.000Z'
  AND chat_id = $1
ORDER BY date;
```

## Validation

### Consistency Checks

**Verify Storage Format:**
```sql
-- Check that all daily summaries use UTC 17:00 pattern
SELECT 
  chat_id,
  date,
  EXTRACT(HOUR FROM date) as hour,
  EXTRACT(MINUTE FROM date) as minute
FROM daily_summaries
WHERE EXTRACT(HOUR FROM date) != 17 
   OR EXTRACT(MINUTE FROM date) != 0;
```

**Verify Display Conversion:**
```javascript
// Test conversion round-trip
const original = "2026-08-03";
const utc = thailandToUTC(original);
const back = utcToThailand(utc);
console.assert(original === back, "Conversion round-trip failed");
```

### Common Issues

**Date Off by One Day:**
- Cause: Using local time instead of UTC 17:00
- Fix: Ensure all conversions use Date.UTC() with hour=17

**Inconsistent Display:**
- Cause: Mixed conversion logic across components
- Fix: Standardize on UTC 17:00 → Thailand date pattern

**Database Query Issues:**
- Cause: Querying by date string instead of UTC range
- Fix: Use UTC 17:00 ranges for date-based queries

## Advantages

**Consistency:**
- Single canonical format across all components
- No ambiguity in date representation
- Predictable conversion behavior

**Timezone Independence:**
- Database stores in UTC (timezone-agnostic)
- UI converts to local timezone for display
- Works correctly from any location

**Query Performance:**
- UTC timestamps index efficiently
- Date range queries are straightforward
- No timezone conversion in database queries

## Best Practices

**Always Use UTC 17:00:**
- Never store Thailand dates as local time
- Always convert to UTC 17:00 before database storage
- Always convert from UTC 17:00 for display

**Use Date.UTC():**
- Avoid local Date constructor for UTC calculations
- Use Date.UTC() for explicit UTC timestamp creation
- Prevents timezone-related bugs

**Document Conversions:**
- Comment all timezone conversions with rationale
- Include examples in code comments
- Reference this standard in documentation

**Test Round-Trips:**
- Verify Thailand → UTC → Thailand conversions
- Test edge cases (month boundaries, year boundaries)
- Validate with actual Thailand calendar dates

## Related Documentation

- `scripts/yomi/process-conversations.mjs` - Message date grouping
- `scripts/yomi/update-conversations.mjs` - Database date storage
- `stacks/web/public/apps/yomi/daily2/index.html` - UI date display
- `docs/kb/yomi.md` - Yomi system overview
- `docs/kb/yomi-daily2-calendar.md` - Daily2 calendar implementation

## Tags

thailand, timezone, date-handling, utc-conversion, yomi, daily-summaries, calendar, timestamp, utc17, standardization