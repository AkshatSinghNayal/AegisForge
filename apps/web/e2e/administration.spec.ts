import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const org = '10000000-0000-4000-8000-000000000001';
const id = '20000000-0000-4000-8000-000000000001';
test('administration controls, bounded status, report retry and audit export', async ({
  page,
}, testInfo) => {
  let controls = {
    disabled_policy_ids: [],
    scans_enabled: true,
    active_scans_enabled: true,
    concurrency: 3,
    target_concurrency: 1,
    daily_quota: 100,
    report_retention_days: 30,
    raw_retention_days: 7,
    allow_networks: [],
    deny_networks: [],
  };
  let retried = false;
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
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
    else if (path.endsWith('/admin/controls')) {
      if (route.request().method() === 'PUT')
        controls = route.request().postDataJSON();
      body = controls;
    } else if (path.endsWith('/admin/system'))
      body = {
        api: 'ready',
        database: 'ready',
        redis: 'ready',
        worker: 'unavailable',
        scanner: 'configured_unverified',
        storage: 'directory_present',
        ai_provider: 'disabled',
        emergency_stop: false,
        active_scans_enabled: true,
      };
    else if (path.endsWith('/admin/jobs'))
      body = [
        {
          id,
          kind: 'report',
          state: 'failed',
          retry: 'regenerate_report',
          created_at: '2026-10-09T00:00:00Z',
        },
      ];
    else if (path.endsWith('/retry')) {
      retried = true;
      body = { message: 'Report queued.' };
    } else if (path.endsWith('/admin/audit'))
      body = [
        {
          id,
          organization_id: org,
          actor_id: id,
          action: 'administration.updated',
          resource_type: 'organization',
          resource_id: org,
          request_id: id,
          timestamp: '2026-10-09T00:00:00Z',
          result: 'success',
          source_ip: null,
          changed_fields: ['scans_enabled'],
        },
      ];
    await route.fulfill({ json: body });
  });
  await page.goto(`/app/admin?organization=${org}`);
  await expect(
    page.getByRole('heading', { name: 'Administration', exact: true }),
  ).toBeVisible();
  await page.getByLabel('scans enabled', { exact: true }).uncheck();
  await page.getByRole('button', { name: 'Save controls' }).click();
  await expect(page.getByRole('status')).toContainText('Controls saved');
  expect(controls.scans_enabled).toBe(false);
  await page.getByRole('button', { name: 'Retry report' }).click();
  expect(retried).toBe(true);
  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement)?.blur();
      window.scrollTo(0, 0);
    });
    await page.screenshot({
      path: testInfo.outputPath(`administration-${width}.png`),
      fullPage: true,
    });
  }
  await page.goto(`/app/audit-log?organization=${org}`);
  await expect(
    page.getByText('administration.updated', { exact: true }),
  ).toBeVisible();
  const download = page.waitForEvent('download');
  await page
    .getByRole('button', { name: 'Export displayed records (JSON)' })
    .click();
  expect((await download).suggestedFilename()).toBe(
    'aegisforge-audit-page.json',
  );
});
