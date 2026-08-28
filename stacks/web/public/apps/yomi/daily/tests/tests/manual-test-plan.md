# Daily2 Manual Test Plan

## Test Environment
- URL: http://tony-omen.local:8080/apps/yomi/daily2/index.html
- Test Chat: u494a728e423a3d45182ad44bd1003cf6 (KKGT @DAY)

## Unit Tests
1. **DateUtils Module Tests**
   - URL: http://tony-omen.local:8080/apps/yomi/daily2/tests/test-daily2.html
   - Expected: All tests pass (green)
   - Tests: thailandDateToUtc, utcToThailandDate, getThailandDateRange, formatDate, formatTime, isValidDate, formatDateKey

## Integration Tests

### 1. Page Load Test
- **Steps**: Navigate to daily2/index.html
- **Expected**: 
  - Page loads without JavaScript errors
  - Calendar displays current month
  - Chat selector populated with conversations
  - No console errors

### 2. Calendar Navigation Test
- **Steps**:
  - Click "Previous Month" button
  - Click "Next Month" button
- **Expected**:
  - Calendar updates to show previous/next month
  - Day headers remain visible
  - No console errors

### 3. Date Selection Test
- **Steps**:
  - Click on a calendar day with data (marked with dot)
  - Click on a calendar day without data
- **Expected**:
  - Selected date highlights in blue
  - Summary panel updates with date info
  - Message panel shows "Select a date to view messages" for empty dates
  - No console errors

### 4. Summary Display Test
- **Steps**:
  - Select a date with existing summary
  - Check summary content
- **Expected**:
  - Summary displays events, actions, topics
  - "Re-summarize" button visible
  - Message count displayed
  - "View conversation" link present

### 5. Re-summarization Test
- **Steps**:
  - Select a date
  - Click "Re-summarize" button
  - Wait for completion
- **Expected**:
  - Progress indicator shows steps
  - Button disabled during processing
  - "✓ Done - refreshing..." message appears
  - Summary refreshes automatically
  - No console errors

### 6. Message List Test
- **Steps**:
  - Select a date with messages
  - Scroll through message list
- **Expected**:
  - Messages display with sender, time, and content
  - System messages styled differently
  - Message count accurate
  - Scrollable if many messages

### 7. Chat Switching Test
- **Steps**:
  - Select different conversation from dropdown
  - Verify calendar updates
- **Expected**:
  - URL updates with new chat ID
  - Calendar shows data for new chat
  - Most recent date auto-selected
  - No console errors

### 8. Thailand Timezone Test
- **Steps**:
  - Select a date
  - Check displayed date format
  - Verify summary date matches Thailand calendar
- **Expected**:
  - Dates displayed in Thailand timezone (UTC+7)
  - No date mismatches
  - Consistent across all displays

### 9. Responsive Layout Test
- **Steps**:
  - Resize browser window
  - Check layout on different sizes
- **Expected**:
  - Calendar panel maintains width
  - Summary panel adjusts
  - Message panel scrollable
  - No horizontal overflow

### 10. Error Handling Test
- **Steps**:
  - Try to re-summarize with network disconnected
  - Select invalid date (if possible)
- **Expected**:
  - Error messages displayed
  - UI remains functional
  - No console crashes

## Performance Tests

### 1. Initial Load
- **Expected**: Page loads within 2 seconds
- **Check**: Network tab in dev tools

### 2. Calendar Rendering
- **Expected**: Calendar renders within 500ms
- **Check**: Performance timing

### 3. Summary Loading
- **Expected**: Summary loads within 1 second
- **Check**: Performance timing

### 4. Message Loading
- **Expected**: 100 messages load within 2 seconds
- **Check**: Performance timing

## Console Error Check
- **Steps**: Open browser dev tools console
- **Expected**: No errors, no warnings
- **Check**: Console tab throughout all tests

## Test Results Template
```
Test Date: ___________
Tester: ___________
Environment: ___________

Unit Tests: [PASS/FAIL]
Integration Tests: [PASS/FAIL]
Performance Tests: [PASS/FAIL]

Issues Found:
1. 
2. 
3. 

Overall Result: [PASS/FAIL]
```
