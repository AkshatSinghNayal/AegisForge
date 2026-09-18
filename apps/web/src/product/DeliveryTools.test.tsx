import { render, screen, fireEvent } from '@testing-library/react';
import { vi, test, expect, beforeEach } from 'vitest';
import DeliveryTools from './DeliveryTools';
import { request } from './client';
vi.mock('./client', () => ({ request: vi.fn() }));
const mocked = vi.mocked(request);
beforeEach(() => {
  mocked.mockReset();
});
test('key secret is shown once and removed on dismissal', async () => {
  mocked.mockResolvedValue({ secret: 'agf_SYNTHETIC_ONCE' });
  render(<DeliveryTools org="org" kind="api-keys" onChange={() => {}} />);
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'CI' } });
  fireEvent.change(screen.getByLabelText('Expires at (local time)'), {
    target: { value: '2027-01-01T00:00' },
  });
  fireEvent.click(screen.getByLabelText('scans:read'));
  fireEvent.click(screen.getByRole('button', { name: 'Create' }));
  expect(await screen.findByDisplayValue('agf_SYNTHETIC_ONCE')).toBeVisible();
  expect(mocked).toHaveBeenCalledWith(
    '/api-keys?organization_id=org',
    expect.anything(),
    'POST',
    expect.objectContaining({ name: 'CI', scopes: ['scans:read'] }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss secret' }));
  expect(screen.queryByDisplayValue('agf_SYNTHETIC_ONCE')).toBeNull();
  expect(localStorage.getItem('api-key')).toBeNull();
});
test('report request queues an explicit version and surfaces errors', async () => {
  mocked.mockRejectedValueOnce(new Error('Permission denied.'));
  render(<DeliveryTools org="org" kind="reports" onChange={() => {}} />);
  fireEvent.change(screen.getByLabelText('Scan ID'), {
    target: { value: '10000000-0000-4000-8000-000000000001' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Queue report' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Permission denied.',
  );
  mocked.mockResolvedValueOnce({ id: 'id', version: 2 });
  fireEvent.click(screen.getByRole('button', { name: 'Queue report' }));
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Report version 2 queued',
  );
});

test('notification load failure never claims an empty history', async () => {
  mocked.mockRejectedValue(new Error('Notification service unavailable.'));
  render(<DeliveryTools org="org" kind="integrations" onChange={() => {}} />);
  expect(screen.queryByText('No deliveries on this page.')).toBeNull();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Notification service unavailable.',
  );
  expect(screen.queryByText('No notification destinations.')).toBeNull();
  expect(screen.queryByText('No deliveries on this page.')).toBeNull();
});
