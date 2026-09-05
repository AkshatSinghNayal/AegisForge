import { test, expect } from '@playwright/test';
test('health root and keyboard refresh reflect dependency failure', async ({
  page,
}) => {
  let available = true;
  await page.route('**/health/ready', (route) =>
    route.fulfill({
      status: available ? 200 : 503,
      json: { status: available ? 'ready' : 'unavailable' },
    }),
  );
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Service health' }),
  ).toBeVisible();
  await expect(page.getByRole('status')).toHaveText(
    'API, PostgreSQL and Redis are ready.',
  );
  available = false;
  await page.keyboard.press('Tab');
  await expect(
    page.getByRole('button', { name: 'Refresh status' }),
  ).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status')).toHaveText(
    'API or dependencies unavailable.',
  );
});
