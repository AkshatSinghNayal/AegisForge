import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const id = '20000000-0000-4000-8000-000000000001';
const org = '10000000-0000-4000-8000-000000000001';
test('GitHub setup, secret dismissal, connection test, delivery history and disable', async ({
  page,
}, testInfo) => {
  let created = false;
  let enabled = true;
  const mapping = () => ({
    id,
    integration_id: id,
    repository: 'owner/repo',
    branch: 'main',
    project_id: id,
    target_id: id,
    policy_id: id,
    target_version: 1,
    policy_version: 1,
    gate_policy_version: 1,
    environment: 'development',
    events: ['push'],
    enabled,
    webhook_path: `/api/hooks/github/${id}`,
  });
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
    else if (path.endsWith('/github/mappings')) {
      if (route.request().method() === 'POST') {
        created = true;
        body = { ...mapping(), secret: 'synthetic-secret-once' };
      } else body = created ? [mapping()] : [];
    } else if (path.endsWith('/test'))
      body = {
        ok: true,
        message: 'Local readiness verified. Send a signed GitHub ping.',
      };
    else if (path.endsWith('/github/deliveries'))
      body = created
        ? [
            {
              id,
              mapping_id: id,
              delivery_id: id,
              event: 'ping',
              state: 'ping',
              scan_id: null,
              created_at: '2026-09-22T12:00:00Z',
            },
          ]
        : [];
    else if (route.request().method() === 'DELETE') {
      enabled = false;
      body = { ok: true };
    } else if (path.includes('/workspace/'))
      body = { items: [], total: 0, page: 1, page_size: 50 };
    await route.fulfill({ json: body });
  });
  await page.goto(`/app/integrations?organization=${org}`);
  await page.getByLabel('Repository (owner/repo)').fill('owner/repo');
  for (const name of [
    'Project ID',
    'Registered target ID',
    'Passive scanner policy ID',
  ])
    await page.getByLabel(name, { exact: true }).fill(id);
  await page.getByRole('button', { name: 'Create GitHub mapping' }).click();
  await expect(page.getByLabel('One-time webhook secret')).toHaveValue(
    'synthetic-secret-once',
  );
  await page.getByRole('button', { name: 'Dismiss webhook secret' }).click();
  await expect(page.getByLabel('One-time webhook secret')).toHaveCount(0);
  await page
    .getByRole('button', { name: 'Test connection for owner/repo' })
    .click();
  await expect(
    page.getByText('Local readiness verified. Send a signed GitHub ping.'),
  ).toBeVisible();
  await expect(page.locator('.github-tools')).toContainText('ping · ping');
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`github-${width}.png`),
      fullPage: true,
    });
  }
  await page.getByRole('button', { name: 'Disable owner/repo' }).click();
  await expect(
    page.getByRole('button', { name: 'Test connection for owner/repo' }),
  ).toBeDisabled();
});
