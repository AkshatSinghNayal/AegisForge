import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

// Synthetic HTTP boundary fixtures; real ingestion/RBAC is covered in PostgreSQL tests.
test('finding filters, evidence provenance, review and scan comparison', async ({
  page,
}) => {
  test.setTimeout(120000);
  const org = '10000000-0000-4000-8000-000000000001';
  const id = '20000000-0000-4000-8000-000000000001';
  const scan = '30000000-0000-4000-8000-000000000001';
  const item = {
    id,
    target_id: id,
    title: 'Synthetic SQL injection observation',
    severity: 'high',
    confidence: 'medium',
    status: 'new',
    route: '/search',
    cwe: 89,
    owasp: ['OWASP_2021_A03'],
    first_seen_at: '2026-09-09T01:00:00Z',
    last_seen_at: '2026-09-09T01:00:00Z',
    version: 1,
  };
  const normalized = {
    rule: '40018',
    method: 'GET',
    parameter: 'q',
    location: 'query',
    wasc: 19,
    references: [],
    request: 'GET /search\nAuthorization: [REDACTED]\n[Body withheld]',
    response: 'Set-Cookie: [REDACTED]\n[Body withheld]',
    sources: { severity: ['/alerts/0/risk'] },
    redaction: { bodies: 'withheld', headers: 'all values masked' },
  };
  const analysisFixture = (version: number) => ({
    id: `analysis-${version}`,
    occurrence_id: id,
    provider: 'mock',
    model: 'deterministic-demo-v1',
    schema_version: 'guidance-v1',
    prompt_version: 'guidance-v1',
    status: 'mock',
    generated_at: `2026-09-10T01:0${version}:00Z`,
    output: {
      summary: '<img src=x onerror="alert(1)">',
      vulnerability_explanation: 'Synthetic advisory explanation',
      root_cause_hypothesis:
        'Hypothesis requiring review: implementation may be involved.',
      technical_impact: 'Unverified technical impact',
      business_impact: 'Unverified business impact',
      remediation_steps: ['Review affected implementation'],
      verification_steps: ['Run an authorized verification scan'],
      evidence_ids: [id],
      cwe_interpretation: 'Scanner CWE 89',
      owasp_mapping_interpretation: 'Scanner supplied mapping',
      model_confidence: 0.2,
      uncertainty_notes: ['Classification alone cannot establish root cause'],
    },
    feedback: [] as { id: string; useful: boolean; note: string }[],
  });
  const analyses: ReturnType<typeof analysisFixture>[] = [];
  let note = '';
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
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
        display_name: 'Fixture reviewer',
        email_verified: true,
        organizations: [
          { id: org, name: 'Synthetic fixture org', role: 'owner' },
        ],
      };
    else if (path.endsWith('/review')) {
      const payload = route.request().postDataJSON() as {
        action: string;
        note: string;
        version: number;
      };
      expect(payload.version).toBe(1);
      expect(payload.action).toBe('accept_risk');
      note = payload.note;
      item.status = 'accepted_risk';
      item.version++;
      body = item;
    } else if (path.includes('/comparison/'))
      body = {
        scan_id: scan,
        state: 'completed',
        completeness: 'complete',
        comparison: { baseline_scan_id: null, changes: { [id]: 'new' } },
      };
    else if (path.endsWith(`/findings/${id}`))
      body = {
        finding: item,
        fingerprint: 'a'.repeat(64),
        fingerprint_version: 'zap-fingerprint-v1',
        normalized,
        occurrences: [
          {
            id,
            scan_id: scan,
            artifact_id: id,
            normalizer: 'zap-normalizer-v1',
            evidence_reference: `occurrence:${id}#/normalized`,
            observed_at: item.last_seen_at,
            normalized,
          },
        ],
        history: note
          ? [
              {
                id,
                action: 'accept_risk',
                previous_state: 'new',
                state: item.status,
                note,
                actor_id: id,
                scan_id: null,
                created_at: item.last_seen_at,
              },
            ]
          : [],
        analysis_status: [],
        policy_impact: [],
      };
    else if (path.endsWith('/feedback')) {
      const payload = route.request().postDataJSON() as {
        useful: boolean;
        note: string;
      };
      analyses[0]?.feedback.push({ id: 'feedback-1', ...payload });
      body = { id: 'feedback-1' };
    } else if (path.endsWith('/analyses')) {
      if (route.request().method() === 'POST') {
        expect(route.request().headers()['x-csrf-token']).toBe(
          'synthetic-csrf',
        );
        analyses.unshift(analysisFixture(analyses.length + 1));
        body = analyses[0];
      } else body = analyses;
    } else if (path.endsWith('/findings'))
      body = {
        items: url.searchParams.get('severity') === 'low' ? [] : [item],
        total: url.searchParams.get('severity') === 'low' ? 0 : 1,
        page: 1,
        page_size: 25,
      };
    else return route.fulfill({ status: 404, json: {} });
    await route.fulfill({ json: body });
  });
  await page.goto('/app/findings');
  await expect(page.getByRole('link', { name: item.title })).toBeVisible();
  await page
    .getByRole('combobox', { name: 'severity', exact: true })
    .selectOption('low');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page).toHaveURL(/severity=low/);
  await expect(
    page.getByText('No findings match these filters.'),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('combobox', { name: 'severity', exact: true }),
  ).toHaveValue('low');
  await page
    .getByRole('combobox', { name: 'severity', exact: true })
    .selectOption('high');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await page.getByRole('button', { name: 'last seen at' }).click();
  await expect(page).toHaveURL(/sort=last_seen_at/);
  await page.getByRole('link', { name: item.title }).click();
  await page.getByRole('tab', { name: 'Evidence', exact: true }).click();
  await expect(
    page.getByText('Authorization: [REDACTED]', { exact: false }),
  ).toBeVisible();
  await page.getByText('Field provenance (raw JSON pointers)').click();
  await expect(
    page.getByText('"/alerts/0/risk"', { exact: false }),
  ).toBeVisible();
  for (const width of [390, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.getByRole('tab', { name: 'Evidence', exact: true }).focus();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: `/tmp/phase9-evidence-${width}.png`,
      fullPage: true,
    });
  }
  await page.getByRole('tab', { name: 'AI Guidance', exact: true }).click();
  await expect(
    page.getByText('No AI analysis has been generated for this finding.'),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Generate guidance', exact: true })
    .click();
  await expect(
    page.getByText('Model confidence: 20%', { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText('<img src=x onerror="alert(1)">', { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator('.ai-guidance img, .ai-guidance script'),
  ).toHaveCount(0);
  await page.getByRole('checkbox').check();
  await page
    .getByLabel('Reviewer note', { exact: true })
    .fill('Synthetic AI review');
  await page.getByRole('button', { name: 'Save feedback' }).click();
  await expect(
    page.getByText('Useful: Synthetic AI review', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Regenerate guidance' }).click();
  await expect(page.locator('.ai-version')).toHaveCount(2);
  for (const width of [390, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({
      path: `/tmp/phase10-guidance-${width}.png`,
      fullPage: true,
    });
  }
  await page
    .getByRole('button', { name: `View occurrence ${id}` })
    .first()
    .click();
  await expect(
    page.getByRole('tab', { name: 'Evidence', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  await expect(
    page.getByRole('tab', { name: 'Evidence', exact: true }),
  ).toBeFocused();
  await page.getByRole('tab', { name: 'AI Guidance', exact: true }).click();
  await page
    .getByRole('tab', { name: 'AI Guidance', exact: true })
    .press('ArrowRight');
  await expect(
    page.getByRole('tab', { name: 'History', exact: true }),
  ).toBeFocused();
  await page.getByRole('tab', { name: 'History', exact: true }).press('End');
  await expect(
    page.getByRole('tab', { name: 'Policy', exact: true }),
  ).toHaveAttribute('aria-selected', 'true');
  await expect(
    page.getByText(
      'No policy evaluation is available. No passing gate is implied.',
    ),
  ).toBeVisible();
  await page
    .getByRole('combobox', { name: 'Action', exact: true })
    .selectOption('accept_risk');
  await page
    .getByLabel('Reviewer note (do not include secrets)')
    .fill('Synthetic review rationale');
  await page.getByRole('button', { name: 'Save review' }).click();
  await expect(page.locator('.finding-accepted_risk')).toBeVisible();
  await page.getByRole('tab', { name: 'History', exact: true }).click();
  await expect(
    page.getByText('Synthetic review rationale', { exact: true }),
  ).toBeVisible();
  await page.getByRole('tab', { name: 'Evidence', exact: true }).click();
  await page.getByRole('link', { name: 'Compare this scan' }).click();
  await expect(
    page.getByRole('heading', { name: 'Scan comparison' }),
  ).toBeVisible();
  await expect(
    page.getByText('Baseline: No comparable completed scan'),
  ).toBeVisible();
});
