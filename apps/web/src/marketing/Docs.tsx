import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { docs } from './content';
import { Metadata } from './Shared';
export default function Docs() {
  const { slug } = useParams();
  const [query, setQuery] = useState('');
  const doc = docs.find((d) => d.slug === slug);
  const matches = docs.filter((d) =>
    (d.title + ' ' + d.text + ' ' + d.note)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  if (slug && !doc)
    return (
      <main id="main" className="m-container legal-page">
        <Metadata
          title="Guide not found"
          description="The requested documentation guide does not exist."
        />
        <h1>Guide not found</h1>
        <Link to="/docs">Browse documentation →</Link>
      </main>
    );
  return (
    <main id="main" className="m-container docs-layout">
      <Metadata
        title={doc?.title ?? 'Documentation'}
        description={
          doc?.text ??
          'Read AegisForge setup, architecture, authorization, policy and integration documentation.'
        }
      />
      <aside>
        <Link className="eyebrow" to="/docs">
          AEGISFORGE DOCS
        </Link>
        <label htmlFor="docs-search">Search documentation</label>
        <input
          id="docs-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Architecture, policies…"
        />
        <nav aria-label="Documentation">
          {matches.map((d) => (
            <Link
              aria-current={d.slug === slug ? 'page' : undefined}
              key={d.slug}
              to={`/docs/${d.slug}`}
            >
              {d.title}
            </Link>
          ))}
        </nav>
        {matches.length === 0 && (
          <p role="status">No matching guides. Try “policy” or “target”.</p>
        )}
      </aside>
      <article>
        {doc ? (
          <>
            <p className="eyebrow">GUIDES / PROJECT RELEASE</p>
            <h1>{doc.title}</h1>
            <p className="m-lead">{doc.text}</p>
            <h2>
              {doc.slug === 'getting-started'
                ? 'Local setup'
                : 'Workflow reference'}
            </h2>
            <pre>
              <code>{doc.code}</code>
            </pre>
            <h2>What to know</h2>
            <p>{doc.note}</p>
            <Link className="button secondary" to="/docs">
              All documentation →
            </Link>
          </>
        ) : (
          <>
            <p className="eyebrow">DOCUMENTATION</p>
            <h1>
              Understand the system.
              <br />
              <em>Build with intent.</em>
            </h1>
            <p className="m-lead">
              Practical guides to the current scaffold and the boundaries of the
              planned platform.
            </p>
            <div className="docs-cards">
              {matches.map((d) => (
                <Link
                  className="capability"
                  key={d.slug}
                  to={`/docs/${d.slug}`}
                >
                  <h2>{d.title} →</h2>
                  <p>{d.text}</p>
                </Link>
              ))}
            </div>
          </>
        )}
      </article>
    </main>
  );
}
