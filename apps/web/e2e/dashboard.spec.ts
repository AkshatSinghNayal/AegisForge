import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const org = '10000000-0000-4000-8000-000000000001';
const id = '20000000-0000-4000-8000-000000000001';
const data = {
  generated_at: '2026-09-11T00:00:00Z',
  date_from: '2026-08-12T00:00:00Z',
  date_to: '2026-09-11T00:00:00Z',
  timezone: 'UTC',
  excluded_scans: 2,
  metrics: [
    { label: 'Completed scans', value: 8, unit: 'count' },
    { label: 'Open findings', value: 3, unit: 'count' },
    { label: 'New high / critical', value: 1, unit: 'count' },
    { label: 'Targets recently scanned', value: 1, unit: 'count' },
    { label: 'Policy pass rate', value: 75, unit: '%' },
    { label: 'Mean time to resolution', value: null, unit: 'hours' },
  ],
  severity: [
    { label: 'high', value: 1 },
    { label: 'medium', value: 2 },
  ],
  owasp: [],
  exclusions: [],
  categories: [{ label: 'CWE-79', value: 3 }],
  lifecycle: [
    { label: '2026-09-10 · new', value: 1 },
    { label: '2026-09-10 · recurring', value: 2 },
    { label: '2026-09-10 · resolved', value: 1 },
  ],
  duration: [{ label: '2026-09-10', value: 5 }],
  completion: [{ label: '2026-09-10', value: 80 }],
  risk: [
    {
      project_id: id,
      target_id: id,
      project: 'Synthetic project',
      target: 'Synthetic target',
      open_findings: 3,
      high_critical: 1,
    },
  ],
  risk_total: 1,
  activity: [],
  action_items: [],
  actions: [
    { label: 'Failed or timed-out scans', value: 2, unit: 'count' },
    { label: 'Targets overdue for a complete scan', value: 0, unit: 'count' },
    { label: 'Unresolved high / critical findings', value: 1, unit: 'count' },
    { label: 'Expired exceptions in active gates', value: 0, unit: 'count' },
  ],
};
for (const role of ['owner', 'developer', 'viewer']) {
  test(`dashboard and product navigation as ${role}`, async ({ page }) => {
    test.setTimeout(120000);
    let failing = false;
    const aggregateQueries: string[] = [];
    let delayRegistry = false;
    let pagedSelectors = false;
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body: unknown = [];
      if (path.endsWith('/auth/csrf')) body = { csrf_token: 'synthetic' };
      else if (path.endsWith('/auth/refresh'))
        body = {
          access_token: 'synthetic',
          expires_in: 600,
          token_type: 'Bearer',
        };
      else if (path.endsWith('/auth/me'))
        body = {
          id,
          email: 'test@example.invalid',
          display_name: 'Synthetic reviewer',
          email_verified: true,
          organizations: [
            { id, name: 'Other org', role },
            { id: org, name: 'Synthetic organization', role },
          ],
        };
      else if (path.includes('/analytics/dashboard')) {
        aggregateQueries.push(route.request().url());
        if (failing) {
          await route.fulfill({
            status: 503,
            json: { error: { message: 'Test outage' } },
          });
          return;
        }
        body = data;
      } else if (
        path.endsWith('/resources/projects') ||
        path.endsWith('/resources/targets')
      ) {
        const query = new URL(route.request().url()).searchParams;
        body = !pagedSelectors
          ? [{ id, project_id: id, label: 'Synthetic project' }]
          : query.get('offset') === '200'
            ? [
                {
                  id: '30000000-0000-4000-8000-000000000201',
                  project_id: query.get('project_id') || id,
                  label: 'Record 201',
                },
              ]
            : Array.from({ length: 200 }, (_, n) => ({
                id: `40000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
                project_id: query.get('project_id') || id,
                label: `Record ${n + 1}`,
              }));
      } else if (path.endsWith('/onboarding'))
        body = {
          create_project: true,
          register_target: true,
          run_safe_baseline: false,
          configure_ci: false,
        };
      else if (path.endsWith('/findings'))
        body = { items: [], total: 0, page: 1, page_size: 25 };
      else if (path.includes('/workspace/')) {
        const registryPage = Number(
          new URL(route.request().url()).searchParams.get('page') || 1,
        );
        if (delayRegistry)
          await new Promise((resolve) => setTimeout(resolve, 1500));
        body = {
          items: [
            {
              id,
              label: `Synthetic record page ${registryPage}`,
              status: 'active',
              created_at: data.generated_at,
              expires_at: null,
              scan_id: null,
            },
          ],
          total: 51,
          page: registryPage,
          page_size: 50,
        };
      }
      await route.fulfill({ json: body });
    });
    await page.goto(`/app/dashboard?timezone=UTC&organization=${org}`);
    await expect(
      page.getByRole('heading', { name: 'Dashboard', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('8', { exact: true })).toBeVisible();
    await page
      .getByRole('combobox', { name: 'Project', exact: true })
      .selectOption(id);
    await expect(page).toHaveURL(new RegExp(`project=${id}`));
    await expect.poll(() => aggregateQueries.at(-1)).toContain(`project=${id}`);
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export this page as CSV' }).click();
    expect((await download).suggestedFilename()).toBe('aegisforge-table.csv');
    if (role === 'owner')
      for (const width of [390, 768, 1280, 1440]) {
        await page.setViewportSize({ width, height: 1000 });
        await page.evaluate(() => {
          (document.activeElement as HTMLElement | null)?.blur();
          window.scrollTo(0, 0);
        });
        await expect(page.getByText(/scans excluded/)).toBeVisible();
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
        expect((await new AxeBuilder({ page }).analyze()).violations).toEqual(
          [],
        );
        await expect(page).toHaveScreenshot(`dashboard-${width}.png`, {
          fullPage: true,
          animations: 'disabled',
        });
      }
    for (const name of ['Policy gates', 'Scan policies', 'Workspace']) {
      await expect(
        page.getByRole('link', { name, exact: true }),
      ).toHaveAttribute('href', new RegExp(`organization=${org}`));
    }
    if (role === 'owner') {
      pagedSelectors = true;
      await page.goto(`/app/dashboard?organization=${org}&timezone=UTC`);
      await page
        .getByRole('button', { name: 'Load more projects', exact: true })
        .click();
      await page
        .getByRole('combobox', { name: 'Project', exact: true })
        .selectOption({ label: 'Record 201' });
      await page
        .getByRole('button', { name: 'Load more targets', exact: true })
        .click();
      await page
        .getByRole('combobox', { name: 'Target', exact: true })
        .selectOption({ label: 'Record 201' });
      await expect
        .poll(() => aggregateQueries.at(-1))
        .toContain('target=30000000-0000-4000-8000-000000000201');
      await expect
        .poll(() => aggregateQueries.at(-1))
        .toContain('project=30000000-0000-4000-8000-000000000201');
      await expect(
        page.getByRole('button', { name: 'Load more targets', exact: true }),
      ).toHaveCount(0);
    }
    failing = true;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByText('Test outage')).toBeVisible();
    failing = false;
    await page.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(page.getByText('8', { exact: true })).toBeVisible();
    if (role === 'owner') {
      await page.goto(`/app/audit-log?organization=${org}`);
      await expect(
        page.getByText('Synthetic record page 1', { exact: true }),
      ).toBeVisible();
      await page.getByRole('button', { name: 'Next', exact: true }).click();
      await expect(
        page.getByText('Synthetic record page 2', { exact: true }),
      ).toBeVisible();
      delayRegistry = true;
      await page.goBack();
      await expect(page.getByText('Loading records…')).toBeVisible();
      await expect(
        page.getByText('Synthetic record page 2', { exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByText('Synthetic record page 1', { exact: true }),
      ).toBeVisible();
    }
    for (const [path, heading] of [
      ['projects', 'Projects'],
      ['targets', 'Targets'],
      ['scans', 'Scan history'],
      ['findings', 'Evidence-backed findings'],
      ['gates', 'Project gate policies'],
      ['team', 'Team'],
      ['settings', 'Settings'],
    ] as const) {
      await page.goto(`/app/${path}?organization=${org}`);
      await expect(
        page.getByRole('heading', { name: heading, exact: true }).first(),
      ).toBeVisible();
      if (path === 'team' && role !== 'owner')
        await expect(page.getByText(/Permission denied/)).toBeVisible();
    }
  });
}
