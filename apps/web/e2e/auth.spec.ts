import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
test.skip(
  process.env.AEGIS_E2E_AUTH !== '1',
  'Requires the migrated Phase 5 API and Redis; see docs/AUTHENTICATION.md.',
);
async function register(page: import('@playwright/test').Page) {
  const email = `browser-${Date.now()}-${Math.random().toString(16).slice(2)}@example.test`;
  await page.goto('/auth/sign-up');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Your name', { exact: true }).fill('Browser user');
  await page
    .getByLabel('Organization name', { exact: true })
    .fill('Browser organization');
  await page
    .getByLabel('Password', { exact: true })
    .fill('Browser synthetic password 123');
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect(page.getByRole('status')).toContainText('Registration received');
  await page.getByRole('link', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Welcome back.' }),
  ).toBeVisible();
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page
    .getByLabel('Password', { exact: true })
    .fill('Browser synthetic password 123');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/getting-started/);
  await expect(
    page.getByRole('heading', { name: 'A clear path to your first scan.' }),
  ).toBeVisible();
}
test('registration, login, real onboarding, refresh bootstrap, organization switch and logout', async ({
  page,
}) => {
  await register(page);
  await expect(
    page.getByText('0 of 4 complete', { exact: true }),
  ).toBeVisible();
  await page.locator('summary').filter({ hasText: 'Create project' }).click();
  await expect(
    page.getByText(
      'Group your application and its security evidence in a project.',
    ),
  ).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: '/tmp/aegis-phase5-workspace.png',
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByText('0 of 4 complete', { exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  await page.getByText('Create an organization', { exact: true }).click();
  await page
    .getByLabel('New organization name')
    .fill('Second browser organization');
  await page
    .getByRole('button', { name: 'Create organization', exact: true })
    .click();
  await expect(page.getByRole('status')).toHaveText('Changes saved.');
  await page
    .getByRole('combobox', { name: 'Organization', exact: true })
    .selectOption({ label: 'Second browser organization' });
  await expect(
    page.getByText('0 of 4 complete', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/sign-in/);
  await page.goto('/app/getting-started');
  await expect(page).toHaveURL(/\/auth\/sign-in/);
});
test('anonymous protected route redirects to sign in', async ({ page }) => {
  await page.goto('/app/getting-started');
  await expect(page).toHaveURL(/\/auth\/sign-in/);
  await expect(
    page.getByRole('heading', { name: 'Welcome back.' }),
  ).toBeVisible();
});
test('mobile sidebar keyboard close and sign out', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await register(page);
  await page.screenshot({
    path: '/tmp/aegis-phase5-mobile.png',
    fullPage: true,
  });
  await page.getByRole('button', { name: 'Open sidebar' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Open sidebar' }).click();
  await dialog.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/sign-in/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test('desktop collapse and recovery forms', async ({ page }) => {
  await register(page);
  await page.getByRole('button', { name: 'Collapse sidebar' }).click();
  await expect(
    page.getByRole('button', { name: 'Expand sidebar' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Expand sidebar' }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByRole('link', { name: 'Forgot password?' }).click();
  await expect(
    page.getByRole('heading', { name: 'Reset your password.' }),
  ).toBeVisible();
  await page
    .getByLabel('Email', { exact: true })
    .fill('unknown-browser@example.test');
  await page.getByRole('button', { name: 'Send reset link' }).click();
  await expect(page.getByRole('status')).toContainText(
    'If the account is available',
  );
  await page.goto('/auth/reset-password');
  await expect(page.getByRole('alert')).toContainText(
    'Open the link from your email',
  );
  await expect(
    page.getByRole('button', { name: 'Continue', exact: true }),
  ).toBeDisabled();
});
