import { test, expect } from '@playwright/test';

test('loads the app and shows the advisory / no-write banner', async ({ page }) => {
  await page.goto('/');
  const banner = page.getByTestId('safety-boundary-banner');
  await expect(banner).toBeVisible();
  await expect(page.getByText(/NO CONTROL WRITE/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'S3M-WaterTwin' })).toBeVisible();
});
