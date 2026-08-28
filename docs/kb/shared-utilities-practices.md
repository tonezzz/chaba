---
category: operations
---

# Migration Status

### Completed
- ✅ Created shared utilities infrastructure
- ✅ Migrated daily2 app to use shared utilities
- ✅ Migrated memory app to use shared utilities
- ✅ Migrated daily app to use shared utilities
- ✅ Migrated chat.html to use shared utilities
- ✅ Migrated index.html to use shared utilities
- ✅ Removed duplicate date-utils.js files
- ✅ Updated SSOT documentation
- ✅ Added TypeScript definitions for all utilities
- ✅ Created unit test framework and date utilities tests
- ✅ Tested all migrated apps with playlive.local MCP server

### Future Work
- ⏳ Extend unit test coverage to api-utils, ui-utils
- ⏳ Add integration tests for YomiApi methods
- ⏳ Consider minification/bundling for production
- ⏳ Add JSDoc comments for better IDE support

## Best Practices

### 1. Error Handling
Always use shared utilities for API calls to ensure consistent error handling:

```javascript
// Good
try {
  const data = await YomiApi.loadConversations();
} catch (error) {
  console.error('Failed to load conversations:', error);
}

// Avoid
try {
  const res = await fetch('/api/yomi/conversations');
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const data = await res.json();
} catch (error) {
  console.error('Failed:', error);
}
```

### 2. Date Handling
Use Thailand date utilities for Yomi apps to ensure timezone consistency:

```javascript
// Good
const thailandDate = DateUtils.utcToThailandDate(isoTimestamp);

// Avoid
const localDate = new Date(isoTimestamp).toLocaleDateString();
```

### 3. UI Safety
Always escape user-generated content:

```javascript
// Good
element.innerHTML = UiUtils.escapeHtml(userInput);

// Avoid
element.innerHTML = userInput; // XSS vulnerability
```

### 4. Event Handling
Use debounce/throttle for performance:

```javascript
// Good
const debouncedSearch = UiUtils.debounce(searchFunction, 300);
input.addEventListener('input', debouncedSearch);

// Avoid
input.addEventListener('input', searchFunction); // No debouncing
```

## Performance Considerations

### Caching
- Shared utilities are loaded once per page load
- Browser caching handles subsequent loads
- Version parameters (`?v=1`) for cache busting

### Bundle Size
- Individual utilities are small (<10KB each)
- Total shared utilities: ~30KB minified
- Lazy loading possible for large utilities

### Load Order
- Critical utilities loaded first
- App-specific modules loaded after
- No circular dependencies

## Documentation

### Internal Documentation
- `shared/README.md` - Usage guide and examples
- JSDoc comments in source files
- This document for architectural decisions

### External Documentation
- `ssot.libs.yml` - Updated with shared utilities reference
- KB entries for specific patterns (Thailand timezone, API patterns)

