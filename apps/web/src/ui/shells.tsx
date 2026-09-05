import { useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import Lenis from 'lenis';
import { Drawer, IconButton, Wordmark } from './index';
const navigation = [
  { to: '/dev/ui', label: 'UI library' },
  { to: '/dev/motion', label: 'Motion lab' },
  { to: '/status', label: 'Service health' },
];
function Navigation({ onNavigate }: { onNavigate?: (() => void) | undefined }) {
  return (
    <nav aria-label="Main navigation">
      {navigation.map((item) => (
        <NavLink onClick={onNavigate} key={item.to} to={item.to}>
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
export function MarketingHeader() {
  const [open, setOpen] = useState(false);
  return (
    <header className="marketing-header">
      <Link to="/dev/ui" aria-label="AegisForge UI library">
        <Wordmark />
      </Link>
      <div className="desktop-nav">
        <Navigation />
      </div>
      <div className="mobile-nav">
        <IconButton
          label="Open navigation"
          variant="secondary"
          onClick={() => setOpen(true)}
        >
          ☰
        </IconButton>
      </div>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Explore AegisForge"
      >
        <Navigation onNavigate={() => setOpen(false)} />
      </Drawer>
    </header>
  );
}
export function MarketingFooter() {
  return (
    <footer className="marketing-footer">
      <Wordmark />
      <p>Forged with intent. Built for clarity.</p>
      <Link to="/dev/ui">Design system ↗</Link>
      <span>Development laboratory · 2026</span>
    </footer>
  );
}
export function PublicLayout({ children }: { children: ReactNode }) {
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    let lenis: Lenis | undefined;
    const update = () => {
      lenis?.destroy();
      lenis = undefined;
      if (!media.matches) lenis = new Lenis({ autoRaf: true, anchors: true });
    };
    update();
    media.addEventListener('change', update);
    return () => {
      media.removeEventListener('change', update);
      lenis?.destroy();
    };
  }, []);
  return (
    <div className="public-layout">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <MarketingHeader />
      {children}
      <MarketingFooter />
    </div>
  );
}
export function AppSidebar({
  onNavigate,
}: {
  onNavigate?: (() => void) | undefined;
}) {
  return (
    <aside className="app-sidebar">
      <Wordmark />
      <p className="eyebrow">WORKSPACE / DESIGN LAB</p>
      <Navigation onNavigate={onNavigate} />
      <div className="sidebar-note">
        <span className="status">
          <span />
          Local environment
        </span>
        <p>
          Component specimens.
          <br />
          No scan data.
        </p>
      </div>
    </aside>
  );
}
export function AppTopbar({ onMenu }: { onMenu: () => void }) {
  return (
    <header className="app-topbar">
      <div className="mobile-nav">
        <IconButton label="Open sidebar" variant="secondary" onClick={onMenu}>
          ☰
        </IconButton>
      </div>
      <span>
        Workspace <span className="muted">/</span> Design system
      </span>
      <span className="badge">DEV ONLY</span>
    </header>
  );
}
export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)');
    const close = () => {
      if (media.matches) setOpen(false);
    };
    media.addEventListener('change', close);
    return () => media.removeEventListener('change', close);
  }, []);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="desktop-sidebar">
        <AppSidebar />
      </div>
      <div className="app-body">
        <AppTopbar onMenu={() => setOpen(true)} />
        {children}
      </div>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Workspace navigation"
      >
        <AppSidebar onNavigate={() => setOpen(false)} />
      </Drawer>
    </div>
  );
}
