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
for (const width of [360, 390, 768, 1024, 1280, 1440, 1920])
  test(`review every public page at ${width}`, async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    for (const route of routes) {
      await page.goto(route);
      await expect(page.locator('h1')).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      const result = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(result.violations, route).toEqual([]);
      const slug = route === '/' ? 'home' : route.slice(1).replaceAll('/', '-');
      await page.screenshot({
        path: `/tmp/aegis-phase3-review/${width}-${slug}.png`,
        fullPage: true,
      });
    }
    expect(errors).toEqual([]);
  });
test('case variants do not crash or select another page', async ({ page }) => {
  await page.goto('/SECURITY');
  await expect(
    page.getByRole('heading', { name: 'Security by explicit boundaries.' }),
  ).toBeVisible();
  await page.goto('/PLATFORM');
  await expect(
    page.getByRole('heading', {
      name: 'One workflow. Distinct sources of truth.',
    }),
  ).toBeVisible();
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    'href',
    'http://localhost:5173/platform',
  );
  await page.goto('/FEATURES/AI-ANALYSIS');
  await expect(
    page.getByRole('heading', {
      name: 'Understand the finding. Keep the source.',
    }),
  ).toBeVisible();
});
test('keyboard footer navigation reaches new content', async ({ page }) => {
  await page.goto('/');
  const link = page
    .locator('footer')
    .getByRole('link', { name: 'Privacy', exact: true });
  await link.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('h1')).toBeFocused();
});

for (const width of [1280, 1440])
  test(`normal pinned story remains inside the viewport at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await expect(page.locator('.pin-spacer')).toHaveCount(1);
    for (const step of ['Discover', 'Scan', 'Explain', 'Enforce and report'])
      await expect(
        page
          .getByRole('list', { name: 'Complete workflow' })
          .getByRole('heading', { name: step, exact: true }),
      ).toHaveCount(1);
    const top = await page
      .locator('.m-story')
      .evaluate((el) => el.getBoundingClientRect().top + scrollY);
    await page.evaluate((y) => window.scrollTo(0, y), top + 1800);
    const panel = page.locator('.story-stage').nth(2);
    await expect(panel).toHaveCSS('visibility', 'visible');
    const box = await panel.locator('.story-visual').boundingBox();
    expect(box!.y).toBeGreaterThanOrEqual(88);
    expect(box!.y + box!.height).toBeLessThanOrEqual(900);
    await page.screenshot({
      path: `/tmp/aegis-phase3-review/${width}-pinned.png`,
    });
  });

test('mobile story enters gently and keeps keyboard navigation usable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.pin-spacer')).toHaveCount(0);
  const stage = page.locator('.story-stage').first();
  await stage.scrollIntoViewIfNeeded();
  await expect(stage.locator('.story-copy')).toHaveCSS('opacity', '1');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page
    .getByRole('dialog')
    .getByRole('link', { name: 'Docs', exact: true })
    .click();
  await expect(page.locator('h1')).toBeFocused();
});
