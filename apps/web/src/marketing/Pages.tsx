import { Link, useLocation } from 'react-router-dom';
import { Cockpit, CTA, FinalCTA, Metadata } from './Shared';
import { features, steps } from './content';
export default function Pages() {
  const { pathname: routePath } = useLocation();
  const pathname = routePath.replace(/\/+$/, '');
  const feature = features.find((f) => pathname === `/features/${f.slug}`);
  if (feature)
    return (
      <main id="main">
        <Metadata title={feature.title} description={feature.problem} />
        <section className="m-container m-page-hero">
          <p className="eyebrow">PLATFORM / {feature.title}</p>
          <h1>{feature.headline}</h1>
          <p className="m-lead">{feature.problem}</p>
          <CTA />
        </section>
        <section className="m-container m-two m-section">
          <div>
            <p className="eyebrow">A CLEARER WORKFLOW</p>
            <h2>{feature.title}, with context.</h2>
            <p>{feature.detail}</p>
            <ol className="workflow-list">
              {feature.workflow.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          </div>
          <div className="technical-panel">
            <Cockpit step={[0, 0, 2, 3, 3][features.indexOf(feature)] ?? 0} />
          </div>
        </section>
        <section className="m-container m-safety">
          <h2>Know the boundary.</h2>
          <p>{feature.safety}</p>
          <p>
            This is a product architecture preview. Scan execution and connected
            integrations are not available in this release.
          </p>
          <Link to="/security">Read the security model →</Link>
        </section>
        <FinalCTA />
      </main>
    );
  if (pathname === '/platform')
    return (
      <main id="main">
        <Metadata
          title="Platform"
          description="Explore AegisForge architecture, evidence boundaries and the discover, scan, explain and enforce workflow."
        />
        <section className="m-container m-page-hero">
          <p className="eyebrow">THE AEGISFORGE PLATFORM</p>
          <h1>
            One workflow.
            <br />
            <em>Distinct sources of truth.</em>
          </h1>
          <p className="m-lead">
            Connect discovery to a decision without blurring observation, advice
            and policy.
          </p>
          <CTA />
        </section>
        <section id="architecture" className="m-container m-section">
          <p className="eyebrow">ARCHITECTURE / PLANNED SYSTEM</p>
          <h2>Separation you can reason about.</h2>
          <div className="architecture-flow">
            {[
              [
                '01',
                'Control plane',
                'React application · FastAPI · organization-scoped authorization',
              ],
              [
                '02',
                'Execution boundary',
                'Queued jobs · isolated worker · scoped ZAP egress',
              ],
              [
                '03',
                'Evidence boundary',
                'Encrypted originals · redacted derivatives · provenance',
              ],
              [
                '04',
                'Review & decision',
                'Advisory Gemini guidance · deterministic versioned policy',
              ],
            ].map(([n, title, text]) => (
              <article key={n}>
                <span>{n}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
          <p className="m-muted">
            This release provides the public site and service-health scaffold.
            Domain services and enforcement remain planned.
          </p>
        </section>
        <section className="m-container m-section">
          <h2>From target to decision trail.</h2>
          <div className="m-grid">
            {steps.map((s) => (
              <article className="capability" key={s.title}>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </article>
            ))}
          </div>
        </section>
        <section className="m-container m-section">
          <h2>Explore the capabilities.</h2>
          <div className="integration-grid">
            {features.map((f) => (
              <Link key={f.slug} to={`/features/${f.slug}`}>
                {f.title} →
              </Link>
            ))}
          </div>
        </section>
        <FinalCTA />
      </main>
    );
  return (
    <main id="main">
      <Metadata
        title="Project packaging"
        description="Community and Team/Research example packaging for the AegisForge research project. No paid plans or checkout."
      />
      <section className="m-container m-page-hero">
        <p className="eyebrow">PRICING / PROJECT PACKAGING</p>
        <h1>
          A place to start.
          <br />
          <em>Room to collaborate.</em>
        </h1>
        <p className="m-lead">
          Example packaging for a research project. These are not purchasable
          plans; availability and commercial pricing are not established.
        </p>
      </section>
      <section className="m-container m-two pricing-cards">
        {[
          [
            'Community',
            'Explore the foundation',
            [
              'Local project setup',
              'Architecture and security documentation',
              'Public design and workflow preview',
            ],
          ],
          [
            'Team / Research',
            'Plan a shared workflow',
            [
              'Proposed organization workspaces',
              'Proposed versioned policy reviews',
              'Proposed report and integration workflows',
            ],
          ],
        ].map(([title, desc, items]) => (
          <article className="capability" key={String(title)}>
            <span className="badge">PROJECT PACKAGING · EXAMPLE</span>
            <h2>{title}</h2>
            <p>{desc}</p>
            <ul>
              {(items as string[]).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            <Link className="button primary" to="/docs/getting-started">
              Explore setup →
            </Link>
          </article>
        ))}
      </section>
      <section className="m-container m-section">
        <h2>Before you choose</h2>
        <details>
          <summary>Can I buy a plan?</summary>
          <p>
            No. This release has no billing, checkout or hosted workspace
            service.
          </p>
        </details>
        <details>
          <summary>Can I run a security scan today?</summary>
          <p>
            The current scaffold exposes service health. Scanning requires later
            implementation of authorization, isolation and evidence services.
          </p>
        </details>
      </section>
    </main>
  );
}
