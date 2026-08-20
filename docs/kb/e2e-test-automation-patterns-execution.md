---
category: operations
---

## Test Execution

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

