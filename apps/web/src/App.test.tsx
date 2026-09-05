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
  it('rejects unsafe API schemes', () => {
    expect(
      envSchema.safeParse({ VITE_API_BASE_URL: 'javascript:alert(1)' }).success,
    ).toBe(false);
  });
});
