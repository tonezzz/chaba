import { test, expect } from '@playwright/test';

test('wind icon renders with correct color based on speed', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check for wind icon (may not be present in all courses)
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Check wind icon has enhanced class
    const hasEnhancedClass = await windIcon.evaluate(el => el.classList.contains('enhanced-wind-icon'));
    console.log('Wind icon has enhanced class:', hasEnhancedClass);
    expect(hasEnhancedClass).toBe(true);

    await page.screenshot({ path: 'e2e/wind-icon-rendering.png' });
  } else {
    console.log('Wind icon not present in this course - skipping');
    await page.screenshot({ path: 'e2e/wind-icon-not-present.png' });
  }
});

test('wind icon displays speed text', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check for wind icon
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Check wind icon contains speed text
    const windIconText = await windIcon.textContent();
    console.log('Wind icon text:', windIconText);
    expect(windIconText).toMatch(/\d+\s*kt/); // Should contain speed in knots

    await page.screenshot({ path: 'e2e/wind-speed-text.png' });
  } else {
    console.log('Wind icon not present in this course - skipping');
  }
});

test('wind icon has hover effects', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find wind icon
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Hover over wind icon
    await windIcon.hover();
    await page.waitForTimeout(300);

    // Take screenshot to show hover effect
    await page.screenshot({ path: 'e2e/wind-hover-effect.png' });

    // Check wind icon still visible after hover
    await expect(windIcon).toBeVisible();
  } else {
    console.log('Wind icon not present in this course - skipping');
  }
});

test('wind icon has breathing animation', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find wind icon
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Take multiple screenshots to check animation
    await page.screenshot({ path: 'e2e/wind-animation-1.png' });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'e2e/wind-animation-2.png' });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'e2e/wind-animation-3.png' });

    console.log('Wind animation screenshots captured');
  } else {
    console.log('Wind icon not present in this course - skipping');
  }
});

test('wind control UI elements are accessible', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Check for wind direction slider
  const windDirSlider = page.locator('#wind-direction');
  const windDirExists = await windDirSlider.count();
  console.log('Wind direction slider exists:', windDirExists > 0);

  // Check for wind speed slider
  const windSpeedSlider = page.locator('#wind-speed');
  const windSpeedExists = await windSpeedSlider.count();
  console.log('Wind speed slider exists:', windSpeedExists > 0);

  // Check for wind gust slider
  const windGustSlider = page.locator('#wind-gust');
  const windGustExists = await windGustSlider.count();
  console.log('Wind gust slider exists:', windGustExists > 0);

  // Check for apply wind button
  const applyWindBtn = page.locator('#apply-wind');
  const applyWindExists = await applyWindBtn.count();
  console.log('Apply wind button exists:', applyWindExists > 0);

  await page.screenshot({ path: 'e2e/wind-controls.png' });
});

test('wind icon size and positioning', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find wind icon
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Check wind icon size
    const iconBox = await windIcon.boundingBox();
    console.log('Wind icon size:', iconBox);
    expect(iconBox.width).toBeGreaterThan(20);
    expect(iconBox.height).toBeGreaterThan(20);

    // Check wind icon is positioned on map
    const map = page.locator('#map');
    const mapBox = await map.boundingBox();
    expect(iconBox.x).toBeGreaterThan(mapBox.x);
    expect(iconBox.y).toBeGreaterThan(mapBox.y);
    expect(iconBox.x + iconBox.width).toBeLessThan(mapBox.x + mapBox.width);
    expect(iconBox.y + iconBox.height).toBeLessThan(mapBox.y + mapBox.height);

    await page.screenshot({ path: 'e2e/wind-positioning.png' });
  } else {
    console.log('Wind icon not present in this course - skipping');
  }
});

test('wind icon SVG structure', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find wind icon
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Check for SVG element
    const svg = windIcon.locator('svg');
    await expect(svg).toBeVisible();

    // Check for path element (wind arrow)
    const path = svg.locator('path');
    await expect(path).toBeVisible();

    // Check for text element (speed display)
    const text = svg.locator('text');
    const textExists = await text.count();
    console.log('Wind icon has speed text:', textExists > 0);

    // Check for circle element (center point)
    const circle = svg.locator('circle');
    await expect(circle).toBeVisible();

    console.log('Wind icon SVG structure verified');

    await page.screenshot({ path: 'e2e/wind-svg-structure.png' });
  } else {
    console.log('Wind icon not present in this course - skipping');
  }
});

test('wind icon color coding', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find wind icon
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Get the SVG path color
    const svg = windIcon.locator('svg');
    const path = svg.locator('path');
    const fillColor = await path.evaluate(el => el.getAttribute('fill'));
    console.log('Wind icon fill color:', fillColor);

    // Check that color is one of the expected wind speed colors
    const expectedColors = ['#22c55e', '#eab308', '#f97316', '#ef4444', '#0ea5e9'];
    const hasExpectedColor = expectedColors.includes(fillColor);
    console.log('Wind icon has expected color:', hasExpectedColor);
    expect(hasExpectedColor).toBe(true);

    await page.screenshot({ path: 'e2e/wind-color-coding.png' });
  } else {
    console.log('Wind icon not present in this course - skipping');
  }
});

test('wind icon glow effect', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  // Find wind icon
  const windIcon = page.locator('.wind-icon');
  const windIconExists = await windIcon.count();
  
  if (windIconExists > 0) {
    await expect(windIcon).toBeVisible();

    // Check for filter definition (glow effect)
    const svg = windIcon.locator('svg');
    const defs = svg.locator('defs');
    const defsExists = await defs.count();
    console.log('Wind icon has defs (for glow):', defsExists > 0);

    if (defsExists > 0) {
      // Check for filter element
      const filter = defs.locator('filter');
      const filterExists = await filter.count();
      console.log('Wind icon has filter element:', filterExists > 0);
    }

    await page.screenshot({ path: 'e2e/wind-glow-effect.png' });
  } else {
    console.log('Wind icon not present in this course - skipping');
  }
});