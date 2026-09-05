import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type TextareaHTMLAttributes,
  type SelectHTMLAttributes,
} from 'react';
import { Link } from 'react-router-dom';
export function Wordmark() {
  return (
    <span className="wordmark">
      <svg
        width="32"
        height="36"
        viewBox="0 0 32 36"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M16 2 29 7v13L16 33 3 20V7Z"
          stroke="currentColor"
          strokeWidth="2"
        />
        <path d="M8 12h16l-4 5h-3v5h5v3H10v-3h4v-5h-3Z" fill="currentColor" />
      </svg>
      Aegis<span>Forge</span>
    </span>
  );
}
export function Button({
  className = '',
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
}) {
  return (
    <button
      type="button"
      className={`button ${variant} ${className}`}
      {...props}
    />
  );
}
export function IconButton({
  label,
  children,
  ...props
}: Parameters<typeof Button>[0] & { label: string }) {
  return (
    <Button aria-label={label} {...props}>
      {children}
    </Button>
  );
}
export function LinkButton({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link className="button secondary" to={to}>
      {children}
    </Link>
  );
}
export function Input({
  label,
  error,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined}
        {...props}
      />
      {error && (
        <span id={`${id}-error`} className="error-text">
          {error}
        </span>
      )}
    </div>
  );
}
export function Textarea({
  label,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea id={id} {...props} />
    </div>
  );
}
export function Select({
  label,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} {...props} />
    </div>
  );
}
export function Checkbox({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="choice">
      <input type="checkbox" {...props} />
      {label}
    </label>
  );
}
export function RadioGroup({
  label,
  options,
  name,
}: {
  label: string;
  options: string[];
  name: string;
}) {
  return (
    <fieldset>
      <legend>{label}</legend>
      {options.map((o) => (
        <label className="choice" key={o}>
          <input type="radio" name={name} value={o} />
          {o}
        </label>
      ))}
    </fieldset>
  );
}
export function Tabs({
  items,
}: {
  items: { label: string; content: ReactNode }[];
}) {
  const [active, setActive] = useState(0);
  const id = useId();
  return (
    <div>
      <div role="tablist" aria-label="Views" className="tabs">
        {items.map((item, i) => (
          <button
            key={item.label}
            role="tab"
            id={`${id}-tab-${i}`}
            aria-controls={`${id}-panel-${i}`}
            aria-selected={i === active}
            tabIndex={i === active ? 0 : -1}
            onClick={() => setActive(i)}
            onKeyDown={(e) => {
              let next: number;
              if (e.key === 'ArrowRight') next = (i + 1) % items.length;
              else if (e.key === 'ArrowLeft')
                next = (i + items.length - 1) % items.length;
              else if (e.key === 'Home') next = 0;
              else if (e.key === 'End') next = items.length - 1;
              else return;
              e.preventDefault();
              setActive(next);
              document.getElementById(`${id}-tab-${next}`)?.focus();
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      {items.map((item, i) => (
        <div
          key={item.label}
          id={`${id}-panel-${i}`}
          role="tabpanel"
          aria-labelledby={`${id}-tab-${i}`}
          tabIndex={0}
          hidden={i !== active}
          className="tab-panel"
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}
export function Dialog({
  open,
  onClose,
  title,
  children,
  drawer = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  drawer?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (open) {
      const previous = document.activeElement as HTMLElement;
      dialog?.showModal();
      const overflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      return () => {
        dialog?.close();
        document.body.style.overflow = overflow;
        previous?.focus();
      };
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      data-lenis-prevent=""
      className={drawer ? 'drawer' : ''}
      aria-labelledby={id}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const focusable = Array.from(
          event.currentTarget.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
          ),
        ).filter((element) => element.getClientRects().length > 0);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="dialog-inner">
        <div className="row between">
          <h2 id={id}>{title}</h2>
          <IconButton label="Close" variant="ghost" onClick={onClose}>
            ×
          </IconButton>
        </div>
        {children}
      </div>
    </dialog>
  );
}
export function Drawer(props: Omit<Parameters<typeof Dialog>[0], 'drawer'>) {
  return <Dialog {...props} drawer />;
}
export function Popover({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <span className="popover-wrap">
      <Button variant="secondary" popoverTarget={id}>
        {label}
      </Button>
      <div id={id} popover="auto" className="popover-content">
        {children}
      </div>
    </span>
  );
}
export function Tooltip({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const id = useId();
  const [dismissed, setDismissed] = useState(false);
  return (
    <span
      className={`tooltip-wrap ${dismissed ? 'dismissed' : ''}`}
      onMouseEnter={() => setDismissed(false)}
      onFocus={() => setDismissed(false)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setDismissed(true);
      }}
    >
      <button className="button ghost" aria-describedby={id}>
        {children}
      </button>
      <span id={id} role="tooltip">
        {label}
      </span>
    </span>
  );
}
export function Dropdown({
  label,
  items,
}: {
  label: string;
  items: { label: string; onSelect: () => void }[];
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLElement>('[role=menuitem]')?.focus();
    const close = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);
  return (
    <div
      ref={root}
      className="dropdown"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          setOpen(false);
          trigger.current?.focus();
        }
        if (e.key === 'Tab') setOpen(false);
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) && open) {
          e.preventDefault();
          const els = Array.from(
            root.current!.querySelectorAll<HTMLElement>('[role=menuitem]'),
          );
          const i = els.indexOf(document.activeElement as HTMLElement);
          els[
            e.key === 'Home'
              ? 0
              : e.key === 'End'
                ? els.length - 1
                : (i + (e.key === 'ArrowDown' ? 1 : els.length - 1)) %
                  els.length
          ]?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        className="button secondary"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        {label} <span aria-hidden="true">↓</span>
      </button>
      {open && (
        <div role="menu" id={id} aria-label={label} className="menu">
          {items.map((item) => (
            <button
              role="menuitem"
              tabIndex={-1}
              key={item.label}
              onClick={() => {
                item.onSelect();
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
export function Toast({
  message,
  onClose,
}: {
  message: string;
  onClose: () => void;
}) {
  return (
    <div className="toast">
      <span role="status">{message}</span>
      <IconButton
        label="Dismiss notification"
        variant="ghost"
        onClick={onClose}
      >
        ×
      </IconButton>
    </div>
  );
}
export function Badge({ children }: { children: ReactNode }) {
  return <span className="badge">{children}</span>;
}
export function Card({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`card ${className}`}>{children}</div>;
}
export function DataTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: string[];
  rows: ReactNode[][];
}) {
  return (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th scope="col" key={c}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Skeleton({ label = 'Loading content' }: { label?: string }) {
  return <div role="status" aria-label={label} className="skeleton" />;
}
export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span aria-hidden="true">◇</span>
      <h3>{title}</h3>
      {children}
    </div>
  );
}
export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="error-state">
      <p role="alert">{message}</p>
      <Button variant="secondary" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
export function StatusDot({ label }: { label: string }) {
  return (
    <span className="status">
      <span aria-hidden="true" />
      {label}
    </span>
  );
}
export function SeverityBadge({
  severity,
}: {
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
}) {
  return <span className={`badge severity ${severity}`}>{severity}</span>;
}
export function CopyButton({ text }: { text: string }) {
  const [status, setStatus] = useState('Copy');
  return (
    <Button
      variant="ghost"
      onClick={() => {
        void navigator.clipboard.writeText(text).then(
          () => setStatus('Copied'),
          () => setStatus('Copy unavailable'),
        );
      }}
    >
      <span role="status">{status}</span>
    </Button>
  );
}
export function CodeBlock({ code }: { code: string }) {
  return (
    <div className="code-block">
      <CopyButton text={code} />
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}
export function TerminalPanel({ children }: { children: ReactNode }) {
  return (
    <div className="terminal">
      <div className="terminal-bar">
        <span aria-hidden="true">● ● ●</span>
        <span>forge / local simulation</span>
      </div>
      <pre>{children}</pre>
    </div>
  );
}
export function Stepper({
  steps,
  current,
}: {
  steps: string[];
  current: number;
}) {
  return (
    <ol className="stepper">
      {steps.map((step, i) => (
        <li key={step} aria-current={i === current ? 'step' : undefined}>
          <span>{String(i + 1).padStart(2, '0')}</span>
          {step}
        </li>
      ))}
    </ol>
  );
}
export function Accordion({
  items,
}: {
  items: { title: string; content: ReactNode }[];
}) {
  return (
    <div className="accordion">
      {items.map((item) => (
        <details key={item.title}>
          <summary>{item.title}</summary>
          <div>{item.content}</div>
        </details>
      ))}
    </div>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-header">
      <p className="eyebrow">{eyebrow}</p>
      <div className="row between">
        <h1>{title}</h1>
        {action}
      </div>
      <p>{description}</p>
    </header>
  );
}
