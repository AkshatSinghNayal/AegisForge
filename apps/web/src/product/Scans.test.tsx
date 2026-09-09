import { expect, it } from 'vitest';
import { eventSchema, mergeEvents } from './scanEvents';
it('replay merges duplicate events without changing ordered history', () => {
  const event = (sequence: number) =>
    eventSchema.parse({
      sequence,
      stage: 'queued',
      message_code: 'queued',
      attempt: 1,
      created_at: '2026-09-08T00:00:00Z',
    });
  const first = [event(1), event(3)];
  const replayed = mergeEvents(first, event(1));
  expect(replayed).toBe(first);
  expect(mergeEvents(replayed, event(2)).map((e) => e.sequence)).toEqual([
    1, 2, 3,
  ]);
});

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import Scans from './Scans';
import { request } from './client';
vi.mock('./client', () => ({
  scanStream: vi.fn(),
  request: vi.fn(async (path: string) => {
    if (path.endsWith('/targets'))
      return [
        {
          id: 'target',
          version: 1,
          display_name: 'Fixture',
          environment: 'development',
          status: 'active',
          policy_id: 'policy',
          credentials: [],
        },
      ];
    if (path.endsWith('/policies'))
      return [{ id: 'policy', name: 'Baseline', version: 1, mode: 'baseline' }];
    if (path.startsWith('/scans?')) return { id: 'scan' };
    throw new Error('Unexpected request');
  }),
}));
it('reviews a target and submits with an idempotency key', async () => {
  const user = userEvent.setup({ delay: null });
  render(
    <MemoryRouter initialEntries={['/app/scans/new']}>
      <Routes>
        <Route path="/app/*" element={<Scans org="org" role="owner" />} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByRole('option', { name: 'Fixture · development' });
  await user.selectOptions(screen.getByLabelText('Target'), 'target');
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('heading', {
    name: 'Choose an immutable policy version',
  });
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await user.type(screen.getByLabelText('Branch (optional)'), 'feature/test');
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('heading', { name: 'Final review' });
  await user.click(screen.getByRole('button', { name: 'Start scan' }));
  expect(request).toHaveBeenCalledWith(
    '/scans?organization_id=org',
    expect.anything(),
    'POST',
    expect.objectContaining({ target_id: 'target', policy_version: 1 }),
    true,
    { 'Idempotency-Key': expect.any(String) },
  );
});

it('clears an active acknowledgement when the reviewed target changes', async () => {
  vi.mocked(request)
    .mockImplementationOnce(async () =>
      ['one', 'two'].map((id) => ({
        id,
        version: 1,
        display_name: id,
        environment: 'development',
        status: 'active',
        policy_id: 'active',
        credentials: [],
      })),
    )
    .mockImplementationOnce(async () => [
      { id: 'active', name: 'Active', version: 1, mode: 'active' },
    ]);
  const user = userEvent.setup({ delay: null });
  render(
    <MemoryRouter initialEntries={['/app/scans/new']}>
      <Routes>
        <Route path="/app/*" element={<Scans org="org" role="owner" />} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByRole('option', { name: 'one · development' });
  await user.selectOptions(screen.getByLabelText('Target'), 'one');
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await user.click(screen.getByRole('checkbox'));
  expect(screen.getByRole('checkbox')).toBeChecked();
  await user.click(screen.getByRole('button', { name: 'Back' }));
  await user.click(screen.getByRole('button', { name: 'Back' }));
  await user.selectOptions(screen.getByLabelText('Target'), 'two');
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  await user.click(screen.getByRole('button', { name: 'Continue' }));
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});
