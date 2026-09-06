import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import Home from './Home';
import { steps } from './content';
vi.mock('gsap', () => ({
  default: {
    registerPlugin: vi.fn(),
    matchMedia: () => ({ add: vi.fn(), revert: vi.fn() }),
  },
}));
it('exposes every workflow step without requiring visual scroll progression', () => {
  const { container } = render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  );
  const workflow = screen.getByRole('list', { name: 'Complete workflow' });
  for (const step of steps) {
    expect(
      within(workflow).getByRole('heading', { name: step.title }),
    ).toBeInTheDocument();
    for (const row of step.rows)
      expect(within(workflow).getByText(row)).toBeInTheDocument();
  }
  expect(container.querySelector('.story-deck')).toHaveAttribute(
    'aria-hidden',
    'true',
  );
  expect(
    screen.queryByRole('heading', { name: 'Advisory analysis' }),
  ).not.toBeInTheDocument();
});
