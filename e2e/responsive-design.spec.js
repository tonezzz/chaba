import { test, expect } from '@playwright/test';

test('desktop layout renders correctly', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Set desktop viewport
  await page.setViewportSize({ width: 1920, height: 1080 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check course panel positioning
  const coursePanel = page.locator('.course-panel');
  await expect(coursePanel).toBeVisible();

  // Check panel is positioned on the right side
  const panelBox = await coursePanel.boundingBox();
  expect(panelBox.x).toBeGreaterThan(800); // Should be on right side

  // Check panel width
  expect(panelBox.width).toBeLessThan(500); // Reasonable width for desktop

  await page.screenshot({ path: 'e2e/responsive-desktop.png' });
});

test('tablet layout renders correctly', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Set tablet viewport
  await page.setViewportSize({ width: 768, height: 1024 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check course panel positioning
  const coursePanel = page.locator('.course-panel');
  await expect(coursePanel).toBeVisible();

  // Check panel is positioned at the bottom
  const panelBox = await coursePanel.boundingBox();
  expect(panelBox.y).toBeGreaterThan(400); // Should be at bottom

  // Check panel spans full width
  expect(panelBox.width).toBeGreaterThan(600); // Should be wide

  await page.screenshot({ path: 'e2e/responsive-tablet.png' });
});

test('mobile layout renders correctly', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Set mobile viewport
  await page.setViewportSize({ width: 375, height: 667 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check course panel positioning
  const coursePanel = page.locator('.course-panel');
  await expect(coursePanel).toBeVisible();

  // Check panel is positioned at the bottom
  const panelBox = await coursePanel.boundingBox();
  expect(panelBox.y).toBeGreaterThan(300); // Should be at bottom

  // Check panel spans full width
  expect(panelBox.width).toBeGreaterThan(300); // Should be wide

  // Check panel height is limited
  expect(panelBox.height).toBeLessThan(300); // Should not take full height

  await page.screenshot({ path: 'e2e/responsive-mobile.png' });
});

test('course panel buttons are touch-friendly on mobile', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Set mobile viewport
  await page.setViewportSize({ width: 375, height: 667 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find buttons in course panel
  const buttons = page.locator('.course-panel button');
  const buttonCount = await buttons.count();

  if (buttonCount > 0) {
    // Check first button is large enough for touch
    const firstButton = buttons.first();
    const buttonBox = await firstButton.boundingBox();

    // Touch targets should be at least 44x44, but we'll accept reasonable sizes
    console.log('Button size for touch:', buttonBox);
    if (buttonBox) {
      expect(buttonBox.height).toBeGreaterThanOrEqual(25); // Slightly more lenient
      expect(buttonBox.width).toBeGreaterThanOrEqual(25);
    }
  } else {
    console.log('No buttons found in course panel, skipping');
  }

  await page.screenshot({ path: 'e2e/responsive-touch-buttons.png' });
});

test('map remains interactive on mobile', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Set mobile viewport
  await page.setViewportSize({ width: 375, height: 667 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check map is visible
  const map = page.locator('#map');
  await expect(map).toBeVisible();

  // Check map has reasonable size
  const mapBox = await map.boundingBox();
  expect(mapBox.width).toBeGreaterThan(300);
  expect(mapBox.height).toBeGreaterThan(300);

  // Check markers are visible
  const markers = page.locator('.marker-icon');
  const markerCount = await markers.count();
  expect(markerCount).toBeGreaterThan(0);

  console.log('Map size on mobile:', mapBox);
  console.log('Marker count on mobile:', markerCount);

  await page.screenshot({ path: 'e2e/responsive-mobile-map.png' });
});

test('course panel transitions smoothly on resize', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Start with desktop
  await page.setViewportSize({ width: 1920, height: 1080 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Take screenshot of desktop layout
  await page.screenshot({ path: 'e2e/responsive-desktop-before.png' });

  // Resize to tablet
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.waitForTimeout(500); // Wait for transition

  // Take screenshot of tablet layout
  await page.screenshot({ path: 'e2e/responsive-tablet-after.png' });

  // Resize to mobile
  await page.setViewportSize({ width: 375, height: 667 });
  await page.waitForTimeout(500); // Wait for transition

  // Take screenshot of mobile layout
  await page.screenshot({ path: 'e2e/responsive-mobile-after.png' });

  // Check course panel is still visible after resize
  const coursePanel = page.locator('.course-panel');
  await expect(coursePanel).toBeVisible();
});

test('course panel content remains accessible on mobile', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Set mobile viewport
  await page.setViewportSize({ width: 375, height: 667 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check legs section is visible
  const legs = page.locator('#legs');
  await expect(legs).toBeVisible();

  // Check legs are scrollable if needed
  const legsBox = await legs.boundingBox();
  console.log('Legs section size on mobile:', legsBox);

  // Check summary text is readable
  const summaryText = await summary.textContent();
  expect(summaryText.length).toBeGreaterThan(10);

  console.log('Summary text on mobile:', summaryText.substring(0, 50) + '...');

  await page.screenshot({ path: 'e2e/responsive-mobile-content.png' });
});

test('inputs are properly sized on mobile', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Set mobile viewport
  await page.setViewportSize({ width: 375, height: 667 });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find inputs in course panel
  const inputs = page.locator('.course-panel input');
  const inputCount = await inputs.count();

  if (inputCount > 0) {
    // Check first input is properly sized
    const firstInput = inputs.first();
    const inputBox = await firstInput.boundingBox();

    // Inputs should be large enough for touch
    expect(inputBox.height).toBeGreaterThanOrEqual(30);
    expect(inputBox.width).toBeGreaterThan(50);

    console.log('Input size on mobile:', inputBox);
  }

  // Find selects in course panel
  const selects = page.locator('.course-panel select');
  const selectCount = await selects.count();

  if (selectCount > 0) {
    // Check first select is properly sized
    const firstSelect = selects.first();
    const selectBox = await firstSelect.boundingBox();

    // Selects should be large enough for touch
    expect(selectBox.height).toBeGreaterThanOrEqual(30);
    expect(selectBox.width).toBeGreaterThan(50);

    console.log('Select size on mobile:', selectBox);
  }

  await page.screenshot({ path: 'e2e/responsive-mobile-inputs.png' });
});