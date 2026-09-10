import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, test, expect, beforeEach } from 'vitest';
import AIGuidance from './AIGuidance';
import { request } from './client';
vi.mock('./client', () => ({ request: vi.fn() }));
const requestMock = vi.mocked(request);
const hostile = '<img src=x onerror="window.compromised=true">';
const row = {
  id: 'version-1',
  occurrence_id: 'evidence-1',
  provider: 'mock',
  model: 'demo-v1',
  schema_version: 'v1',
  prompt_version: 'v1',
  status: 'mock',
  generated_at: null,
  output: {
    summary: hostile,
    vulnerability_explanation: 'Explanation',
    root_cause_hypothesis: 'Hypothesis requiring review',
    technical_impact: 'Unknown technical impact',
    business_impact: 'Unknown business impact',
    remediation_steps: ['Review implementation'],
    verification_steps: ['Run authorized scan'],
    evidence_ids: ['evidence-1'],
    cwe_interpretation: 'CWE',
    owasp_mapping_interpretation: 'OWASP',
    model_confidence: 0.2,
    uncertainty_notes: ['Unverified'],
  },
  feedback: [],
};
beforeEach(() => {
  requestMock.mockReset();
});
test('escapes guidance and feedback, opens evidence, and keeps checklist local', async () => {
  requestMock.mockResolvedValue([
    { ...row, feedback: [{ id: 'f', useful: false, note: hostile }] },
  ]);
  const cite = vi.fn();
  const { container } = render(
    <AIGuidance org="org" finding="finding" role="owner" cite={cite} />,
  );
  await screen.findByText(hostile, { exact: true });
  expect(container.querySelector('img,script')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: /View occurrence/ }));
  expect(cite).toHaveBeenCalledWith('evidence-1');
  fireEvent.click(screen.getByRole('checkbox'));
  expect(requestMock).toHaveBeenCalledTimes(1);
});
test('authorized regeneration retains prior version and saves explicit feedback', async () => {
  requestMock
    .mockResolvedValueOnce([row])
    .mockResolvedValueOnce({ ...row, id: 'version-2' })
    .mockResolvedValueOnce([{ ...row, id: 'version-2' }, row]);
  render(
    <AIGuidance org="org" finding="finding" role="owner" cite={vi.fn()} />,
  );
  fireEvent.click(
    await screen.findByRole('button', { name: 'Regenerate guidance' }),
  );
  await waitFor(() =>
    expect(screen.getAllByText(/Version ID:/)).toHaveLength(2),
  );
  requestMock
    .mockResolvedValueOnce({ id: 'feedback' })
    .mockResolvedValueOnce([row]);
  fireEvent.change(screen.getAllByLabelText('Reviewer note')[0]!, {
    target: { value: 'Useful context' },
  });
  fireEvent.click(screen.getAllByRole('button', { name: 'Save feedback' })[0]!);
  await screen.findByText(/Feedback saved for review/);
  expect(requestMock).toHaveBeenCalledWith(
    expect.stringContaining('/feedback?'),
    expect.anything(),
    'POST',
    { useful: true, note: 'Useful context' },
  );
});
test('viewer sees degradation and prior versions without write controls', async () => {
  requestMock.mockResolvedValue([
    { ...row, status: 'degraded', output: null },
    row,
  ]);
  render(
    <AIGuidance org="org" finding="finding" role="viewer" cite={vi.fn()} />,
  );
  await screen.findByText(/Enrichment is unavailable/);
  expect(
    screen.queryByRole('button', { name: 'Regenerate guidance' }),
  ).toBeNull();
  expect(screen.queryByRole('button', { name: 'Save feedback' })).toBeNull();
  expect(screen.getAllByText(/Version ID:/)).toHaveLength(2);
});

test('a failed feedback write clears a previous success notice', async () => {
  requestMock
    .mockResolvedValueOnce([row])
    .mockResolvedValueOnce({ id: 'feedback-1' })
    .mockResolvedValueOnce([row]);
  render(
    <AIGuidance org="org" finding="finding" role="owner" cite={vi.fn()} />,
  );
  fireEvent.click(await screen.findByRole('button', { name: 'Save feedback' }));
  await screen.findByText(/Feedback saved for review/);
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Save feedback' }),
    ).not.toBeDisabled(),
  );
  requestMock.mockRejectedValueOnce(new Error('Write failed'));
  fireEvent.click(screen.getByRole('button', { name: 'Save feedback' }));
  await screen.findByText('Write failed');
  expect(screen.queryByText(/Feedback saved for review/)).toBeNull();
});
