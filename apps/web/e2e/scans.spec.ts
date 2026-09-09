import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
test.skip(
  process.env.AEGIS_E2E_AUTH !== '1',
  'Requires disposable PostgreSQL, Redis and mock Celery worker.',
);

test('real mock worker, live SSE replay, final gate and cancellation', async ({
  page,
  context,
}) => {
  test.setTimeout(300000);
  page.setDefaultTimeout(15000);
  const inspect = async (name: string) => {
    for (const width of [390, 768, 1280, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.screenshot({
        path: `/tmp/phase7-review-${name}-${width}.png`,
        fullPage: true,
      });
    }
    await page.setViewportSize({ width: 1280, height: 900 });
  };
  let refreshes = 0;
  page.on('response', (response) => {
    if (response.url().endsWith('/api/v1/auth/refresh') && response.ok())
      refreshes++;
  });
  const origin = 'http://127.0.0.1:5174';
  const csrf = (await (await page.request.get('/api/v1/auth/csrf')).json())
    .csrf_token as string;
  const headers: Record<string, string> = {
    Origin: origin,
    'X-CSRF-Token': csrf,
  };
  const post = async (path: string, data?: unknown) => {
    const response = await page.request.post(`/api/v1${path}`, {
      headers,
      data,
    });
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  };
  const email = `scan-${Date.now()}@example.test`;
  await post('/auth/register', {
    email,
    password: 'Synthetic scan password 123',
    display_name: 'Scan owner',
    organization_name: 'Scan fixture org',
  });
  headers.Authorization = `Bearer ${(await post('/auth/sign-in', { email, password: 'Synthetic scan password 123' })).access_token}`;
  const org = (
    await (await page.request.get('/api/v1/organizations', { headers })).json()
  )[0].id as string;
  const prefix = `/organizations/${org}`;
  const member = (
    await (
      await page.request.get(`/api/v1${prefix}/configuration-identity`, {
        headers,
      })
    ).json()
  ).member_id as string;
  const project = await post(`${prefix}/projects`, {
    name: 'Mock lifecycle project',
    slug: 'mock',
    owner_id: member,
    member_ids: [member],
  });
  const policy = await post(`${prefix}/policies`, {
    name: 'Mock baseline',
    mode: 'baseline',
    allow_private: true,
    internal_test_declaration:
      'Administrator authorizes this disposable local fixture.',
  });
  await post(`${prefix}/targets`, {
    project_id: project.id,
    display_name: 'Lifecycle fixture',
    kind: 'web_url',
    base_url: 'http://target-fixture:8080',
    policy_id: policy.id,
    consent: true,
    authorization_owner_id: member,
    authorization_declaration: 'I own and authorize this disposable fixture.',
  });
  const active = await post(`${prefix}/policies`, {
    name: 'Mock active',
    mode: 'active',
    active_warning_acknowledged: true,
    active_rule_allowlist: ['40012'],
    allow_private: true,
    internal_test_declaration:
      'Administrator authorizes this disposable local fixture.',
  });
  await page.goto('/app/scans');
  await expect(page.getByText('No scans yet.', { exact: false })).toBeVisible();
  await inspect('empty-history');
  await page.getByRole('link', { name: 'New scan', exact: true }).click();
  await inspect('target');
  await page
    .getByRole('combobox', { name: 'Target', exact: true })
    .selectOption({ label: 'Lifecycle fixture · development' });
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await inspect('policy');
  await page
    .getByRole('combobox', { name: 'Policy', exact: true })
    .selectOption(active.id);
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await inspect('active-consent');
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Policy', exact: true })
    .selectOption(policy.id);
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByLabel('Branch (optional)').fill('phase7-fixture');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Final review' }),
  ).toBeVisible();
  await inspect('final-review');
  await page.getByRole('button', { name: 'Start scan', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/scans\/[a-f0-9-]+$/);
  await expect(
    page.getByText('DEMO · Simulated lifecycle', { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByLabel('Sanitized scan event timeline')
      .getByText('queued', { exact: true })
      .first(),
  ).toBeVisible();
  const refreshesAtStart = refreshes;
  await inspect('running');
  await context.setOffline(true);
  await page.waitForTimeout(1500);
  await context.setOffline(false);
  await expect(page.getByRole('status')).toHaveText('History synchronized', {
    timeout: 120000,
  });
  expect(refreshes).toBeGreaterThan(refreshesAtStart);
  const timeline = page.getByLabel('Sanitized scan event timeline');
  const lines = await timeline.locator('li').allTextContents();
  const sequences = lines.map((line) => Number(line.trim().slice(0, 3)));
  expect(sequences).toEqual(
    Array.from({ length: sequences.length }, (_, i) => i + 1),
  );
  expect(lines.join(' ')).not.toContain('password');
  await expect(
    page.getByText('fail · demo not security evidence', { exact: true }),
  ).toBeVisible();
  await inspect('completed');
  await page.getByRole('link', { name: 'Back to scan history' }).click();
  await expect(
    page.getByText('Branch phase7-fixture', { exact: false }),
  ).toBeVisible();
  await inspect('history');
  await page.getByRole('link', { name: 'New scan', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Target', exact: true })
    .selectOption({ label: 'Lifecycle fixture · development' });
  for (let i = 0; i < 3; i++)
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'Start scan', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel scan', exact: true }).click();
  await expect(page.getByText('Scan stopped: cancelled.')).toBeVisible();
  await inspect('cancelled');
  await expect(
    page.getByRole('button', { name: 'Cancel scan', exact: true }),
  ).toHaveCount(0);
});
