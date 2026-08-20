---
category: operations
---

# Best Practices

### Async Operations

1. **Always Use Async/Await**: Prefer async/await over Promise chains
2. **Handle Errors**: Always include try-catch blocks
3. **Show Loading States**: Provide feedback during async operations
4. **Avoid Nested Async**: Keep async operations flat and sequential
5. **Use Proper Timeouts**: Set reasonable timeouts for async operations

### Function Naming

1. **Be Descriptive**: Use names that describe the function's purpose
2. **Use Verbs**: Start with action verbs (search, load, save, fetch)
3. **Include Context**: Add module context (mapSearch, routeSearch)
4. **Avoid Abbreviations**: Use full words for clarity
5. **Be Consistent**: Follow naming conventions across codebase

### Module Exports

1. **Dual Export**: Export to both window and module.exports
2. **Export at End**: Place exports at end of file
3. **Document Exports**: Add JSDoc comments
4. **Test Exports**: Verify exports work in different environments
5. **Namespace When Needed**: Use objects for related functions

## Code Examples

### Complete Async Event Handler Example

```javascript
// Define async function
async function searchLocationForRoute(query) {
  const response = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}`);
  if (!response.ok) {
    throw new Error('Search failed');
  }
  return await response.json();
}

// Async event handler with error handling
document.getElementById('search-btn').addEventListener('click', async (event) => {
  event.preventDefault();
  
  const query = document.getElementById('search-input').value;
  const loadingIndicator = document.getElementById('loading');
  const resultsContainer = document.getElementById('results');
  
  try {
    loadingIndicator.style.display = 'block';
    resultsContainer.innerHTML = '';
    
    const results = await searchLocationForRoute(query);
    displayResults(results);
  } catch (error) {
    resultsContainer.innerHTML = `<div class="error">Error: ${error.message}</div>`;
  } finally {
    loadingIndicator.style.display = 'none';
  }
});
```

### Complete Function Export Example

```javascript
// Function definitions
function searchLocationForRoute(query) {
  // Implementation
}

function calculateRoute(from, to) {
  // Implementation
}

function displayRoute(route) {
  // Implementation
}

// Dual export at end of file
if (typeof window !== 'undefined') {
  window.searchLocationForRoute = searchLocationForRoute;
  window.calculateRoute = calculateRoute;
  window.displayRoute = displayRoute;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    searchLocationForRoute,
    calculateRoute,
    displayRoute
  };
}
```

