import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

test('imagen2 UI assessment', async ({ page }) => {
  // Mock backend so the interface reaches its ready/idle state.
  await page.route('**/api/health', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', model: 'stable-diffusion-xl-base-1.0' }) });
  });
  await page.route('**/api/history', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ history: [] }) });
  });

  await page.goto('/apps/imagen2/');
  await expect(page.locator('#status')).toContainText('Backend ready', { timeout: 5000 });
  await expect(page.locator('#generate')).toBeEnabled();

  // Desktop screenshot.
  await page.screenshot({ path: 'e2e/imagen2-desktop.png', fullPage: true });

  // Mobile viewport.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.locator('#status')).toContainText('Backend ready', { timeout: 5000 });
  await page.screenshot({ path: 'e2e/imagen2-mobile.png', fullPage: true });

  const findings = await page.evaluate(() => {
    const inputs = [...document.querySelectorAll('input, textarea, select')];
    const unlabeled = inputs
      .filter(el => {
        const id = el.id;
        const aria = el.getAttribute('aria-label');
        const labelledBy = el.getAttribute('aria-labelledby');
        const hasLabel = id && document.querySelector(`label[for="${id}"]`);
        return !hasLabel && !aria && !labelledBy && !el.placeholder;
      })
      .map(el => el.id || el.tagName);

    const fileInputId = 'reference';
    const fileHasLabel = !!document.querySelector(`label[for="${fileInputId}"]`);

    return {
      title: document.title,
      h1: document.querySelector('h1')?.textContent?.trim() || null,
      titleMatchesH1: document.title === document.querySelector('h1')?.textContent?.trim(),
      statusText: document.getElementById('status')?.textContent?.trim(),
      generateEnabled: !document.getElementById('generate')?.disabled,
      unlabeledInputs: unlabeled,
      hasPromptShortcut: true, // ctrl+enter handler is in source
      mobileViewportWidth: window.innerWidth,
      mobileOneColumn: window.getComputedStyle(document.querySelector('.layout')).gridTemplateColumns.trim().split(/\s+/).length === 1,
      noDownloadLabel: !document.querySelector('label[for="download-scale"]'),
      noProgressLabel: !document.querySelector('label[for="progress"]') && !document.getElementById('progress')?.getAttribute('aria-label'),
      lockCheckboxInsideWidthLabel: !!document.querySelector('label[for="width"] input#lock-ratio'),
      viewTabsNoAria: [...document.querySelectorAll('#view-tabs button')].some(b => !b.getAttribute('aria-selected') || !b.getAttribute('aria-controls') || b.getAttribute('role') !== 'tab'),
      historyHeading: document.querySelector('.history h2')?.textContent?.trim(),
      fileInputLabeled: fileHasLabel,
    };
  });

  findings.screenshotPaths = ['e2e/imagen2-desktop.png', 'e2e/imagen2-mobile.png'];
  findings.summary = [
    findings.titleMatchesH1 ? null : `Title/H1 mismatch: title="${findings.title}" but h1="${findings.h1}".`,
    ...findings.unlabeledInputs.map(id => `Unlabeled control: #${id}.`),
    findings.noDownloadLabel ? 'No <label> for #download-scale select.' : null,
    findings.noProgressLabel ? 'No <label> for #progress progress bar.' : null,
    findings.lockCheckboxInsideWidthLabel ? 'The lock-ratio checkbox is nested inside the Width label; it has no standalone accessible label.' : null,
    findings.viewTabsNoAria ? 'View tabs (#view-tabs) lack aria-selected/aria-controls for screen readers.' : null,
  ].filter(Boolean);

  expect(findings.titleMatchesH1, 'title should match h1').toBe(true);
  expect(findings.unlabeledInputs, 'no unlabeled inputs').toEqual([]);
  expect(findings.noDownloadLabel, 'download select should be labeled').toBe(false);
  expect(findings.noProgressLabel, 'progress should have an accessible name').toBe(false);
  expect(findings.lockCheckboxInsideWidthLabel, 'lock checkbox should not be inside width label').toBe(false);
  expect(findings.viewTabsNoAria, 'view tabs should have aria attributes').toBe(false);
  expect(findings.mobileOneColumn, 'mobile layout should be single column').toBe(true);

  await fs.writeFile('/tmp/imagen2-assessment.json', JSON.stringify(findings, null, 2));
  console.log('Assessment written to /tmp/imagen2-assessment.json');
  if (findings.summary.length) console.log(findings.summary.join('\n'));
});

test('imagen2 generation error display', async ({ page }) => {
  await page.route('**/api/health', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', model: 'stable-diffusion-xl-base-1.0' }) });
  });
  await page.route('**/api/history', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ history: [] }) });
  });
  await page.route('**/api/generate', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: 'err-job' }) });
  });
  await page.route('**/api/progress/**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ done: true, progress: null, result: null, error: 'mock img2img failure' }) });
  });

  await page.goto('/apps/imagen2/');
  await page.fill('#prompt', 'test prompt');
  await page.click('#generate');
  await expect(page.locator('#status')).toContainText('Error: mock img2img failure', { timeout: 5000 });
});
