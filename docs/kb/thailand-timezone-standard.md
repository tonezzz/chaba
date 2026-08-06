# Thailand Timezone Standard for Date Handling

## What it is

Standardized approach for handling Thailand calendar dates across the Yomi system using **Thailand calendar day definition (17:00 UTC to 16:59:59 UTC next day)**. This ensures consistent date representation and display across different timezones and locales.

## Context/Background

Implemented on 2026-08-06 to resolve date handling inconsistencies in Yomi daily summaries and calendar views. Previous implementations had timezone conversion issues causing date misalignment between storage, processing, and display layers.

**Critical Discovery (2026-08-06):**
- Database stores `delivered_time` as Unix seconds × 1000 (pseudo-milliseconds) in UTC
- Thailand calendar date is defined as: **17:00 UTC to 16:59:59 UTC next day**
- This means Thailand midnight = 17:00 UTC previous day
- Example: Thailand calendar date "2026-08-03" spans 2026-08-03T17:00:00Z to 2026-08-04T16:59:59Z

## Key Details

### Timezone Fundamentals

**Thailand Timezone:**
- UTC+7 (Indochina Time)
- No daylight saving time
- Consistent year-round offset

**Thailand Calendar Day Definition:**
- **Start:** 17:00 UTC (midnight Thailand time)
- **End:** 16:59:59 UTC next day (23:59:59 Thailand time)
- **Example:** Thailand calendar date "2026-08-03" = 2026-08-03T17:00:00Z to 2026-08-04T16:59:59Z

### Database Storage Format

**Messages Table:**
```sql
-- delivered_time stored as bigint (Unix seconds × 1000)
-- Example: 1784205597875 = 1784205597 seconds = 2026-07-16T12:39:57.000Z UTC
SELECT message_id, delivered_time, to_timestamp(delivered_time / 1000) as utc_time
FROM messages WHERE chat_id = $1;
```

**Daily Summaries Table:**
```sql
-- date stored as DATE type (YYYY-MM-DD)
-- Represents Thailand calendar date, not UTC timestamp
SELECT chat_id, date, message_count
FROM daily_summaries WHERE chat_id = $1;
```

### Conversion Formulas

**IMPORTANT:** There are TWO different conversions depending on the use case:

#### 1. UTC Timestamp → Thailand Calendar Date (for filtering/grouping)
```javascript
// Thailand calendar date: 17:00 UTC to 16:59:59 UTC next day
// To convert UTC timestamp to Thailand calendar date:
// SUBTRACT 7 hours to align with Thailand calendar day start (17:00 UTC)
function utcToThailandCalendarDate(isoTimestamp) {
  const utcDate = new Date(isoTimestamp);
  const thailandCalendarDate = new Date(utcDate.getTime() - (7 * 60 * 60 * 1000));
  return thailandCalendarDate.toISOString().split('T')[0];
}

// Example: 2026-07-17T00:15:59.619Z UTC → 2026-07-16 (in July 16 Thailand calendar day)
// Reason: 00:15:59 UTC is after 17:00 UTC previous day, so it's in next Thailand calendar day
```

#### 2. UTC Timestamp → Thailand Time (for display)
```javascript
// Convert UTC timestamp to Thailand time (UTC+7) for display
function utcToThailandTime(isoTimestamp) {
  const utcDate = new Date(isoTimestamp);
  const thailandTime = new Date(utcDate.getTime() + (7 * 60 * 60 * 1000));
  return thailandTime.toISOString();
}

// Example: 2026-07-17T00:15:59.619Z UTC → 2026-07-17T07:15:59.619Z Thailand
```

#### 3. Thailand Calendar Date → UTC Range (for API filtering)
```javascript
// Convert Thailand calendar date to UTC range for database queries
function getThailandDateRange(dateStr) {
  const [year, month, day] = dateStr.split('-').map(Number);
  
  // Thailand calendar date starts at 17:00 UTC
  const startDate = new Date(Date.UTC(year, month - 1, day, 17, 0, 0));
  
  // Thailand calendar date ends at 16:59:59 UTC next day
  const endDate = new Date(Date.UTC(year, month - 1, day + 1, 16, 59, 59));
  
  return {
    startDate: startDate.toISOString(),
    endDate: endDate.toISOString()
  };
}

// Example: "2026-08-03" → 
//   startDate: 2026-08-03T17:00:00.000Z
//   endDate: 2026-08-04T16:59:59.000Z
```

