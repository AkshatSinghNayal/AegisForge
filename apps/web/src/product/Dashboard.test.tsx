import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import Dashboard from './Dashboard';
import { csvCell } from './analyticsModels';
import { ApiError, request } from './client';
vi.mock('./client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./client')>()),
  request: vi.fn(),
}));
const empty = {
  generated_at: '2026-09-11T00:00:00Z',
  date_from: '2026-08-12T00:00:00Z',
  date_to: '2026-09-11T00:00:00Z',
  timezone: 'UTC',
  excluded_scans: 2,
  metrics: [
    { label: 'Policy pass rate', value: null, unit: '%' },
    { label: 'Mean time to resolution', value: null, unit: 'hours' },
  ],
  severity: [],
  owasp: [],
  exclusions: [],
  categories: [],
  lifecycle: [],
  duration: [],
  completion: [],
  risk: [],
  risk_total: 0,
  activity: [],
  action_items: [],
  actions: [],
};
beforeEach(() => {
  vi.mocked(request).mockReset();
  vi.mocked(request).mockImplementation(async (path) =>
    path.includes('/analytics/') ? empty : [],
  );
});
it('shows empty, partial and stale data honestly, omitting invalid MTTR', async () => {
  render(
    <MemoryRouter>
      <Dashboard org="org" />
    </MemoryRouter>,
  );
  await screen.findByText('Insufficient data');
  expect(screen.getByText(/2 scans excluded/)).toBeVisible();
  expect(screen.queryByText('Mean time to resolution')).not.toBeInTheDocument();
  expect(screen.getByText(/Stale data/)).toBeVisible();
  expect(screen.getByText('No targets match these filters.')).toBeVisible();
});
it('retries errors and communicates permission denial', async () => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.includes('/analytics/')) throw new ApiError(403, 'Forbidden');
    return [];
  });
  render(
    <MemoryRouter>
      <Dashboard org="org" />
    </MemoryRouter>,
  );
  await screen.findByText(/Permission denied/);
  vi.mocked(request).mockImplementation(async (path) =>
    path.includes('/analytics/') ? empty : [],
  );
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await screen.findByText('No scans in this window.');
});
it('sends the same URL filters in a single aggregate request', async () => {
  render(
    <MemoryRouter
      initialEntries={[
        '/?project=p&target=t&date_from=2026-09-01T00%3A00%3A00Z&timezone=UTC',
      ]}
    >
      <Dashboard org="org" />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      expect.stringContaining(
        'project=p&target=t&date_from=2026-09-01T00%3A00%3A00Z',
      ),
      expect.anything(),
    ),
  );
});
it('keeps URL-selected records visible when they are beyond the loaded option page', async () => {
  render(
    <MemoryRouter initialEntries={['/?project=project-201&target=target-201']}>
      <Dashboard org="org" />
    </MemoryRouter>,
  );
  await screen.findByText('No scans in this window.');
  expect(screen.getByRole('combobox', { name: 'Project' })).toHaveValue(
    'project-201',
  );
  expect(screen.getByRole('combobox', { name: 'Target' })).toHaveValue(
    'target-201',
  );
  await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await screen.findByText('No scans in this window.');
  expect(screen.getByRole('combobox', { name: 'Target' })).toHaveValue(
    'target-201',
  );
});
it('quotes CSV and neutralizes spreadsheet formulas', () => {
  expect(csvCell('=1+2')).toBe('"\'=1+2"');
  expect(csvCell('hello,"world"')).toBe('"hello,""world"""');
  expect(csvCell(5)).toBe('"5"');
});

it('links actions to the affected record and keeps organization scope', async () => {
  vi.mocked(request).mockImplementation(async (path) =>
    path.includes('/analytics/')
      ? {
          ...empty,
          action_items: [
            { label: 'Review failed scan', path: '/app/scans/scan-id' },
            {
              label: 'Review finding',
              path: '/app/findings?finding=finding-id',
            },
          ],
        }
      : [],
  );
  render(
    <MemoryRouter>
      <Dashboard org="org" />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole('link', { name: 'Review failed scan' }),
  ).toHaveAttribute('href', '/app/scans/scan-id?organization=org');
  expect(screen.getByRole('link', { name: 'Review finding' })).toHaveAttribute(
    'href',
    '/app/findings?finding=finding-id&organization=org',
  );
});
