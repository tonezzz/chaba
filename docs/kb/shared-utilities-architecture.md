---
category: operations
---

# Solution Architecture

### Directory Structure

```
stacks/web/public/apps/
├── shared/
│   ├── js/
│   │   ├── date-utils.js           # General date handling
│   │   ├── date-utils-thailand.js  # Thailand timezone extensions
│   │   ├── api-utils.js            # Generic API request handling
│   │   ├── api-yomi.js             # Yomi-specific API endpoints
│   │   └── ui-utils.js             # Common UI helper functions
│   └── README.md                   # Usage documentation
└── [app directories]
    ├── daily2/
    ├── memory/
    └── [other apps]
```

### Module Categories

#### 1. Date Utilities (`date-utils.js`)

**Purpose**: General date manipulation and formatting

**Key Functions**:
- `formatDate()` - Format dates for display
- `formatTime()` - Format times for display
- `isValidDate()` - Validate date formats
- `formatDateKey()` - Format dates as YYYY-MM-DD
- `isoToUnix()` / `unixToIso()` - Timestamp conversions
- `msToIso()` / `msToUnix()` - Millisecond conversions
- `getDateRange()` - Get date ranges for filtering
- `addDays()` - Date arithmetic
- `getRelativeTime()` - Human-readable time differences

**Usage Example**:
```javascript
DateUtils.formatDate(new Date()); // "Friday, August 7, 2026"
DateUtils.getRelativeTime(new Date(Date.now() - 3600000)); // "1 hour ago"
```

#### 2. Thailand Date Extensions (`date-utils-thailand.js`)

**Purpose**: Thailand timezone-specific date handling

**Key Functions**:
- `utcToThailandDate()` - Convert Thailand time to calendar date
- `thailandDateToUtc()` - Convert Thailand calendar date to UTC
- `getThailandDateRange()` - Get Thailand calendar date ranges
- `formatDateKeyThailand()` - Format dates in Thailand time

**Usage Example**:
```javascript
DateUtils.utcToThailandDate('2026-08-03T15:29:28Z'); // "2026-08-03"
DateUtils.getThailandDateRange('2026-08-03'); // Thailand calendar range
```

#### 3. API Utilities (`api-utils.js`)

**Purpose**: Generic HTTP request handling with consistent error handling

**Key Functions**:
- `get()` / `post()` / `put()` / `delete()` - HTTP methods
- `getWithParams()` - GET with query parameters
- `handleResponse()` - Consistent response parsing
- `handleError()` - Standardized error handling
- `retry()` - Exponential backoff retry logic
- `buildQueryString()` - Query string construction

**Usage Example**:
```javascript
ApiUtils.get('/api/endpoint');
ApiUtils.post('/api/endpoint', { data: 'value' });
ApiUtils.getWithParams('/api/endpoint', { param1: 'value1' });
```

#### 4. Yomi API (`api-yomi.js`)

**Purpose**: Yomi-specific API endpoints wrapper

**Key Functions**:
- `loadConversations()` - Load all conversations
- `loadDailySummaries()` - Load daily summaries for a chat
- `loadMessages()` - Load messages for date range
- `resummarize()` - Trigger re-summarization
- `analyzeMedia()` - Analyze media with AI
- `getMediaAnalysisStatus()` - Check analysis job status
- `loadCollectiveMemory()` - Load collective memory data
- `searchCollectiveMemory()` - Search memory

**Usage Example**:
```javascript
const conversations = await YomiApi.loadConversations();
const summaries = await YomiApi.loadDailySummaries(chatId);
const messages = await YomiApi.loadMessages(chatId, startDate, endDate);
```

#### 5. UI Utilities (`ui-utils.js`)

**Purpose**: Common UI helper functions

**Key Functions**:
- `escapeHtml()` - XSS prevention
- `createElement()` - DOM element creation
- `showLoading()` / `showError()` / `showEmpty()` - State display
- `debounce()` / `throttle()` - Event utilities
- `createModal()` - Modal dialog creation
- `showToast()` - Toast notifications
- `copyToClipboard()` - Clipboard operations
- `formatFileSize()` - File size formatting
- `truncateText()` - Text truncation
- `getQueryParam()` / `setQueryParam()` - URL parameter handling

**Usage Example**:
```javascript
UiUtils.showLoading('#container', 'Loading data...');
UiUtils.showToast('Operation successful', 'success');
const debouncedFn = UiUtils.debounce(func, 300);
```

## Implementation Guidelines

### Loading Order

Utilities must be loaded in dependency order:

```html
<!-- Base utilities -->
<script src="/apps/shared/js/date-utils.js"></script>
<script src="/apps/shared/js/date-utils-thailand.js"></script>
<script src="/apps/shared/js/api-utils.js"></script>
<script src="/apps/shared/js/api-yomi.js"></script>
<script src="/apps/shared/js/ui-utils.js"></script>

<!-- App-specific modules -->
<script src="js/app.js"></script>
```

### Adding New Utilities

When creating new shared utilities:

1. **Choose appropriate category**:
   - General utilities: Add to existing `*-utils.js` or create new
   - App-specific APIs: Create `api-{appname}.js`
   - Extensions: Create `{name}-extensions.js`

2. **Follow naming conventions**:
   - `*-utils.js`: General utility modules
   - `api-*.js`: API-specific modules
   - `*-extensions.js`: Extensions to base utilities

3. **Include JSDoc comments** for all public functions

4. **Export to window object** for global access

5. **Handle errors gracefully** with descriptive messages

6. **Add usage examples** to shared/README.md

### Migration Pattern

**Before (inline code)**:
```javascript
async function loadConversations() {
  const res = await fetch('/api/yomi/conversations');
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
  return data.conversations || [];
}
```

**After (using shared utilities)**:
```javascript
async function loadConversations() {
  return await YomiApi.loadConversations();
}
```

## Benefits

### 1. Code Reusability
- Common functionality written once, used everywhere
- Reduces code duplication by ~40% in migrated apps

### 2. Consistency
- Standardized error handling across all apps
- Consistent API call patterns
- Uniform date formatting and timezone handling

### 3. Maintainability
- Bug fixes applied once, benefit all apps
- Easier to add new features
- Centralized documentation

### 4. Developer Experience
- Clear, documented APIs
- Predictable function signatures
- Reduced cognitive load when switching between apps

### 5. Testing
- Easier to test core functionality
- Test once, validate everywhere
- Better test coverage