### Implementation Locations

**Frontend (daily2):**
- `stacks/web/public/apps/yomi/daily2/js/date-utils.js` - Date conversion utilities
- `stacks/web/public/apps/yomi/daily2/js/calendar.js` - Calendar date generation
- `stacks/web/public/apps/yomi/daily2/js/messages.js` - Message filtering by date
- `stacks/web/public/apps/yomi/daily2/js/summary.js` - Summary display

**Backend (yomi):**
- `scripts/yomi/update-conversations.mjs` - Message grouping and summary generation
- `scripts/yomi/yomi-api.mjs` - API date filtering

### Date Grouping Logic

**Backend (update-conversations.mjs):**
```javascript
// Group messages by Thailand calendar day (UTC+7)
// Add 7 hours to convert UTC to Thailand time
function groupMessagesByDate(messages) {
  for (const m of messages) {
    const normalizedTime = normalizeTimestamp(m.deliveredTime);
    // Add 7 hours for Thailand timezone
    const thailandTime = new Date(normalizedTime + (7 * 60 * 60 * 1000));
    const date = thailandTime.toISOString().split('T')[0];
    // ... group by date
  }
}
```

**Frontend (date-utils.js):**
```javascript
// Convert UTC timestamp to Thailand calendar date
// SUBTRACT 7 hours to align with Thailand calendar day start (17:00 UTC)
utcToThailandDate(isoTimestamp) {
  const utcDate = new Date(isoTimestamp);
  const thailandCalendarDate = new Date(utcDate.getTime() - (7 * 60 * 60 * 1000));
  return thailandCalendarDate.toISOString().split('T')[0];
}
```

### API Filtering

**Messages API (yomi-api.mjs):**
```javascript
// API expects milliseconds for date filtering
// Database stores delivered_time as bigint (seconds × 1000)
async function handleMessages(chatId, url, res) {
  const startDate = url.searchParams.get('startDate'); // milliseconds
  const endDate = url.searchParams.get('endDate'); // milliseconds
  
  let query = `
    SELECT data, media_analysis FROM messages
    WHERE chat_id = $1
      AND delivered_time >= $2
      AND delivered_time <= $3
  `;
  // ... execute query
}
```

**Frontend (messages.js):**
```javascript
// Convert Thailand calendar date to UTC range in milliseconds
const { startDate, endDate } = DateUtils.getThailandDateRange(dateStr);
const startMs = DateUtils.isoToUnix(startDate) * 1000;
const endMs = DateUtils.isoToUnix(endDate) * 1000;

const url = `/api/yomi/messages?chat=${chatId}&startDate=${startMs}&endDate=${endMs}`;
```

## Usage

### Standard Conversion Pattern

**UTC Timestamp → Thailand Calendar Date (for filtering):**
```javascript
// Message at 2026-07-17T00:15:59.619Z UTC
// Convert to Thailand calendar date: SUBTRACT 7 hours
const thailandCalendarDate = utcToThailandCalendarDate('2026-07-17T00:15:59.619Z');
// Result: "2026-07-16" (in July 16 Thailand calendar day)
// Reason: 00:15:59 UTC is after 17:00 UTC previous day
```

**Thailand Calendar Date → UTC Range (for API):**
```javascript
// Thailand calendar date "2026-08-03"
const range = getThailandDateRange('2026-08-03');
// Result: {
//   startDate: "2026-08-03T17:00:00.000Z",
//   endDate: "2026-08-04T16:59:59.000Z"
// }
```

