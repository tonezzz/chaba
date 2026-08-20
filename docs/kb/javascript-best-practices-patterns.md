---
category: operations
---

# Implementation/Architecture

### Async Function Pattern in Event Handlers

When dealing with async operations in event handlers, ensure the handler functions are marked as `async` and the async operations are properly awaited. This prevents race conditions and ensures proper execution order.

#### Problem: Race Conditions

```javascript
// ❌ INCORRECT: Not async, no await
document.getElementById('search-btn').addEventListener('click', () => {
  const results = searchLocation(query); // Returns Promise, not awaited
  displayResults(results); // Undefined or Promise object
});
```

#### Solution: Async Event Handlers

```javascript
// ✅ CORRECT: Async handler with proper await
document.getElementById('search-btn').addEventListener('click', async () => {
  const results = await searchLocation(query); // Properly awaited
  displayResults(results); // Actual results
});
```

#### Best Practices

1. **Mark Event Handlers as Async**: Always use `async` keyword for event handlers that perform async operations
2. **Await Async Operations**: Use `await` for all async function calls
3. **Error Handling**: Wrap async operations in try-catch blocks
4. **Loading States**: Show loading indicators during async operations

```javascript
document.getElementById('search-btn').addEventListener('click', async () => {
  try {
    showLoading();
    const results = await searchLocation(query);
    displayResults(results);
  } catch (error) {
    showError(error.message);
  } finally {
    hideLoading();
  }
});
```

### Function Export Best Practices

When multiple JavaScript modules have similar functions, use descriptive names to avoid conflicts. Export functions at the end of the file in both window object and module.exports for maximum compatibility.

#### Problem: Function Name Conflicts

```javascript
// ❌ INCORRECT: Generic function names cause conflicts
// map-module.js
function searchLocation(query) {
  // Map-specific search logic
}

// route-input-module.js
function searchLocation(query) {
  // Route-specific search logic
}

// Both loaded in same page - which one gets called?
```

#### Solution: Descriptive Function Names

```javascript
// ✅ CORRECT: Descriptive names prevent conflicts
// map-module.js
function searchLocationForMap(query) {
  // Map-specific search logic
}

// route-input-module.js
function searchLocationForRoute(query) {
  // Route-specific search logic
}
```

#### Dual Export Pattern

Export functions at the end of the file in both window object and module.exports for maximum compatibility:

```javascript
// Function definition
function searchLocationForRoute(query) {
  // Implementation
}

// Dual export at end of file
if (typeof window !== 'undefined') {
  window.searchLocationForRoute = searchLocationForRoute;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    searchLocationForRoute
  };
}
```

#### Benefits of Dual Export

1. **Browser Compatibility**: Window object export for direct browser usage
2. **Module System Compatibility**: module.exports for CommonJS/Node.js
3. **Flexibility**: Works in both environments without changes
4. **Testing**: Easier to test functions in isolation

## Operational Procedures

### Implementing Async Event Handlers

1. **Identify Async Operations**: Find event handlers that call async functions
2. **Add Async Keyword**: Mark event handler functions as `async`
3. **Await Calls**: Use `await` for all async function calls
4. **Add Error Handling**: Wrap in try-catch blocks
5. **Add Loading States**: Show/hide loading indicators

### Implementing Function Exports

1. **Use Descriptive Names**: Name functions based on their specific purpose
2. **Avoid Generic Names**: Don't use names like `search`, `load`, `save`
3. **Use Prefixes**: Consider module prefixes (e.g., `mapSearch`, `routeSearch`)
4. **Dual Export**: Export to both window and module.exports
5. **Document Exports**: Add JSDoc comments for exported functions

## Troubleshooting

### Issue: Race Conditions in Event Handlers

**Symptoms**:
- Code executes before async operations complete
- Undefined values from async functions
- Intermittent failures

**Causes**:
- Event handlers not marked as async
- Async operations not awaited
- Missing error handling

**Solutions**:
1. Add `async` keyword to event handler
2. Use `await` for async operations
3. Add try-catch for error handling
4. Add loading states to prevent double-submission

### Issue: Function Name Conflicts

**Symptoms**:
- Wrong function being called
- Unexpected behavior
- Functions not executing

**Causes**:
- Generic function names across modules
- Multiple modules loaded in same page
- Namespace pollution

**Solutions**:
1. Use descriptive, module-specific function names
2. Consider module prefixes
3. Use objects to namespace functions
4. Check for conflicts before deployment

### Issue: Module Export Failures

**Symptoms**:
- Functions not available in other modules
- Import errors
- Undefined function references

**Causes**:
- Missing module.exports
- Incorrect export syntax
- Export before function definition

**Solutions**:
1. Use dual export pattern (window + module.exports)
2. Place exports at end of file
3. Verify export syntax
4. Test imports in different environments

