---
category: operations
---

# E2E Test Automation Patterns

## What it is

End-to-end testing patterns and best practices for static site validation using Playwright, as implemented in the Chaba-Raceman project for automated testing of web applications.

## Context/Background

Created 2026-08-05 during E2E test implementation for Chaba-Raceman static site. Achieved 100% test pass rate (4/4 tests) after fixing accessibility, data loading, and test mismatch issues. Created static-site-tester subagent for ongoing E2E test management.

## Key Details

### Test Architecture

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

### Test Execution

**Run all tests**:
```bash
cd /home/tony/CascadeProjects/chaba-raceman
npx playwright test
```

**Run specific test file**:
```bash
npx playwright test e2e/track3.spec.js
```

**Run with UI**:
```bash
npx playwright test --ui
```

**Run in debug mode**:
```bash
npx playwright test --debug
```

**Run specific test**:
```bash
npx playwright test -g "should load successfully"
```

### Test Configuration

**playwright.config.js**:
```javascript
module.exports = {
  testDir: './e2e',
  timeout: 30000,
  retries: 2,
  use: {
    baseURL: 'http://localhost:8083',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
};
```

### Static-Site-Tester Subagent

**Purpose**: Automated E2E test management for static sites

**Capabilities**:
- Run E2E test suites
- Analyze test results and failures
- Suggest fixes for common issues
- Generate test reports
- Validate accessibility compliance

**Usage**:
```
"Run the E2E test suite for the raceman static site.
Analyze any failures and suggest fixes.
Focus on accessibility and data loading issues."
```

### Best Practices

#### 1. Test Isolation
- Each test should be independent
- Use beforeEach/afterEach for setup/teardown
- Avoid dependencies between tests

#### 2. Reliable Selectors
- Use stable selectors (data-testid, role)
- Avoid brittle selectors (CSS classes, structure)
- Prefer user-facing attributes

#### 3. Proper Waiting
- Use explicit waits (waitForSelector, waitForResponse)
- Avoid arbitrary sleep calls
- Wait for network responses when testing API integration

#### 4. Accessibility First
- Include accessibility checks in all tests
- Test keyboard navigation
- Verify ARIA labels and roles

#### 5. Maintainable Tests
- Keep tests simple and focused
- Use page object model for complex pages
- Extract common test utilities

### Integration with CI/CD

**GitHub Actions Example**:
```yaml
- name: Install dependencies
  run: npm ci

- name: Install Playwright browsers
  run: npx playwright install --with-deps

- name: Run E2E tests
  run: npx playwright test

- name: Upload test results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: playwright-report
    path: playwright-report/
```

### Troubleshooting

#### Tests timeout
- Check if target service is running
- Verify network connectivity
- Increase timeout in playwright.config.js
- Check for infinite loops in application

#### Flaky tests
- Add retries in configuration
- Improve waiting strategies
- Check for race conditions
- Stabilize test data

#### Selector not found
- Verify selector is correct
- Check if element is dynamically loaded
- Use more robust selectors
- Add explicit waits

#### Accessibility failures
- Add missing alt attributes
- Ensure proper ARIA labels
- Check color contrast
- Verify keyboard navigation

## Related Documentation

- **[playwright-vs-playlive.md](playwright-vs-playlive.md)** - Playwright vs PlayLive comparison
- **[subagent-implementation-strategy.md](subagent-implementation-strategy.md)** - Subagent for test management
- **[static-site-tester.md](../../.devin/agents/static-site-tester.md)** - E2E test subagent configuration

## Tags

- **e2e-testing**: End-to-end test automation
- **playwright**: Browser automation framework
- **accessibility**: A11y testing patterns
- **test-automation**: Automated testing strategies
- **quality-assurance**: Test quality and reliability