**UTC Timestamp → Thailand Time (for display):**
```javascript
// Message at 2026-07-17T00:15:59.619Z UTC
// Convert to Thailand time: ADD 7 hours
const thailandTime = utcToThailandTime('2026-07-17T00:15:59.619Z');
// Result: "2026-07-17T07:15:59.619Z"
```

### Database Queries

**Query by Thailand Date:**
```sql
-- Query messages for Thailand calendar date "2026-08-03"
-- Convert to UTC range: 2026-08-03T17:00:00Z to 2026-08-04T16:59:59Z
SELECT * FROM messages 
WHERE delivered_time >= 1785776400000  -- 2026-08-03T17:00:00.000Z in ms
  AND delivered_time <= 1785862799000  -- 2026-08-04T16:59:59.000Z in ms
  AND chat_id = $1;
```

**Query Daily Summaries:**
```sql
-- Daily summaries store Thailand calendar dates as DATE type
-- Direct date comparison works
SELECT * FROM daily_summaries 
WHERE chat_id = $1
  AND date >= '2026-08-01'
  AND date <= '2026-08-31'
ORDER BY date DESC;
```

## Validation

### Consistency Checks

**Verify Thailand Calendar Date Conversion:**
```javascript
// Test: Message at 2026-07-17T00:15:59.619Z UTC
// Expected: Thailand calendar date "2026-07-16"
const result = utcToThailandCalendarDate('2026-07-17T00:15:59.619Z');
console.assert(result === '2026-07-16', 'Conversion failed');
```

**Verify Date Range Conversion:**
```javascript
// Test: Thailand calendar date "2026-08-03"
// Expected: 2026-08-03T17:00:00Z to 2026-08-04T16:59:59Z
const range = getThailandDateRange('2026-08-03');
console.assert(range.startDate === '2026-08-03T17:00:00.000Z');
console.assert(range.endDate === '2026-08-04T16:59:59.000Z');
```

### Common Issues

**Date Off by One Day:**
- **Cause:** Using wrong conversion (add vs subtract 7 hours)
- **Fix:** Use SUBTRACT 7 hours for Thailand calendar date, ADD 7 hours for Thailand time
- **Check:** Verify which conversion you need (filtering vs display)

**API Filtering Returns Wrong Messages:**
- **Cause:** Using wrong timestamp units (seconds vs milliseconds)
- **Fix:** Database stores seconds × 1000, API expects milliseconds
- **Check:** Multiply Unix seconds by 1000 for API calls

**Calendar Shows Wrong Date:**
- **Cause:** Calendar generating dates in local time instead of Thailand calendar dates
- **Fix:** Use simple date generation (formatDateKey) without timezone conversion
- **Check:** Calendar dates should match database Thailand calendar dates

## Advantages

**Consistency:**
- Single Thailand calendar day definition across all components
- Clear distinction between Thailand calendar date and Thailand time
- Predictable conversion behavior

**Timezone Independence:**
- Database stores in UTC (timezone-agnostic)
- UI converts to Thailand calendar dates for display
- Works correctly from any location

**Query Performance:**
- UTC timestamps index efficiently
- Date range queries are straightforward
- No timezone conversion in database queries

## Best Practices

**Know Which Conversion to Use:**
- **Thailand calendar date (filtering/grouping):** SUBTRACT 7 hours
- **Thailand time (display):** ADD 7 hours
- **Date range (API):** Use getThailandDateRange() function

**Always Use Thailand Calendar Day Definition:**
- Thailand calendar day = 17:00 UTC to 16:59:59 UTC next day
- This is the canonical definition for all date operations
- Document the rationale in code comments

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

- `scripts/yomi/update-conversations.mjs` - Message grouping and summary generation
- `scripts/yomi/yomi-api.mjs` - API date filtering
- `stacks/web/public/apps/yomi/daily2/js/date-utils.js` - Date conversion utilities
- `docs/kb/yomi.md` - Yomi system overview
- `docs/kb/yomi-daily2-calendar.md` - Daily2 calendar implementation

## Tags

thailand, timezone, date-handling, utc-conversion, yomi, daily-summaries, calendar, timestamp, thailand-calendar-day, utc17, standardization
