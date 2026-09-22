import { render, screen, fireEvent } from '@testing-library/react';
import { vi, test, expect, beforeEach } from 'vitest';
import GitHubIntegration from './GitHubIntegration';
import { request } from './client';
vi.mock('./client', () => ({ request: vi.fn() }));
const mocked = vi.mocked(request);
const id = '10000000-0000-4000-8000-000000000001';
const row = {
  id,
  integration_id: id,
  repository: 'owner/repo',
  branch: 'main',
  project_id: id,
  target_id: id,
  policy_id: id,
  target_version: 1,
  policy_version: 1,
  gate_policy_version: 1,
  environment: 'development',
  events: ['push'],
  enabled: true,
  webhook_path: `/api/hooks/github/${id}`,
};
beforeEach(() => {
  mocked.mockReset();
});
test('mapping creation, secret dismissal, readiness check and disable', async () => {
  let created = false;
  mocked.mockImplementation(async (path, _schema, method) => {
    if (path.includes('/test'))
      return { ok: true, message: 'Local readiness verified.' };
    if (method === 'DELETE') return { ok: true };
    if (method === 'POST') {
      created = true;
      return { ...row, secret: 'synthetic-webhook-once' };
    }
    return path.includes('/mappings') && created ? [row] : [];
  });
  render(<GitHubIntegration org={id} />);
  fireEvent.change(screen.getByLabelText('Repository (owner/repo)'), {
    target: { value: 'owner/repo' },
  });
  for (const label of [
    'Project ID',
    'Registered target ID',
    'Passive scanner policy ID',
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value: id } });
  fireEvent.click(
    screen.getByRole('button', { name: 'Create GitHub mapping' }),
  );
  expect(await screen.findByLabelText('One-time webhook secret')).toHaveValue(
    'synthetic-webhook-once',
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Dismiss webhook secret' }),
  );
  expect(screen.queryByDisplayValue('synthetic-webhook-once')).toBeNull();
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Test connection for owner/repo',
    }),
  );
  expect(await screen.findByText('Local readiness verified.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Disable owner/repo' }));
  expect(await screen.findByText('Mapping disabled.')).toBeVisible();
  expect(mocked).toHaveBeenCalledWith(
    `/workspace/integrations/${id}?organization_id=${id}`,
    expect.anything(),
    'DELETE',
  );
});
test('load failure is reported without claiming an empty history', async () => {
  mocked.mockRejectedValue(new Error('Unavailable'));
  render(<GitHubIntegration org={id} />);
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(screen.queryByText('No GitHub deliveries on this page.')).toBeNull();
});
