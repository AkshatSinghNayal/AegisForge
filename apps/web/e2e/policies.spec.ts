import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
// Explicit synthetic HTTP fixtures; production service tests use real PostgreSQL.
test('structured policy publication, activation, preview and immutable history', async ({
  page,
}) => {
  const org = '10000000-0000-4000-8000-000000000001';
  const id = '20000000-0000-4000-8000-000000000001';
  let active: string | null = null;
  const versions: { id: string; version: number; snapshot: unknown }[] = [];
  const result = {
    outcome: 'fail',
    matches: [
      {
        rule_id: 'rule-1',
        outcome: 'fail',
        reason: '1 matching findings exceed the allowed count of 0.',
        finding_ids: [id],
        occurrence_ids: [id],
      },
    ],
    excluded_finding_ids: [],
  };
  const history: unknown[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path.endsWith('/auth/csrf')) body = { csrf_token: 'synthetic-csrf' };
    else if (path.endsWith('/auth/refresh'))
      body = {
        access_token: 'synthetic-access',
        expires_in: 600,
        token_type: 'Bearer',
      };
    else if (path.endsWith('/auth/me'))
      body = {
        id,
        email: 'synthetic@example.invalid',
        display_name: 'Fixture admin',
        email_verified: true,
        organizations: [{ id: org, name: 'Synthetic org', role: 'owner' }],
      };
    else if (path.endsWith('/projects'))
      body = [{ id, name: 'Synthetic project' }];
    else if (path.endsWith('/activation')) {
      active = (route.request().postDataJSON() as { policy_id: string | null })
        .policy_id;
      body = { message: 'Updated' };
    } else if (path.endsWith('/gate-policies')) {
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON() as {
          policy: { rules: { match: { owasp: string[] } }[] };
        };
        expect(payload.policy.rules[0]?.match.owasp).toEqual([
          'OWASP_2021_A03',
        ]);
        body = {
          id,
          version: versions.length + 1,
          snapshot: { ...payload.policy, exceptions: [] },
        };
        versions.push(body as (typeof versions)[number]);
      } else body = { active_id: active, versions };
    } else if (path.endsWith('/policy-preview')) body = result;
    else if (path.endsWith('/policy-evaluations')) {
      if (route.request().method() === 'POST') {
        body = {
          id: `evaluation-${history.length + 1}`,
          input_digest: 'a'.repeat(64),
          evaluation_version: 'deterministic-v1',
          input_snapshot: { policy: versions[0]?.snapshot },
          result_snapshot: result,
        };
        history.push(body);
      } else body = history;
    } else throw new Error(`Unexpected fixture ${path}`);
    await route.fulfill({ json: body });
  });
  await page.goto('/app/gates');
  await expect(
    page.getByRole('heading', { name: 'Project gate policies' }),
  ).toBeVisible();
  await page.getByLabel('owasp', { exact: true }).fill('OWASP_2021_A03');
  await page
    .getByRole('button', { name: 'Publish version', exact: true })
    .click();
  await expect(page.getByRole('status')).toContainText(
    'Published immutable version 1',
  );
  await page.getByRole('button', { name: 'Activate selected version' }).click();
  await expect(page.getByText('Active: 1', { exact: true })).toBeVisible();
  await page.getByLabel('Scan ID').fill(id);
  await page.getByRole('button', { name: 'Preview selected policy' }).click();
  await expect(
    page.getByRole('heading', { name: 'Outcome: fail' }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: `Finding ${id}` })).toBeVisible();
  await page.getByText('Contributing occurrence IDs', { exact: true }).click();
  await expect(
    page.getByRole('listitem').filter({ hasText: id }).last(),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Save re-evaluation' }).click();
  await page.getByRole('button', { name: 'Save re-evaluation' }).click();
  await expect(
    page.getByRole('heading', { name: /Evaluation evaluation-/ }),
  ).toHaveCount(2);
  await page
    .getByText('Immutable input snapshot and digest', { exact: true })
    .first()
    .click();
  await expect(
    page.getByText('a'.repeat(64), { exact: true }).first(),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Deactivate', exact: true }).click();
  await expect(
    page.getByText('Active: None — scans remain incomplete'),
  ).toBeVisible();
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
          .analyze()
      ).violations,
    ).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 900 });
  await page.screenshot({
    path: '/tmp/phase11-policy-mobile.png',
    fullPage: true,
  });
});
