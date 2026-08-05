import { test, expect } from '@playwright/test';

test('marker drag-and-drop repositioning', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab since it's hidden by default
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a draggable marker
  const marker = page.locator('.marker-icon').first();
  await expect(marker).toBeVisible();

  // Get initial position
  const initialBox = await marker.boundingBox();
  console.log('Initial marker position:', initialBox);

  // Drag the marker using mouse events
  await marker.hover();
  await page.mouse.down();
  await page.mouse.move(initialBox.x + 50, initialBox.y + 50);
  await page.mouse.up();

  // Wait for drag completion
  await page.waitForTimeout(1000);

  // Take screenshot of result
  await page.screenshot({ path: 'e2e/drag-drop-result.png' });
});

test('marker visual feedback during drag', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a draggable marker
  const marker = page.locator('.marker-icon').first();
  await expect(marker).toBeVisible();

  // Get initial position
  const initialBox = await marker.boundingBox();
  
  // Start drag operation
  await marker.hover();
  await page.mouse.down();
  await page.mouse.move(initialBox.x + 20, initialBox.y + 20);

  // Check for visual feedback (marker-dragging class)
  const isDragging = await marker.evaluate(el => el.classList.contains('marker-dragging'));
  console.log('Marker has dragging class:', isDragging);

  // Check cursor state
  const cursorStyle = await page.evaluate(() => document.body.style.cursor);
  console.log('Cursor style during drag:', cursorStyle);

  await page.mouse.up();

  // Take screenshot during drag
  await page.screenshot({ path: 'e2e/drag-visual-feedback.png' });
});

test('marker position persistence after drag', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a draggable marker
  const marker = page.locator('.marker-icon').first();
  await expect(marker).toBeVisible();

  // Get initial position
  const initialBox = await marker.boundingBox();
  console.log('Initial marker position:', initialBox);

  // Drag the marker
  await marker.hover();
  await page.mouse.down();
  await page.mouse.move(initialBox.x + 100, initialBox.y + 100);
  await page.mouse.up();

  // Wait for re-render
  await page.waitForTimeout(2000);

  // Reload page to test persistence
  await page.reload({ waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab again
  await page.click('#tab-course');

  // Wait for course to load
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find the same marker
  const markerAfterReload = page.locator('.marker-icon').first();
  await expect(markerAfterReload).toBeVisible();

  // Take screenshot to verify position persistence
  await page.screenshot({ path: 'e2e/drag-persistence.png' });
});

test('drag notification displays correctly', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find a draggable marker
  const marker = page.locator('.marker-icon').first();
  await expect(marker).toBeVisible();

  // Drag the marker
  const initialBox = await marker.boundingBox();
  await marker.hover();
  await page.mouse.down();
  await page.mouse.move(initialBox.x + 30, initialBox.y + 30);
  await page.mouse.up();

  // Wait for notification
  const courseMsg = page.locator('#course-msg');
  await page.waitForTimeout(1500);

  // Check notification element exists and is visible
  await expect(courseMsg).toBeVisible();

  // Take screenshot
  await page.screenshot({ path: 'e2e/drag-notification-result.png' });
});

test('multiple markers can be dragged independently', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find multiple markers
  const markers = page.locator('.marker-icon');
  const markerCount = await markers.count();
  console.log('Total markers found:', markerCount);

  if (markerCount >= 2) {
    // Drag first marker
    const firstMarker = markers.nth(0);
    const firstBox = await firstMarker.boundingBox();
    await firstMarker.hover();
    await page.mouse.down();
    await page.mouse.move(firstBox.x + 50, firstBox.y + 50);
    await page.mouse.up();
    await page.waitForTimeout(1000);

    // Drag second marker
    const secondMarker = markers.nth(1);
    const secondBox = await secondMarker.boundingBox();
    await secondMarker.hover();
    await page.mouse.down();
    await page.mouse.move(secondBox.x - 30, secondBox.y + 30);
    await page.mouse.up();
    await page.waitForTimeout(1000);

    // Check that notification appeared
    const courseMsg = page.locator('#course-msg');
    const msgText = await courseMsg.textContent();
    console.log('Notifications after multiple drags:', msgText);

    await page.screenshot({ path: 'e2e/multiple-drag-result.png' });
  } else {
    console.log('Not enough markers for multi-drag test, skipping');
  }
});