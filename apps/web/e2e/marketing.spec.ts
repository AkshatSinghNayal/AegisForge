import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const routes = [
  '/',
  '/platform',
  '/features/web-scanning',
  '/features/api-scanning',
  '/features/ai-analysis',
  '/features/ci-cd',
  '/features/reports',
  '/pricing',
  '/docs',
  '/docs/getting-started',
  '/docs/architecture',
  '/docs/authorization',
  '/docs/policies',
  '/docs/integrations',
  '/security',
  '/privacy',
  '/terms',
];
test('all public routes, metadata and internal links resolve', async ({
  page,
}) => {
  const titles = new Set<string>();
  const links = new Set<string>();
  for (const route of routes) {
    await page.goto(route);
    await expect(page.locator('h1')).toHaveCount(1);
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      'href',
      `http://localhost:5173${route}`,
    );
    titles.add(await page.title());
    for (const link of await page
      .locator('a[href^="/"]')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href')!)))
      links.add(link.split('#')[0]!);
  }
  expect(titles.size).toBe(routes.length);
  expect(
    [...links].filter((link) => !routes.includes(link) && link !== '/status'),
  ).toEqual([]);
});
test('critical CTA, architecture anchor and documentation search', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Create a workspace' }).first().click();
  await expect(
    page.getByRole('heading', { name: 'Create a workspace', exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/registration is not available/)).toBeVisible();
  await page.goto('/');
  await page
    .getByRole('link', { name: 'View the architecture' })
    .first()
    .click();
  await expect(page).toHaveURL(/platform#architecture/);
  await expect(
    page.getByRole('heading', { name: 'Separation you can reason about.' }),
  ).toBeInViewport();
  await page.goto('/docs');
  await page.getByRole('searchbox').fill('zzzz');
  await expect(page.getByRole('status')).toContainText('No matching guides');
  await page.getByRole('searchbox').fill('authorization');
  await page
    .getByRole('navigation', { name: 'Documentation' })
    .getByRole('link', { name: 'Scanning authorization' })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Scanning authorization', exact: true }),
  ).toBeVisible();
});
for (const width of [360, 390, 768, 1024, 1440, 1920])
  test(`public layout at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const route of [
      '/',
      '/platform',
      '/features/api-scanning',
      '/pricing',
      '/docs/architecture',
      '/security',
    ]) {
      await page.goto(route);
      await expect(page.locator('h1')).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  });
test('mobile menu, reduced motion and accessibility', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page
    .getByRole('dialog')
    .getByRole('link', { name: 'Pricing', exact: true })
    .click();
  await expect(page).toHaveURL(/pricing/);
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.goto('/');
  await expect(page.locator('.pin-spacer')).toHaveCount(0);
  for (const stage of await page.locator('.story-stage').all()) {
    await stage.scrollIntoViewIfNeeded();
    await expect(stage).toBeVisible();
  }
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze())
      .violations,
  ).toEqual([]);
  await page.screenshot({ path: '/tmp/aegis-home-mobile.png', fullPage: true });
});
test('desktop pin changes panels and cleans up on navigation and motion change', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/');
  await expect(page.locator('.pin-spacer')).toHaveCount(1);
  const story = page.locator('.m-story');
  const top = await story.evaluate(
    (el) => el.getBoundingClientRect().top + scrollY,
  );
  await page.evaluate((y) => window.scrollTo(0, y), top + 1800);
  await expect(page.locator('.story-stage').nth(2)).toHaveCSS(
    'visibility',
    'visible',
  );
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(page.locator('.pin-spacer')).toHaveCount(0);
  for (const stage of await page.locator('.story-stage').all())
    await expect(stage).toHaveCSS('visibility', 'visible');
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze())
      .violations,
  ).toEqual([]);
  await page.screenshot({
    path: '/tmp/aegis-home-desktop.png',
    fullPage: true,
  });
  await page
    .getByRole('link', { name: 'Platform', exact: true })
    .first()
    .click();
  await expect(page.locator('.pin-spacer')).toHaveCount(0);
});

test('static SEO output works without JavaScript and public scrolling is scoped', async ({
  browser,
  page,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await context.newPage();
  const response = await staticPage.goto('http://127.0.0.1:4173/platform/');
  await expect(staticPage).toHaveTitle('Platform | AegisForge');
  await expect(staticPage.locator('link[rel="canonical"]')).toHaveAttribute(
    'href',
    'http://localhost:5173/platform',
  );
  expect(await response!.text()).toContain('AegisForge is a research project');
  await context.close();
  expect((await page.request.get('/sitemap.xml')).status()).toBe(200);
  expect(await (await page.request.get('/robots.txt')).text()).toContain(
    'Disallow: /',
  );
  await page.goto('/');
  await expect(page.locator('html')).toHaveClass(/lenis/);
  await page.getByRole('link', { name: 'Service health', exact: true }).click();
  await expect(page.locator('html')).not.toHaveClass(/lenis/);
  await page.goto('/platform/');
  await expect(
    page.getByRole('heading', {
      name: 'One workflow. Distinct sources of truth.',
    }),
  ).toBeVisible();
  await page.goto('/security/');
  await expect(
    page.getByRole('heading', { name: 'Security by explicit boundaries.' }),
  ).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto('/');
  await expect(page.locator('.pin-spacer')).toHaveCount(0);
  await page.goto('/docs/unknown');
  await expect(
    page.getByRole('heading', { name: 'Guide not found' }),
  ).toBeVisible();
});
