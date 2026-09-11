import { StrictMode } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import Configuration from './Configuration';
import { request } from './client';
vi.mock('./client', () => ({
  request: vi.fn(async (path: string) => {
    if (path.endsWith('/projects'))
      return [{ id: 'project', name: 'Synthetic project', status: 'active' }];
    if (path.endsWith('/policies'))
      return [{ id: 'policy', name: 'Baseline', version: 1, mode: 'baseline' }];
    if (path.endsWith('/configuration-identity'))
      return { member_id: 'member' };
    throw new Error('Unexpected request');
  }),
}));
it('preserves submitted wizard fields across deferred React updates and gates validation on consent', async () => {
  const user = userEvent.setup({ delay: null });
  render(
    <StrictMode>
      <MemoryRouter initialEntries={['/app/targets/new']}>
        <Routes>
          <Route
            path="/app/*"
            element={<Configuration org="org" role="owner" userId="user" />}
          />
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  );
  await screen.findByRole('option', { name: 'Synthetic project' });
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Project' }),
    'project',
  );
  await user.type(screen.getByLabelText('Display name'), 'Synthetic target');
  await user.type(
    screen.getByLabelText('Base URL'),
    'https://synthetic.example/',
  );
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Policy version' }),
    'policy',
  );
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await user.type(
    screen.getByLabelText('Authorization declaration'),
    'I own this synthetic target and authorize validation.',
  );
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  expect(screen.getByText('https://synthetic.example/')).toBeVisible();
  expect(
    screen.getByRole('button', { name: 'Validate URL and OpenAPI' }),
  ).toBeDisabled();
  await user.click(screen.getByRole('checkbox'));
  expect(
    screen.getByRole('button', { name: 'Validate URL and OpenAPI' }),
  ).toBeEnabled();
  expect(
    screen.getByRole('button', { name: 'Authorize and register target' }),
  ).toBeDisabled();
});

it('clears the previous target when a new target request fails', async () => {
  vi.mocked(request)
    .mockResolvedValueOnce({
      id: 'a',
      project_id: 'p',
      display_name: 'Old target',
      kind: 'web_url',
      base_url: 'https://old.example/',
      environment: 'development',
      policy_id: null,
      consent_at: null,
      authorization_owner_id: null,
      authorization_declaration: '',
      inclusion_patterns: [],
      exclusion_patterns: [],
      allowed_methods: [],
      rate_limit: 2,
      timeout_seconds: 300,
      status: 'active',
      version: 1,
      verified_at: null,
      has_openapi: false,
      credentials: [],
    })
    .mockRejectedValueOnce(new Error('Target not found.'));
  const user = userEvent.setup({ delay: null });
  render(
    <MemoryRouter initialEntries={['/app/targets/a']}>
      <Link to="/app/targets/missing">Missing target</Link>
      <Routes>
        <Route
          path="/app/*"
          element={<Configuration org="org" role="viewer" userId="user" />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole('heading', { name: 'Old target' }),
  ).toBeVisible();
  await user.click(screen.getByRole('link', { name: 'Missing target' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Target not found.',
  );
  expect(
    screen.queryByRole('heading', { name: 'Old target' }),
  ).not.toBeInTheDocument();
});

it('keeps a heading during project-settings loading and offers retry on failure', async () => {
  let reject: (reason: Error) => void = () => {};
  vi.mocked(request).mockImplementationOnce(
    () =>
      new Promise((_resolve, fail) => {
        reject = fail;
      }),
  );
  render(
    <MemoryRouter initialEntries={['/app/projects/project/settings']}>
      <Routes>
        <Route
          path="/app/*"
          element={<Configuration org="org" role="owner" userId="user" />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(
    screen.getByRole('heading', { name: 'Project settings' }),
  ).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('Loading');
  reject(new Error('Settings unavailable'));
  await screen.findByText('Settings unavailable');
  expect(screen.getByRole('button', { name: 'Retry' })).toBeVisible();
});
