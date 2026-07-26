import { test, expect } from '@playwright/test';

test('renders Reef Riders single-page layout', async ({ page }) => {
  await page.goto('/apps/reefriders/index.html', { waitUntil: 'domcontentloaded' });

  // Wait for the YAML-driven hero to render
  const heroHeading = page.locator('#hero h1');
  await expect(heroHeading).toHaveText('Reef Riders Boracay', { timeout: 15000 });

  // Retained major layout sections from the original wireframe
  const sections = [
    'about',
    'activities',
    'pricing',
    'wind',
    'getting-here',
    'crew',
    'reviews',
    'contact',
  ];

  for (const id of sections) {
    const section = page.locator(`#${id}`);
    await expect(section, `section #${id} should be visible`).toBeVisible();
  }

  // Spot-check key content migrated from the original site
  await expect(page.locator('#about')).toContainText('Bolabog Beach');
  await expect(page.locator('#activities')).toContainText('Windsurfing');
  await expect(page.locator('#pricing')).toContainText('TBD');
  await expect(page.locator('#contact')).toContainText('+63 908 820 2267');

  await page.screenshot({ path: 'e2e/reefriders-layout.png' });
});
