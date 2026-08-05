import { test, expect } from '@playwright/test';

test('initial page load performance', async ({ page }) => {
  // Start performance measurement
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Get performance metrics
  const performanceMetrics = await page.evaluate(() => {
    const navigation = performance.getEntriesByType('navigation')[0];
    return {
      domContentLoaded: navigation.domContentLoadedEventEnd - navigation.domContentLoadedEventStart,
      loadComplete: navigation.loadEventEnd - navigation.loadEventStart,
      totalLoadTime: navigation.loadEventEnd - navigation.fetchStart,
      domInteractive: navigation.domInteractive - navigation.fetchStart,
      firstPaint: performance.getEntriesByName('first-paint')[0]?.startTime || 0,
      firstContentfulPaint: performance.getEntriesByName('first-contentful-paint')[0]?.startTime || 0
    };
  });

  console.log('Page load performance metrics:', performanceMetrics);

  // Performance thresholds (in milliseconds)
  expect(performanceMetrics.domContentLoaded).toBeLessThan(2000); // DOM content loaded in < 2s
  expect(performanceMetrics.totalLoadTime).toBeLessThan(5000); // Total load time < 5s
  expect(performanceMetrics.domInteractive).toBeLessThan(3000); // DOM interactive in < 3s
});

test('course rendering performance', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Measure course rendering time
  const renderStartTime = Date.now();
  
  const summary = page.locator('#summary');
  await summary.waitFor({ state: 'visible', timeout: 15000 });
  const summaryText = await summary.textContent();
  expect(summaryText).not.toBe('Loading...');
  
  const renderEndTime = Date.now();
  const renderTime = renderEndTime - renderStartTime;

  console.log('Course rendering time:', renderTime, 'ms');

  // Course should render in reasonable time
  expect(renderTime).toBeLessThan(5000); // Course rendering < 5s

  // Check that markers are rendered
  const markers = page.locator('.marker-icon');
  const markerCount = await markers.count();
  console.log('Markers rendered:', markerCount);
  expect(markerCount).toBeGreaterThan(0);
});

test('responsive design performance - mobile', async ({ page }) => {
  // Set mobile viewport
  await page.setViewportSize({ width: 375, height: 667 });

  const loadStartTime = Date.now();
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });
  const loadEndTime = Date.now();

  const mobileLoadTime = loadEndTime - loadStartTime;
  console.log('Mobile load time:', mobileLoadTime, 'ms');

  // Mobile should load in reasonable time
  expect(mobileLoadTime).toBeLessThan(3000); // Mobile load < 3s

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await summary.waitFor({ state: 'visible', timeout: 15000 });
  const summaryText = await summary.textContent();
  expect(summaryText).not.toBe('Loading...');

  // Check mobile rendering performance
  const renderStartTime = Date.now();
  const coursePanel = page.locator('.course-panel');
  await expect(coursePanel).toBeVisible();
  const renderEndTime = Date.now();

  const mobileRenderTime = renderEndTime - renderStartTime;
  console.log('Mobile render time:', mobileRenderTime, 'ms');

  expect(mobileRenderTime).toBeLessThan(2000); // Mobile render < 2s
});

test('responsive design performance - desktop', async ({ page }) => {
  // Set desktop viewport
  await page.setViewportSize({ width: 1920, height: 1080 });

  const loadStartTime = Date.now();
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });
  const loadEndTime = Date.now();

  const desktopLoadTime = loadEndTime - loadStartTime;
  console.log('Desktop load time:', desktopLoadTime, 'ms');

  // Desktop should load quickly
  expect(desktopLoadTime).toBeLessThan(2000); // Desktop load < 2s

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await summary.waitFor({ state: 'visible', timeout: 15000 });
  const summaryText = await summary.textContent();
  expect(summaryText).not.toBe('Loading...');

  // Check desktop rendering performance
  const renderStartTime = Date.now();
  const coursePanel = page.locator('.course-panel');
  await expect(coursePanel).toBeVisible();
  const renderEndTime = Date.now();

  const desktopRenderTime = renderEndTime - renderStartTime;
  console.log('Desktop render time:', desktopRenderTime, 'ms');

  expect(desktopRenderTime).toBeLessThan(1000); // Desktop render < 1s
});

test('memory usage monitoring', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await summary.waitFor({ state: 'visible', timeout: 15000 });
  const summaryText = await summary.textContent();
  expect(summaryText).not.toBe('Loading...');

  // Get memory usage
  const memoryMetrics = await page.evaluate(() => {
    if (performance.memory) {
      return {
        usedJSHeapSize: performance.memory.usedJSHeapSize,
        totalJSHeapSize: performance.memory.totalJSHeapSize,
        jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
        memoryUsagePercent: (performance.memory.usedJSHeapSize / performance.memory.jsHeapSizeLimit) * 100
      };
    }
    return null;
  });

  if (memoryMetrics) {
    console.log('Memory usage metrics:', memoryMetrics);

    // Memory usage should be reasonable (< 80% of limit)
    expect(memoryMetrics.memoryUsagePercent).toBeLessThan(80);
  } else {
    console.log('Memory API not available in this browser');
  }
});

test('animation performance', async ({ page }) => {
  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await summary.waitFor({ state: 'visible', timeout: 15000 });
  const summaryText = await summary.textContent();
  expect(summaryText).not.toBe('Loading...');

  // Measure animation frame rate
  const frameRate = await page.evaluate(() => {
    return new Promise((resolve) => {
      let frames = 0;
      let startTime = performance.now();
      
      function countFrames() {
        frames++;
        if (performance.now() - startTime >= 1000) {
          resolve(frames);
        } else {
          requestAnimationFrame(countFrames);
        }
      }
      
      requestAnimationFrame(countFrames);
    });
  });

  console.log('Animation frame rate:', frameRate, 'fps');

  // Should maintain reasonable frame rate (> 30fps)
  expect(frameRate).toBeGreaterThan(30);
});

test('network request performance', async ({ page }) => {
  // Monitor network requests
  const requests = [];
  page.on('request', request => {
    requests.push({
      url: request.url(),
      method: request.method(),
      resourceType: request.resourceType()
    });
  });

  await page.goto('/apps/raceman/', { waitUntil: 'domcontentloaded' });

  // Activate the COURSE tab
  await page.click('#tab-course');

  // Wait for course to load
  const summary = page.locator('#summary');
  await summary.waitFor({ state: 'visible', timeout: 15000 });
  const summaryText = await summary.textContent();
  expect(summaryText).not.toBe('Loading...');

  console.log('Total network requests:', requests.length);
  console.log('Resource types:', requests.map(r => r.resourceType));

  // Check for excessive requests
  expect(requests.length).toBeLessThan(50); // Should not make excessive requests

  // Check for critical resources
  const hasCourseData = requests.some(r => r.url.includes('.yml') || r.url.includes('course'));
  console.log('Has course data request:', hasCourseData);
});