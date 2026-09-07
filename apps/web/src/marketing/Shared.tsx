import { env } from '@/env';
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import Lenis from 'lenis';
import { Drawer, IconButton, Wordmark } from '@/ui';
import { features } from './content';
import './marketing.css';
const RouteFocusContext = createContext<RefObject<string> | null>(null);
export function CTA() {
  return (
    <div className="m-actions">
      <Link className="button primary" to="/auth/sign-up">
        Create a workspace <span aria-hidden="true">↗</span>
      </Link>
      <Link className="button secondary" to="/platform#architecture">
        View the architecture <span aria-hidden="true">→</span>
      </Link>
    </div>
  );
}
export function FinalCTA() {
  return (
    <section className="m-final">
      <p className="eyebrow">BUILD WITH A CLEARER SIGNAL</p>
      <h2>
        From scan to understanding.
        <br />
        From understanding to action.
      </h2>
      <CTA />
      <p className="m-muted">Explore the project. Prepare your workspace.</p>
    </section>
  );
}
export function Cockpit({ step = 0 }: { step?: number }) {
  const labels = [
    'Target workspace',
    'Scan evidence',
    'Advisory analysis',
    'Policy & reports',
  ];
  return (
    <div className="cockpit">
      <div className="cockpit-bar">
        <span>◈ AEGISFORGE</span>
        <span className="mock-label">
          Illustrative interface · no scan executed
        </span>
      </div>
      <div className="cockpit-body">
        <aside aria-hidden="true">
          <span className="cockpit-project">FORGE / SANDBOX</span>
          {[
            'Overview',
            'Targets',
            'Findings',
            'Scan history',
            'Policies',
            'Reports',
          ].map((s, i) => (
            <div className={i === step + 1 ? 'selected' : ''} key={s}>
              {s}
            </div>
          ))}
        </aside>
        <div className="cockpit-content">
          <div className="cockpit-heading">
            <span>WORKSPACE / REVIEW</span>
            <span className="badge">DESIGN PREVIEW</span>
          </div>
          <h3>{labels[step]}</h3>
          <div className="mock-flow">
            <span>Discover</span>
            <i>→</i>
            <span>Scan</span>
            <i>→</i>
            <span>Explain</span>
            <i>→</i>
            <span>Enforce</span>
          </div>
          <div className="mock-evidence">
            <span className="eyebrow">
              {
                [
                  'AUTHORIZED SCOPE',
                  'SOURCE OF TRUTH',
                  'EVIDENCE-LINKED GUIDANCE',
                  'DETERMINISTIC EVALUATION',
                ][step]
              }
            </span>
            <h4>
              {
                [
                  'Your boundary comes first.',
                  'Keep the observation intact.',
                  'Advice with a source.',
                  'Rules decide. Evidence explains.',
                ][step]
              }
            </h4>
            <p>
              {
                [
                  'Target authorization → discovery → scope review',
                  'ZAP observation → redacted derivative → finding',
                  'Redacted evidence → Gemini → validated references',
                  'Completeness + policy version → reviewable result',
                ][step]
              }
            </p>
            <div className="mock-lines" aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
          </div>
          <div className="mock-bottom">
            <span>Evidence preserved</span>
            <span>AI advisory</span>
            <span>No live results</span>
          </div>
        </div>
      </div>
    </div>
  );
}
export function Metadata({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  const { pathname, hash } = useLocation();
  const previousRoute = useContext(RouteFocusContext);
  useEffect(() => {
    const key = pathname + hash;
    if (!previousRoute || previousRoute.current === key) return;
    const frame = requestAnimationFrame(() => {
      const target = hash ? document.getElementById(hash.slice(1)) : null;
      const heading =
        target?.querySelector<HTMLElement>('h1, h2') ??
        document.querySelector<HTMLElement>('main h1');
      heading?.setAttribute('tabindex', '-1');
      heading?.focus({ preventScroll: true });
      previousRoute.current = key;
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname, hash, previousRoute]);
  const origin = env.VITE_SITE_URL;
  const url = new URL(pathname.toLowerCase().replace(/\/+$/, '') || '/', origin)
    .href;
  return (
    <>
      <title>{`${title} | AegisForge`}</title>
      <meta name="description" content={description} />
      <link rel="canonical" href={url} />
      <meta property="og:title" content={`${title} | AegisForge`} />
      <meta property="og:description" content={description} />
      <meta property="og:url" content={url} />
      <meta property="og:type" content="website" />
      <meta property="og:site_name" content="AegisForge" />
      <script type="application/ld+json">
        {JSON.stringify({
          '@context': 'https://schema.org',
          '@graph': [
            { '@type': 'Organization', name: 'AegisForge', url: origin },
            {
              '@type': 'SoftwareApplication',
              name: 'AegisForge',
              applicationCategory: 'DeveloperApplication',
              operatingSystem: 'Web',
              description:
                'A research project for evidence-linked vulnerability intelligence.',
            },
          ],
        }).replace(/</g, '\u003c')}
      </script>
    </>
  );
}
export default function MarketingLayout() {
  const [open, setOpen] = useState(false);
  const [solid, setSolid] = useState(false);
  const { pathname, hash } = useLocation();
  const previousRoute = useRef(pathname + hash);
  useEffect(() => {
    const scroll = () => setSolid(window.scrollY > 24);
    scroll();
    window.addEventListener('scroll', scroll, { passive: true });
    return () => window.removeEventListener('scroll', scroll);
  }, []);
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
      lenis?.destroy();
      media.removeEventListener('change', update);
    };
  }, []);
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0);
    else
      requestAnimationFrame(() =>
        document.getElementById(hash.slice(1))?.scrollIntoView(),
      );
  }, [pathname, hash]);
  const nav = (
    <nav aria-label="Public navigation">
      {[
        ['/platform', 'Platform'],
        ['/features/web-scanning', 'Features'],
        ['/pricing', 'Pricing'],
        ['/docs', 'Docs'],
      ].map(([to, label]) => (
        <Link key={to} to={to!} onClick={() => setOpen(false)}>
          {label}
        </Link>
      ))}
    </nav>
  );
  return (
    <div className="marketing">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className={`m-nav ${solid ? 'solid' : ''}`}>
        <Link to="/" aria-label="AegisForge home">
          <Wordmark />
        </Link>
        <div className="m-desktop">
          {nav}
          <Link className="button primary" to="/auth/sign-up">
            Get started ↗
          </Link>
        </div>
        <div className="m-mobile">
          <IconButton label="Open navigation" onClick={() => setOpen(true)}>
            ☰
          </IconButton>
        </div>
      </header>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Explore AegisForge"
      >
        {nav}
        <Link to="/auth/sign-up" onClick={() => setOpen(false)}>
          Create a workspace ↗
        </Link>
      </Drawer>
      <RouteFocusContext value={previousRoute}>
        <Outlet />
      </RouteFocusContext>
      <footer className="m-footer">
        <div>
          <Wordmark />
          <p>Clarity is a security feature.</p>
          <small>
            Research project · 2026
            <br />
            Product interfaces are illustrative.
          </small>
        </div>
        <div>
          <h2>Product</h2>
          <Link to="/platform">Platform</Link>
          {features.map((f) => (
            <Link key={f.slug} to={`/features/${f.slug}`}>
              {f.title}
            </Link>
          ))}
        </div>
        <div>
          <h2>Resources</h2>
          <Link to="/docs">Documentation</Link>
          <Link to="/docs/architecture">Architecture</Link>
          <Link to="/pricing">Project packaging</Link>
          <Link to="/status">Service health</Link>
        </div>
        <div>
          <h2>Trust</h2>
          {['security', 'privacy', 'terms'].map((s) => (
            <Link to={`/${s}`} key={s}>
              {s[0]!.toUpperCase() + s.slice(1)}
            </Link>
          ))}
        </div>
      </footer>
    </div>
  );
}
