import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
test.skip(
  process.env.AEGIS_E2E_AUTH !== '1',
  'Requires the disposable real backend and synthetic target fixture.',
);

test('complete project, policy, authorized target, credential and archive setup', async ({
  page,
}) => {
  test.setTimeout(240000);
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
        path: `/tmp/phase6-review-${name}-${width}.png`,
        fullPage: true,
      });
    }
    await page.setViewportSize({ width: 1280, height: 900 });
  };
  const email = `config-${Date.now()}@example.test`;
  await page.goto('/auth/sign-up');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page
    .getByLabel('Your name', { exact: true })
    .fill('Configuration owner');
  await page
    .getByLabel('Organization name', { exact: true })
    .fill('Synthetic configuration org');
  await page
    .getByLabel('Password', { exact: true })
    .fill('Synthetic configuration password 123');
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect(page.getByRole('status')).toContainText('Registration received');
  await page.getByRole('link', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page
    .getByLabel('Password', { exact: true })
    .fill('Synthetic configuration password 123');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/getting-started/);
  await page.getByRole('link', { name: 'Projects', exact: true }).click();
  await inspect('projects');
  await page.getByRole('link', { name: 'Create project', exact: true }).click();
  await inspect('project-new');
  await page.getByLabel('Project name', { exact: true }).fill('Synthetic API');
  await page.getByLabel('Slug', { exact: true }).fill('synthetic-api');
  await page
    .getByRole('textbox', { name: 'Description', exact: true })
    .fill('Owned development fixture');
  await page.getByRole('button', { name: 'Save project', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Synthetic API', exact: true }),
  ).toBeVisible();
  const projectUrl = page.url();
  await inspect('project-detail');
  await expect(
    page.getByText('No scans recorded. Start a scan from Scan history.'),
  ).toBeVisible();
  await page.getByRole('link', { name: 'Scan policies', exact: true }).click();
  await page.getByRole('button', { name: 'Add standard policies' }).click();
  await expect(
    page.getByRole('link', { name: 'Passive baseline', exact: true }),
  ).toBeVisible();
  await inspect('policies');
  await page.getByRole('link', { name: 'Create custom policy' }).click();
  await page
    .getByRole('combobox', { name: 'Mode', exact: true })
    .selectOption('active');
  await inspect('policy-active-editor');
  await page
    .getByRole('combobox', { name: 'Mode', exact: true })
    .selectOption('baseline');
  await page
    .getByLabel('Policy name', { exact: true })
    .fill('Internal fixture passive');
  await page.getByLabel('Permit RFC1918', { exact: false }).check();
  await page
    .getByLabel('Internal test authorization', { exact: false })
    .fill(
      'Administrator authorizes this disposable internal development fixture.',
    );
  await page
    .getByRole('button', { name: 'Create policy', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Scan policies', exact: true }),
  ).toBeVisible();
  await page.getByRole('link', { name: 'Targets', exact: true }).click();
  await inspect('targets');
  await page
    .getByRole('link', { name: 'Register target', exact: true })
    .click();
  await page
    .getByRole('combobox', { name: 'Project', exact: true })
    .selectOption({ label: 'Synthetic API' });
  await page
    .getByLabel('Display name', { exact: true })
    .fill('Synthetic target');
  await page
    .getByRole('combobox', { name: 'Target type', exact: true })
    .selectOption('openapi_upload');
  await page
    .getByLabel('Base URL', { exact: true })
    .fill('http://127.0.0.1:8080/');
  await page
    .getByLabel('OpenAPI JSON or YAML', { exact: false })
    .setInputFiles({
      name: 'api.json',
      mimeType: 'application/json',
      buffer: Buffer.from(
        JSON.stringify({
          openapi: '3.0.3',
          info: { title: 'Synthetic', version: '1.0' },
          paths: {},
          'x-secret': 'SPEC-CANARY',
        }),
      ),
    });
  await inspect('wizard-basics');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Policy version', exact: true })
    .selectOption({ label: 'Internal fixture passive · v1 · baseline' });
  await inspect('wizard-scope');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page
    .getByRole('combobox', { name: 'Authentication type', exact: true })
    .selectOption('bearer');
  await page
    .getByLabel('Secret value', { exact: true })
    .fill('BROWSER-SECRET-CANARY');
  await page
    .getByLabel('Authorization declaration', { exact: true })
    .fill(
      'I own and authorize tests against this disposable synthetic fixture.',
    );
  await inspect('wizard-authentication');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.getByText('BROWSER-SECRET-CANARY')).toHaveCount(0);
  await page.getByRole('checkbox').check();
  await page
    .getByRole('button', { name: 'Validate URL and OpenAPI', exact: true })
    .click();
  await expect(page.getByRole('alert')).toContainText('blocked network');
  await expect(
    page.getByRole('button', {
      name: 'Authorize and register target',
      exact: true,
    }),
  ).toBeDisabled();
  await inspect('wizard-failure');
  await page.getByRole('button', { name: 'Edit setup', exact: true }).click();
  await page
    .getByLabel('Base URL', { exact: true })
    .fill('http://target-fixture:8080/');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page
    .getByLabel('Secret value', { exact: true })
    .fill('BROWSER-SECRET-CANARY');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  await page.getByRole('checkbox').check();
  await page
    .getByRole('button', { name: 'Validate URL and OpenAPI', exact: true })
    .click();
  await expect(page.getByRole('alert')).toContainText('OpenAPI valid.');
  await inspect('wizard-review');
  await page
    .getByRole('button', { name: 'Authorize and register target', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Synthetic target', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('OpenAPI: Sanitized document stored'),
  ).toBeVisible();
  await expect(page.getByText('BROWSER-SECRET-CANARY')).toHaveCount(0);
  await inspect('target-detail');
  await page.screenshot({
    path: '/tmp/aegis-phase6-target.png',
    fullPage: true,
  });
  await page
    .getByRole('button', { name: 'Revoke credential', exact: true })
    .click();
  await expect(page.getByText('No authentication configured.')).toBeVisible();
  await page.goto(projectUrl);
  await page
    .getByRole('link', { name: 'Project settings', exact: true })
    .click();
  await expect(
    page.getByRole('button', { name: 'Save project', exact: true }),
  ).toBeVisible();
  await inspect('project-settings');
  await page
    .getByRole('textbox', { name: 'Description', exact: true })
    .fill('Updated synthetic project');
  await page.getByRole('button', { name: 'Save project', exact: true }).click();
  await expect(page.getByText('Updated synthetic project')).toBeVisible();
  await page
    .getByRole('button', { name: 'Archive project', exact: true })
    .click();
  await expect(
    page.getByRole('button', { name: 'Restore project', exact: true }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Restore project', exact: true })
    .click();
  await expect(
    page.getByRole('button', { name: 'Archive project', exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: '/tmp/aegis-phase6-project-mobile.png',
    fullPage: true,
  });
});
