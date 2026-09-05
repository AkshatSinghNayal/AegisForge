import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { Accordion, Dialog, Dropdown, Tabs } from './index';
import { AppShell } from './shells';
describe('component interactions', () => {
  it('switches tabs with arrows and Home/End', async () => {
    const user = userEvent.setup();
    render(
      <Tabs
        items={[
          { label: 'First', content: 'First panel' },
          { label: 'Second', content: 'Second panel' },
        ]}
      />,
    );
    await user.click(screen.getByRole('tab', { name: 'First' }));
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Second' })).toHaveFocus();
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Second panel');
    await user.keyboard('{Home}');
    expect(screen.getByRole('tab', { name: 'First' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Second' })).toHaveFocus();
  });
  it('selects dropdown items with keyboard and restores focus', async () => {
    const user = userEvent.setup();
    const select = vi.fn();
    render(
      <Dropdown
        label="Actions"
        items={[
          { label: 'One', onSelect: select },
          { label: 'Two', onSelect: select },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Actions' }));
    expect(screen.getByRole('menuitem', { name: 'One' })).toHaveFocus();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(select).toHaveBeenCalledOnce();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Actions' })).toHaveFocus();
    await user.keyboard('{ArrowDown}{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
  it('opens and closes an accordion disclosure', async () => {
    const user = userEvent.setup();
    render(
      <Accordion items={[{ title: 'Details', content: 'Expanded content' }]} />,
    );
    const summary = screen.getByText('Details');
    await user.click(summary);
    expect(summary.parentElement).toHaveAttribute('open');
    await user.click(summary);
    expect(summary.parentElement).not.toHaveAttribute('open');
  });
  it('synchronizes modal state and restores the invoking element', () => {
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute('open');
    };
    const trigger = document.createElement('button');
    document.body.append(trigger);
    trigger.focus();
    const { rerender } = render(
      <Dialog open title="Review" onClose={() => {}}>
        Content
      </Dialog>,
    );
    expect(screen.getByRole('dialog')).toHaveAccessibleName('Review');
    rerender(
      <Dialog open={false} title="Review" onClose={() => {}}>
        Content
      </Dialog>,
    );
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
    trigger.remove();
  });
  it('opens the sidebar and closes it after navigation', async () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute('open');
    };
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AppShell>
          <main>Body</main>
        </AppShell>
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: 'Open sidebar' }));
    expect(screen.getByRole('dialog')).toHaveAccessibleName(
      'Workspace navigation',
    );
    const dialog = screen.getByRole('dialog');
    await user.click(
      Array.from(dialog.querySelectorAll('a')).find(
        (a) => a.textContent === 'Motion lab',
      )!,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
