---
category: operations
---

## Test Architecture

**Testing Framework**: Playwright 1.61.1
**Target**: localhost:8083 (raceman container)
**Test Location**: `/home/tony/CascadeProjects/chaba-raceman/e2e/`
**Configuration**: `playwright.config.js`

### Test Structure

**Test Files**:
- `e2e/track3.spec.js` - Track3 page E2E tests
- `e2e/imagen2.spec.js` - Imagen2 page E2E tests
- `e2e/reefriders.spec.js` - Reefriders page E2E tests

**Test Organization**:
```javascript
// Typical test structure
test.describe('Page Name', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:8083/page-name');
  });

  test('should load successfully', async ({ page }) => {
    await expect(page).toHaveTitle(/Page Name/);
  });

  test('should have accessible content', async ({ page }) => {
    // Accessibility checks
  });
});
```

### Common Test Patterns

#### 1. Page Load Validation

**Pattern**: Verify page loads and has correct title
```javascript
test('should load successfully', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  await expect(page).toHaveTitle(/Track3/);
});
```

**Purpose**: Basic smoke test to ensure page is accessible

#### 2. Content Validation

**Pattern**: Verify specific content exists on page
```javascript
test('should display track data', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  const trackElement = page.locator('.track-data');
  await expect(trackElement).toBeVisible();
});
```

**Purpose**: Ensure critical content is rendered

#### 3. Accessibility Testing

**Pattern**: Check for accessibility issues
```javascript
test('should be accessible', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  // Check for proper ARIA labels, alt text, etc.
  const images = page.locator('img');
  const count = await images.count();
  for (let i = 0; i < count; i++) {
    await expect(images.nth(i)).toHaveAttribute('alt');
  }
});
```

**Purpose**: Ensure compliance with accessibility standards

#### 4. Data Loading Validation

**Pattern**: Verify dynamic data loads correctly
```javascript
test('should load track data from API', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  // Wait for data to load
  await page.waitForSelector('.data-loaded');
  const dataElement = page.locator('.track-data');
  await expect(dataElement).not.toBeEmpty();
});
```

**Purpose**: Ensure API integration works correctly

### Test Fix Patterns

#### Issue 1: Accessibility Violations

**Problem**: Missing alt attributes on images
```javascript
// Before fix
<img src="track3-8081.png">

// After fix
<img src="track3-8081.png" alt="Track3 screenshot at port 8081">
```

**Detection**: Playwright accessibility plugin or manual inspection
**Prevention**: Add alt attributes to all images during development

#### Issue 2: Data Loading Failures

**Problem**: Tests fail because data hasn't loaded
```javascript
// Before fix
test('should display data', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  const data = page.locator('.data');
  await expect(data).toBeVisible(); // Fails if data not loaded
});

// After fix
test('should display data', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  await page.waitForSelector('.data-loaded', { timeout: 5000 });
  const data = page.locator('.data');
  await expect(data).toBeVisible();
});
```

**Detection**: Test failures with timeout errors
**Prevention**: Add loading indicators and wait for them

#### Issue 3: Test Mismatches

**Problem**: Test expectations don't match actual implementation
```javascript
// Before fix
test('should have correct title', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  await expect(page).toHaveTitle('Track3 Dashboard'); // Wrong title
});

// After fix
test('should have correct title', async ({ page }) => {
  await page.goto('http://localhost:8083/track3');
  await expect(page).toHaveTitle(/Track3/); // Flexible matching
});
```

**Detection**: Test failures with expectation mismatches
**Prevention**: Keep tests synchronized with implementation changes

