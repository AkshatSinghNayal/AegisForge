import {
  chromium,
  request,
  expect,
} from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const fixture = process.env.AEGIS_LIVE_FIXTURE;
const compose = [
  'compose',
  '-p',
  'aegisforge',
  '-f',
  'docker-compose.yml',
  '-f',
  'docker-compose.e2e.yml',
  '-f',
  `${fixture}/compose.json`,
];
const db = (...args) =>
  execFileSync(
    'docker',
    [...compose, 'exec', '-T', 'api', 'python', '/live/database.py', ...args],
    { encoding: 'utf8' },
  );
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const email = `phase13-live-${Date.now()}@example.test`;
try {
  await page.goto('http://127.0.0.1:5174/auth/sign-up');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page
    .getByLabel('Your name', { exact: true })
    .fill('Synthetic Phase 13 reviewer');
  await page
    .getByLabel('Organization name', { exact: true })
    .fill('Synthetic Phase 13 live test');
  await page
    .getByLabel('Password', { exact: true })
    .fill('Synthetic live password 12345');
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect(page.getByRole('status')).toContainText('Registration received');
  await page.getByRole('link', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page
    .getByLabel('Password', { exact: true })
    .fill('Synthetic live password 12345');
  const loginResponse = page.waitForResponse(
    (r) => r.url().endsWith('/auth/sign-in') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const access = (await (await loginResponse).json()).access_token;
  await expect(page).toHaveURL(/getting-started/);
  const session = await request.newContext({
    baseURL: 'http://127.0.0.1:8000',
    extraHTTPHeaders: {
      Authorization: `Bearer ${access}`,
      Origin: 'http://127.0.0.1:5174',
    },
  });
  const org = (await (await session.get('/api/v1/auth/me')).json())
    .organizations[0].id;
  const csrf = (await (await session.get('/api/v1/auth/csrf')).json())
    .csrf_token;
  const headers = { 'X-CSRF-Token': csrf };
  const hmac = readFileSync(`${fixture}/hmac.txt`, 'utf8');
  const destination = (address) => ({
    name: `Synthetic ${Date.now()}`,
    kind: 'webhook',
    address,
    secret: hmac,
    subscriptions: ['scan.failed'],
  });
  // Route-level requests use real authentication, CSRF, DNS and database dependencies.
  const blocked = [
    'https://127.0.0.1/',
    'https://169.254.169.254/latest/meta-data/',
    'https://[::1]/',
    'https://[::ffff:127.0.0.1]/',
    'https://blocked.webhook.test/',
    'http://webhook.receiver.test/',
    'https://webhook.receiver.test:8443/',
  ];
  for (const address of blocked) {
    const response = await session.post(
      `/api/v1/notifications/destinations?organization_id=${org}`,
      { headers, data: destination(address) },
    );
    expect(response.status()).toBe(422);
    expect((await response.json()).error.code).toBe('destination_invalid');
  }
  expect(
    await (
      await session.get(
        `/api/v1/notifications/destinations?organization_id=${org}`,
      )
    ).json(),
  ).toEqual([]);
  console.log(
    'PASS SSRF: seven authenticated malicious destinations rejected with 422; no destination persisted.',
  );
  db('reject-invalid-signature', 'unused');
  const created = await session.post(
    `/api/v1/notifications/destinations?organization_id=${org}`,
    { headers, data: destination('https://webhook.receiver.test/hook') },
  );
  expect(created.status()).toBe(201);
  const destId = (await created.json()).id;
  db('seed-failure', org);
  let received;
  for (let n = 0; n < 60; n++) {
    try {
      received = JSON.parse(readFileSync(`${fixture}/received.json`, 'utf8'));
    } catch {
      /* Receiver has not acknowledged yet. */
    }
    if (received) break;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  if (!received) console.log(db('diagnostics', org));
  expect(received?.verified).toBe(true);
  expect(received.organization_id).toBe(org);
  await expect
    .poll(async () => {
      const rows = await (
        await session.get(
          `/api/v1/notifications/deliveries?organization_id=${org}`,
        )
      ).json();
      return rows.find((r) => r.destination_id === destId)?.state;
    })
    .toBe('sent');
  console.log(
    'PASS webhook: actual HTTPS POST received; timestamp and exact-byte HMAC verified independently; durable delivery marked sent.',
  );
  await session.delete(
    `/api/v1/notifications/destinations/${destId}?organization_id=${org}`,
    { headers },
  );
  await page.goto(`http://127.0.0.1:5174/app/api-keys?organization=${org}`);
  await page.getByLabel('Name', { exact: true }).fill('Synthetic live key');
  await page.getByLabel('Expires at (local time)').fill('2027-01-01T12:00');
  await page.getByLabel('scans:read', { exact: true }).check();
  const issuance = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === '/api/v1/api-keys' &&
      r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  const key = await (await issuance).json();
  expect(key.secret.startsWith('agf_')).toBe(true);
  // Avoid including the secret in assertion failure diagnostics.
  expect(
    (await page.getByLabel('One-time API secret').inputValue()) === key.secret,
  ).toBe(true);
  await page.getByRole('button', { name: 'Dismiss secret' }).click();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: 'Create API key' }),
  ).toBeVisible();
  await expect(page.getByLabel('One-time API secret')).toHaveCount(0);
  const listed = await (
    await session.get(`/api/v1/api-keys?organization_id=${org}`)
  ).text();
  expect(listed.includes(key.secret)).toBe(false);
  expect(listed.includes('key_hash')).toBe(false);
  const machine = await request.newContext({
    baseURL: 'http://127.0.0.1:8000',
    extraHTTPHeaders: { Authorization: `Bearer ${key.secret}` },
  });
  expect((await machine.storageState()).cookies).toEqual([]);
  expect((await machine.get('/api/public/v1/projects')).status()).toBe(200);
  expect(
    JSON.parse(
      db(
        'inspect-key',
        key.id,
        createHash('sha256').update(key.secret).digest('hex'),
      ),
    ),
  ).toEqual({ hash_only: true, usage_recorded: true });
  db('set-key-hash', key.id, '0'.repeat(64));
  expect((await machine.get('/api/public/v1/projects')).status()).toBe(401);
  db(
    'set-key-hash',
    key.id,
    createHash('sha256').update(key.secret).digest('hex'),
  );
  expect((await machine.get('/api/public/v1/projects')).status()).toBe(200);
  expect((await machine.get('/api/public/v1/findings')).status()).toBe(403);
  expect(
    (
      await session.delete(
        `/api/v1/api-keys/${key.id}?organization_id=${org}`,
        { headers },
      )
    ).status(),
  ).toBe(200);
  expect((await machine.get('/api/public/v1/projects')).status()).toBe(401);
  await machine.dispose();
  await session.dispose();
  console.log(
    'PASS API key: real browser issuance/display/dismiss/reload; hash-only DB assertion; cookie-free key-only request 200, scope denial 403 and revocation 401.',
  );
} finally {
  await browser.close();
}
