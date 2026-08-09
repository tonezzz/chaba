# Yomi Daily Calendar Timezone Conversion

## Context

The Yomi daily calendar widget displays daily summaries with date selection and re-summarization functionality. The system stores dates in UTC but needs to display them correctly for Thailand timezone (UTC+7).

## Problem

Database stores daily summary dates at 17:00:00 UTC to represent midnight in Thailand (UTC+7). However, the browser runs in UTC-7 timezone, which caused a 1-day offset in calendar display - showing dates 5-6 instead of the intended 4-5 for August.

## Solution

Implemented timezone-aware date conversion:

### Database to Calendar Display
- Database stores: `2026-08-04T17:00:00.000Z` (UTC 17:00 = Thailand midnight)
- Browser (UTC-7) converts to: August 4, 10:00 AM local time
- Add 1 day to get intended Thailand date: August 5
- Calendar displays: August 5 (correct Thailand date)

### Calendar to API Calls
- User selects: August 5 (Thailand date)
- Subtract 1 day to convert to UTC format: August 4
- API receives: `2026-08-04` (matches database format)

## Implementation Details

### File Modified
`/home/tony/CascadeProjects/chaba-yomi/stacks/web/public/apps/yomi/daily2/index.html`

### Key Functions

**Calendar Date Display:**
```javascript
// Convert UTC database date to Thailand local date for calendar
const utcDate = new Date(s.date);
const localYear = utcDate.getFullYear();
const localMonth = utcDate.getMonth();
const localDay = utcDate.getDate() + 1;
return `${localYear}-${String(localMonth + 1).padStart(2, '0')}-${String(localDay).padStart(2, '0')}`;
```

**API Date Conversion:**
```javascript
// Convert local calendar date to UTC format for API
const [localYear, localMonth, localDay] = dateStr.split('-').map(Number);
const utcDateStr = `${localYear}-${String(localMonth).padStart(2, '0')}-${String(localDay - 1).padStart(2, '0')}`;
```

### Applied To
- Calendar day highlighting (has-data class)
- Date selection and summary display
- Re-summarize button date parameter
- Initial month selection for most recent summary

## Additional Features Implemented

1. **Calendar Widget** - Shows available summary dates with visual indicators
2. **Date Selection** - Click handler to display selected day's summary
3. **Re-summarize Button** - In-place progress indication with spinner and status text
4. **Auto-refresh** - Summary refreshes automatically after re-summarization
5. **Basic Auth Fix** - Removed `{ credentials: 'include' }` from fetch calls

## Deployment

Changes must be copied to main chaba repository for Docker volume mount:
```bash
cp /home/tony/CascadeProjects/chaba-yomi/stacks/web/public/apps/yomi/daily2/index.html \
   /home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/daily2/index.html
```

## Verification

Tested with playlive.tony-dell:
- Calendar shows correct dates (4-5 for August)
- Click functionality works for both dates
- Re-summarize button shows progress and refreshes summary
- Date conversion correctly applied for API calls

## Related

- Language-aware summarization (Thai/English/mixed) already implemented
- Basic auth URL handling for fetch API
- Docker volume mount deployment workflow

## Tags

- yomi
- calendar
- timezone
- utc-conversion
- thailand-timezone
- daily-summaries
- frontend
