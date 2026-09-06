import { test, expect, type Locator } from '@playwright/test';

async function expectTouchTargets(links: Locator, count?: number) {
  await expect(links.first()).toBeVisible();
  if (count !== undefined) await expect(links).toHaveCount(count);
  else expect(await links.count()).toBeGreaterThan(0);
  for (const link of await links.all()) {
    await expect(link).toBeVisible();
    const size = await link.evaluate((element) => {
      const { width, height } = element.getBoundingClientRect();
      return { width, height };
    });
    const label = await link.innerText();
    expect.soft(size.width, `${label} width`).toBeGreaterThanOrEqual(44);
    expect.soft(size.height, `${label} height`).toBeGreaterThanOrEqual(44);
  }
}

for (const width of [360, 390, 768, 1024, 1280, 1440, 1920]) {
  test(`public link touch targets at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await expectTouchTargets(page.locator('.m-footer a'));
    await expectTouchTargets(page.locator('.outcome a'), 2);
    for (const route of ['/docs', '/docs/getting-started']) {
      await page.goto(route);
      await expectTouchTargets(
        page.locator('.docs-layout aside > a.eyebrow'),
        1,
      );
      await expectTouchTargets(page.locator('.m-footer a'));
    }
  });
}
