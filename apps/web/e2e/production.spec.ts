import { test, expect } from '@playwright/test';
for (const route of ['/dev/ui', '/dev/motion'])
  test(`production excludes ${route}`, async ({ page }) => {
    await page.goto(route);
    await expect(
      page.getByRole('heading', { name: 'Page not found' }),
    ).toBeVisible();
    await expect(
      page.getByText('LOCAL SIMULATION', { exact: true }),
    ).toHaveCount(0);
  });
