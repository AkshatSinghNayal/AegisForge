import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
for (const width of [360, 390, 768, 1024, 1280, 1440, 1920])
  for (const route of ['ui', 'motion'])
    test(`${route} fits ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.goto(`/dev/${route}`);
      await expect(page.locator('h1')).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      if (width === 390 || width === 1440) {
        const results = await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
          .analyze();
        expect(results.violations).toEqual([]);
        await expect(page).toHaveScreenshot(`${route}-${width}.png`, {
          fullPage: true,
          animations: 'disabled',
        });
      }
    });
test('modal traps focus, Escape restores it; popover and sidebar work', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/ui');
  const trigger = page.getByRole('button', {
    name: 'Open dialog',
    exact: true,
  });
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Shift+Tab');
  expect(
    await dialog.evaluate((el) => el.contains(document.activeElement)),
  ).toBe(true);
  await page.keyboard.press('Tab');
  expect(
    await dialog.evaluate((el) => el.contains(document.activeElement)),
  ).toBe(true);
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await page.getByRole('button', { name: 'About this lab' }).click();
  await expect(
    page.getByRole('heading', { name: 'Development only' }),
  ).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Open sidebar' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page
    .getByRole('dialog')
    .getByRole('link', { name: 'Motion lab' })
    .click();
  await expect(page.locator('h1')).toHaveText('Clarity in motion.');
});
test('motion runs, cleans up on navigation, and respects a live preference change', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/dev/motion');
  await expect(page.locator('.pin-spacer')).toHaveCount(1);
  await page.locator('[data-count]').scrollIntoViewIfNeeded();
  await expect(page.locator('[data-count]')).toHaveText('128');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(page.locator('.pin-spacer')).toHaveCount(0);
  await expect(page.locator('[data-terminal]')).toContainText(
    'No scan executed',
  );
  await expect(page.locator('.story-panel').nth(1)).toHaveCSS('opacity', '1');
  await page
    .getByRole('link', { name: 'Back to the component library' })
    .click();
  await expect(page.locator('.pin-spacer')).toHaveCount(0);
  expect(
    await page.evaluate(() =>
      document.documentElement.classList.contains('lenis'),
    ),
  ).toBe(false);
  expect(errors).toEqual([]);
});
