import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const org = '10000000-0000-4000-8000-000000000001';
const id = '20000000-0000-4000-8000-000000000001';
test('report, notification and one-time key controls', async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  const writes: string[] = [];
  let failRegistry = false;
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (failRegistry && path.includes('/workspace/')) {
      await route.fulfill({
        status: 503,
        json: {
          error: { code: 'unavailable', message: 'Registry unavailable' },
        },
      });
      return;
    }
    let body: unknown = [];
    if (path.endsWith('/auth/csrf')) body = { csrf_token: 'fixture' };
    else if (path.endsWith('/auth/refresh'))
      body = { access_token: 'fixture', expires_in: 600, token_type: 'Bearer' };
    else if (path.endsWith('/auth/me'))
      body = {
        id,
        email: 'test@example.invalid',
        display_name: 'Reviewer',
        email_verified: true,
        organizations: [{ id: org, name: 'Synthetic org', role: 'owner' }],
      };
    else if (path.includes('/workspace/'))
      body = { items: [], total: 0, page: 1, page_size: 50 };
    else if (route.request().method() === 'POST') {
      writes.push(path);
      if (path.endsWith('/api-keys'))
        body = { secret: 'agf_SYNTHETIC_ONE_TIME' };
      else if (path.endsWith('/reports')) body = { id, version: 1 };
      else if (path.endsWith('/destinations'))
        body = {
          id,
          name: 'Email',
          kind: 'email',
          enabled: true,
          subscriptions: ['scan.failed'],
        };
    }
    await route.fulfill({ json: body });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/app/api-keys?organization=${org}`);
  await page.getByLabel('Name', { exact: true }).fill('CI key');
  await page.getByLabel('Expires at (local time)').fill('2027-01-01T12:00');
  await page.getByLabel('scans:read', { exact: true }).check();
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByLabel('One-time API secret')).toHaveValue(
    'agf_SYNTHETIC_ONE_TIME',
  );
  failRegistry = true;
  await page.getByRole('button', { name: 'Refresh records' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByLabel('One-time API secret')).toHaveValue(
    'agf_SYNTHETIC_ONE_TIME',
  );
  failRegistry = false;
  await page.getByRole('button', { name: 'Dismiss secret' }).click();
  await expect(page.getByLabel('One-time API secret')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText(
    'agf_SYNTHETIC_ONE_TIME',
  );
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.goto(`/app/reports?organization=${org}`);
  await page.getByLabel('Scan ID').fill(id);
  await page.getByRole('button', { name: 'Queue report' }).click();
  await expect(page.getByRole('status')).toContainText('version 1 queued');
  await page.goto(`/app/integrations?organization=${org}`);
  await page.getByLabel('Name', { exact: true }).fill('Email');
  await page
    .getByLabel('Email address or HTTPS endpoint')
    .fill('test@example.invalid');
  await page.getByLabel('scan.failed', { exact: true }).check();
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('destination enabled');
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page
    .getByRole('heading', { name: 'Integrations', exact: true })
    .click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath('notifications-390.png'),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: testInfo.outputPath('notifications-1440.png'),
    fullPage: true,
  });
  for (const kind of ['reports', 'api-keys', 'integrations']) {
    await page.goto(`/app/${kind}?organization=${org}`);
    await expect(page.locator('.delivery-tools')).toBeVisible();
    for (const width of [390, 768, 1280, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.screenshot({
        path: testInfo.outputPath(`${kind}-${width}.png`),
        fullPage: true,
      });
    }
  }
  expect(writes).toEqual([
    '/api/v1/api-keys',
    '/api/v1/reports',
    '/api/v1/notifications/destinations',
  ]);
});
