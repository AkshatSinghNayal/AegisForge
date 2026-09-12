import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { z } from 'zod';
import { request } from './client';
import { usePagedOptions } from './usePagedOptions';
import { MoreOptions } from './PagedOptions';
vi.mock('./client', () => ({ request: vi.fn() }));
const schema = z.array(z.object({ id: z.string() }));
const first = Array.from({ length: 200 }, (_, n) => ({ id: String(n) }));
function Harness({ path = '/options' }: { path?: string }) {
  const options = usePagedOptions(path, schema);
  return (
    <>
      <select aria-label="Record">
        {options.data?.map((r) => (
          <option key={r.id}>{r.id}</option>
        ))}
      </select>
      <MoreOptions label="records" options={options} />
    </>
  );
}
beforeEach(() => {
  vi.mocked(request).mockReset();
});
it('reaches record 201 and keeps earlier choices when the next page fails then retries', async () => {
  let failing = true;
  vi.mocked(request).mockImplementation(async (path) => {
    if (!path.includes('offset=')) return first;
    if (failing) throw new Error('Page unavailable');
    return [{ id: '200' }];
  });
  render(<Harness />);
  await userEvent.click(
    await screen.findByRole('button', { name: 'Load more records' }),
  );
  await screen.findByRole('alert');
  expect(screen.getAllByRole('option')).toHaveLength(200);
  failing = false;
  await userEvent.click(screen.getByRole('button', { name: 'Retry records' }));
  await userEvent.selectOptions(
    screen.getByRole('combobox'),
    await screen.findByRole('option', { name: '200' }),
  );
  expect(screen.getByRole('combobox')).toHaveValue('200');
  expect(screen.getAllByRole('option')).toHaveLength(201);
  expect(
    screen.queryByRole('button', { name: 'Load more records' }),
  ).not.toBeInTheDocument();
  expect(request).toHaveBeenLastCalledWith('/options?offset=200', schema);
});
it('handles exactly 200 rows with an explicit empty final page', async () => {
  vi.mocked(request).mockImplementation(async (path) =>
    path.includes('offset=') ? [] : first,
  );
  render(<Harness />);
  await userEvent.click(
    await screen.findByRole('button', { name: 'Load more records' }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: 'Load more records' }),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getAllByRole('option')).toHaveLength(200);
});
it('resets pagination for project or organization changes and ignores late responses', async () => {
  let finish: (value: { id: string }[]) => void = () => {};
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.includes('offset='))
      return new Promise((resolve) => {
        finish = resolve;
      });
    return path === '/a?project=one' ? first : [{ id: 'other-scope' }];
  });
  const view = render(<Harness path="/a?project=one" />);
  await userEvent.click(
    await screen.findByRole('button', { name: 'Load more records' }),
  );
  view.rerender(<Harness path="/b?project=two" />);
  await screen.findByRole('option', { name: 'other-scope' });
  finish([{ id: 'late-old-scope' }]);
  await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(1));
  expect(
    screen.queryByRole('option', { name: 'late-old-scope' }),
  ).not.toBeInTheDocument();
  view.rerender(<Harness path="/a?project=one" />);
  await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(200));
  expect(request).toHaveBeenLastCalledWith('/a?project=one', schema);
});
