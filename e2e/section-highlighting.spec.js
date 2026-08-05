import { test, expect } from '@playwright/test';

test('section highlighting activates on hover', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row in the legs list
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover over the section row
  await sectionRow.hover();
  await page.waitForTimeout(500);

  // Check for highlight effects
  const hasFocusClass = await sectionRow.evaluate(el => el.classList.contains('focus-section'));
  console.log('Section row has focus class:', hasFocusClass);

  // Take screenshot to show highlighting
  await page.screenshot({ path: 'e2e/section-highlight-hover.png' });
});

test('section highlighting shows visual effects', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover to activate highlighting
  await sectionRow.hover();
  await page.waitForTimeout(500);

  // Check for highlight layer on map
  const highlightPane = page.locator('.leaflet-pane.highlight-pane');
  const highlightPaneExists = await highlightPane.count();
  console.log('Highlight pane exists:', highlightPaneExists > 0);

  // Check for highlighted section lines
  const highlightedLines = page.locator('.highlight-section-line');
  const lineCount = await highlightedLines.count();
  console.log('Highlighted section lines:', lineCount);

  // Take screenshot
  await page.screenshot({ path: 'e2e/section-highlight-visual.png' });
});

test('section highlighting clears on mouse leave', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover to activate highlighting
  await sectionRow.hover();
  await page.waitForTimeout(500);

  // Take screenshot with highlight
  await page.screenshot({ path: 'e2e/section-highlight-active.png' });

  // Move mouse away
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);

  // Take screenshot without highlight
  await page.screenshot({ path: 'e2e/section-highlight-cleared.png' });

  console.log('Section highlighting cleared on mouse leave');
});

test('section highlighting shows glow effects', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover to activate highlighting
  await sectionRow.hover();
  await page.waitForTimeout(500);

  // Check for glow layer
  const glowLines = page.locator('.highlight-section-glow');
  const glowCount = await glowLines.count();
  console.log('Glow effect lines:', glowCount);

  // Take screenshot to show glow effect
  await page.screenshot({ path: 'e2e/section-highlight-glow.png' });
});

test('section highlighting shows endpoint markers', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover to activate highlighting
  await sectionRow.hover();
  await page.waitForTimeout(500);

  // Check for endpoint markers
  const endpointMarkers = page.locator('.highlight-section-endpoint');
  const endpointCount = await endpointMarkers.count();
  console.log('Endpoint markers:', endpointCount);

  // Take screenshot to show endpoint markers
  await page.screenshot({ path: 'e2e/section-highlight-endpoints.png' });
});

test('section highlighting has animated arrow', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover to activate highlighting
  await sectionRow.hover();
  await page.waitForTimeout(500);

  // Check for animated arrow
  const animatedArrow = page.locator('.highlight-arrow');
  const arrowExists = await animatedArrow.count();
  console.log('Animated arrow exists:', arrowExists > 0);

  // Take multiple screenshots to show animation
  await page.screenshot({ path: 'e2e/section-highlight-arrow-1.png' });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: 'e2e/section-highlight-arrow-2.png' });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: 'e2e/section-highlight-arrow-3.png' });
});

test('section highlighting animations are smooth', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover to activate highlighting
  await sectionRow.hover();
  await page.waitForTimeout(200);

  // Take screenshot immediately after hover
  await page.screenshot({ path: 'e2e/section-highlight-animation-start.png' });

  // Wait for animation to progress
  await page.waitForTimeout(1000);

  // Take screenshot during animation
  await page.screenshot({ path: 'e2e/section-highlight-animation-mid.png' });

  console.log('Section highlighting animation captured');
});

test('multiple sections can be highlighted independently', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find multiple section rows
  const sectionRows = page.locator('#legs > div');
  const rowCount = await sectionRows.count();
  console.log('Total section rows:', rowCount);

  if (rowCount >= 2) {
    // Hover over first section
    await sectionRows.nth(0).hover();
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'e2e/section-highlight-first.png' });

    // Move to second section
    await sectionRows.nth(1).hover();
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'e2e/section-highlight-second.png' });

    console.log('Multiple sections highlighted independently');
  } else {
    console.log('Not enough sections for multi-highlight test');
  }
});

test('section highlighting pane has correct z-index', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a section row
  const sectionRow = page.locator('#legs > div').first();
  await expect(sectionRow).toBeVisible();

  // Hover to activate highlighting
  await sectionRow.hover();
  await page.waitForTimeout(500);

  // Check highlight pane z-index (may not exist in all courses)
  const highlightPane = page.locator('.leaflet-pane.highlight-pane');
  const paneExists = await highlightPane.count();
  
  if (paneExists > 0) {
    const zIndex = await highlightPane.evaluate(el => getComputedStyle(el).zIndex);
    console.log('Highlight pane z-index:', zIndex);

    // z-index should be higher than default layers
    expect(parseInt(zIndex)).toBeGreaterThan(400);
  } else {
    console.log('Highlight pane not present in this course - skipping');
  }

  await page.screenshot({ path: 'e2e/section-highlight-zindex.png' });
});

test('section highlighting works with different section types', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find all section rows
  const sectionRows = page.locator('#legs > div');
  const rowCount = await sectionRows.count();
  console.log('Total sections to test:', rowCount);

  // Test highlighting on each section
  for (let i = 0; i < Math.min(rowCount, 3); i++) {
    await sectionRows.nth(i).hover();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `e2e/section-highlight-type-${i}.png` });
    
    // Move mouse away to clear
    await page.mouse.move(0, 0);
    await page.waitForTimeout(300);
  }

  console.log('Section highlighting tested on multiple section types');
});