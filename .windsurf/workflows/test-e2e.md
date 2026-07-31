---
description: Run Playwright end-to-end tests with PHP dev server
---
1. If Playwright browsers are missing, run `npx playwright install --with-deps` first.
2. Run `just -f /home/tony/CascadeProjects/chaba-h3/Justfile test-e2e`.
3. The recipe starts the PHP dev server on `0.0.0.0:8123`, waits for it to be ready, runs `npx playwright test`, then tears the server down.
4. Report the test result summary (passed/failed/skipped counts) and the first failing test name if any failed.
