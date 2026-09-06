import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { App } from '@/App';
import { envSchema } from '@/env';
describe('foundation', () => {
  it.each([
    [200, 'ready', 'API, PostgreSQL and Redis are ready.'],
    [503, 'unavailable', 'API or dependencies unavailable.'],
    [200, 'invalid', 'API or dependencies unavailable.'],
  ])('renders real health (%s/%s)', async (status, value, message) => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status: value }), { status }),
        ),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App />
      </QueryClientProvider>,
    );
    expect(
      screen.getByRole('heading', { name: 'Service health' }),
    ).toBeInTheDocument();
    expect(await screen.findByText(message)).toBeInTheDocument();
  });
  it('rejects malformed origins without throwing', () => {
    expect(envSchema.safeParse({ VITE_SITE_URL: 'not-a-url' }).success).toBe(
      false,
    );
  });
  it('rejects unsafe public configuration', () => {
    for (const value of [
      'javascript:alert(1)',
      'https://user:secret@example.com',
      'https://example.com/path',
      'https://example.com/?token=x',
    ])
      expect(envSchema.safeParse({ VITE_SITE_URL: value }).success).toBe(false);
    expect(
      envSchema.safeParse({
        VITE_SECURITY_CONTACT: 'a@example.com\\r\\nBcc:evil@example.com',
      }).success,
    ).toBe(false);
    expect(
      envSchema.safeParse({
        VITE_SITE_URL: 'https://example.com',
        VITE_SECURITY_CONTACT: 'security@example.com',
      }).success,
    ).toBe(true);
  });
  it('rejects unsafe API schemes', () => {
    expect(
      envSchema.safeParse({ VITE_API_BASE_URL: 'javascript:alert(1)' }).success,
    ).toBe(false);
  });
});
