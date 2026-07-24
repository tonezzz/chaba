import { test, expect } from '@playwright/test';

test('renders course with legs', async ({ page }) => {
  await page.goto('/apps/track3/', { waitUntil: 'domcontentloaded' });

  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  const legs = page.locator('#legs > div');
  await expect(legs.first()).toBeVisible();

  await page.screenshot({ path: 'e2e/track3-initial.png' });

  console.log('summary text:', await summary.textContent());
  console.log('leg count:', await legs.count());
});

test('tracks dropdown is visible on hover', async ({ page }) => {
  await page.goto('/apps/track3/', { waitUntil: 'domcontentloaded' });
  const summary = page.locator('#summary');
  await expect(summary).not.toHaveText('Loading...', { timeout: 15000 });

  const tracks = page.locator('nav a:has-text("Tracks")');
  await tracks.hover();
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'e2e/track3-nav.png' });
});
