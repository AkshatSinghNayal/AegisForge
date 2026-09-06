import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
for (const width of [360, 390, 768, 1024, 1280, 1440, 1920]) {
  test(`retro targets and focus ${width}`, async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    for (const route of ['/dev/ui', '/dev/motion']) {
      await page.goto(route);
      await expect(page.locator('h1')).toBeVisible();
      const small = await page
        .locator('a,button,input,select,textarea,summary')
        .evaluateAll((nodes) =>
          nodes.flatMap((node) => {
            if (
              !(node instanceof HTMLElement) ||
              !node.checkVisibility() ||
              node.matches(':disabled')
            )
              return [];
            if (node.classList.contains('skip-link')) return [];
            const target = node.matches(
              'input[type=checkbox],input[type=radio]',
            )
              ? node.closest('label')!
              : node;
            const r = target.getBoundingClientRect();
            return r.width < 44 || r.height < 44
              ? [
                  {
                    tag: node.tagName,
                    text: node.textContent?.trim().slice(0, 60),
                    width: r.width,
                    height: r.height,
                  },
                ]
              : [];
          }),
        );
      expect(small, route).toEqual([]);
      if (route.startsWith('/dev/'))
        expect(
          (
            await new AxeBuilder({ page })
              .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
              .analyze()
          ).violations,
        ).toEqual([]);
      await page.keyboard.press('Tab');
      const focus = await page.evaluate(() => {
        const el = document.activeElement!;
        const css = getComputedStyle(el);
        return {
          visible: el.matches(':focus-visible'),
          outline: css.outlineStyle,
          width: css.outlineWidth,
        };
      });
      expect(focus.visible).toBe(true);
      expect(focus.outline).not.toBe('none');
      expect(focus.width).not.toBe('0px');
    }
  });
}
