import { spawnSync } from 'node:child_process';
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
const script = resolve('scripts/seo.mjs');
function build(settings: Record<string, string>) {
  const directory = mkdtempSync(join(tmpdir(), 'aegis-public-config-'));
  mkdirSync(join(directory, 'dist'));
  writeFileSync(
    join(directory, 'dist/index.html'),
    '<html><head><title>AegisForge</title></head><body></body></html>',
  );
  const result = spawnSync(process.execPath, [script], {
    cwd: directory,
    env: {
      ...process.env,
      VITE_SITE_URL: 'https://example.com',
      VITE_SECURITY_CONTACT: '',
      ...settings,
    },
    encoding: 'utf8',
  });
  return { directory, result };
}
describe('public build configuration', () => {
  it.each([
    { VITE_SITE_URL: 'not-a-url' },
    { VITE_SITE_URL: 'https://user:private-marker@example.com' },
    { VITE_SECURITY_CONTACT: 'invalid-private-marker' },
    {
      VITE_SECURITY_CONTACT: 'a@example.com\r\nBcc:private-marker@example.com',
    },
  ])('fails the build without echoing invalid input (%j)', (settings) => {
    const { directory, result } = build(settings);
    try {
      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain('Invalid public configuration');
      expect(result.stderr).not.toContain('private-marker');
    } finally {
      rmSync(directory, { recursive: true });
    }
  });
  it('writes matching public canonical, sitemap and indexing policy', () => {
    const { directory, result } = build({
      VITE_SECURITY_CONTACT: 'security@example.com',
    });
    try {
      expect(result.status, result.stderr).toBe(0);
      expect(
        readFileSync(join(directory, 'dist/security/index.html'), 'utf8'),
      ).toContain('https://example.com/security');
      expect(
        readFileSync(join(directory, 'dist/sitemap.xml'), 'utf8'),
      ).toContain('https://example.com/features/ai-analysis');
      expect(
        readFileSync(join(directory, 'dist/robots.txt'), 'utf8'),
      ).toContain('Allow: /');
    } finally {
      rmSync(directory, { recursive: true });
    }
  });
});

it('the documented setup generates credentials and preserves them on repeat', async () => {
  const { docs } = await import('./content');
  const command = docs
    .find((doc) => doc.slug === 'getting-started')!
    .code.split('\n')[0]!
    .split(' ');
  const directory = mkdtempSync(join(tmpdir(), 'aegis-setup-guide-'));
  try {
    mkdirSync(join(directory, 'scripts'));
    writeFileSync(
      join(directory, '.env.example'),
      readFileSync(resolve('../../.env.example')),
    );
    writeFileSync(
      join(directory, 'scripts/setup_env.py'),
      readFileSync(resolve('../../scripts/setup_env.py')),
    );
    const run = () =>
      spawnSync(command[0]!, command.slice(1), {
        cwd: directory,
        encoding: 'utf8',
      });
    expect(run().status).toBe(0);
    const first = readFileSync(join(directory, '.env'), 'utf8');
    expect(first).toMatch(/POSTGRES_PASSWORD=[a-f0-9]{48}/);
    expect(first).toMatch(/REDIS_PASSWORD=[a-f0-9]{48}/);
    expect(run().status).toBe(0);
    expect(readFileSync(join(directory, '.env'), 'utf8')).toBe(first);
  } finally {
    rmSync(directory, { recursive: true });
  }
});
