import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import Policies from './Policies';
import { request } from './client';
vi.mock('./client', () => ({ request: vi.fn(), messageSchema: {} }));
beforeEach(() => {
  vi.mocked(request).mockReset();
  vi.mocked(request).mockImplementation(async (path: string) => {
    if (path.endsWith('/projects'))
      return [{ id: 'project', name: 'Synthetic project' }];
    return { active_id: null, versions: [] };
  });
});
it('developer reads policy without publication or activation controls', async () => {
  render(
    <MemoryRouter>
      <Policies org="org" role="developer" />
    </MemoryRouter>,
  );
  await screen.findByRole('heading', { name: 'Published versions' });
  expect(
    screen.queryByRole('button', { name: 'Publish version' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Activate selected version' }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: 'Preview selected policy' }),
  ).toBeDisabled();
});
it('builder retains comma lists and submits structured conditions', async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <Policies org="org" role="owner" />
    </MemoryRouter>,
  );
  await screen.findByRole('heading', { name: 'Publish a new version' });
  await user.type(screen.getByLabelText('owasp'), 'A01:2021, A03:2021');
  await user.selectOptions(
    screen.getByLabelText('Incomplete scan outcome'),
    'fail',
  );
  await user.click(screen.getByRole('button', { name: 'Publish version' }));
  expect(
    vi.mocked(request).mock.calls.find((c) => c[2] === 'POST')?.[3],
  ).toMatchObject({
    policy: {
      incomplete_outcome: 'fail',
      rules: [{ match: { owasp: ['A01:2021', 'A03:2021'] } }],
    },
  });
});
