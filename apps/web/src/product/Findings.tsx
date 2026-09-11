import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { z } from 'zod';
import { exportCSV } from './analyticsModels';
import { Button } from '@/ui';
import { request } from './client';
import AIGuidance from './AIGuidance';

const findingSchema = z.object({
  id: z.string(),
  target_id: z.string(),
  title: z.string(),
  severity: z.string(),
  confidence: z.string(),
  status: z.string(),
  route: z.string(),
  cwe: z.number().nullable(),
  owasp: z.array(z.string()),
  first_seen_at: z.string(),
  last_seen_at: z.string(),
  version: z.number(),
});
const pageSchema = z.object({
  items: z.array(findingSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
});
const normalizedSchema = z.object({
  request: z.string().optional(),
  response: z.string().optional(),
  rule: z.string().optional(),
  method: z.string().optional(),
  parameter: z.string().optional(),
  location: z.string().optional(),
  wasc: z.number().nullable().optional(),
  references: z.array(z.string()).optional(),
  sources: z.record(z.string(), z.array(z.string())).optional(),
  redaction: z.record(z.string(), z.string()).optional(),
});
const detailSchema = z.object({
  finding: findingSchema,
  fingerprint: z.string(),
  fingerprint_version: z.string(),
  normalized: normalizedSchema,
  occurrences: z.array(
    z.object({
      id: z.string(),
      scan_id: z.string(),
      artifact_id: z.string(),
      normalizer: z.string(),
      evidence_reference: z.string(),
      observed_at: z.string(),
      normalized: normalizedSchema,
    }),
  ),
  history: z.array(
    z.object({
      id: z.string(),
      action: z.string(),
      previous_state: z.string(),
      state: z.string(),
      note: z.string(),
      actor_id: z.string().nullable(),
      scan_id: z.string().nullable(),
      created_at: z.string(),
    }),
  ),
  analysis_status: z.array(
    z.object({ id: z.string(), status: z.string(), advisory: z.boolean() }),
  ),
  policy_impact: z.array(
    z.object({ id: z.string(), scan_id: z.string(), outcome: z.string() }),
  ),
});
const comparisonSchema = z.object({
  scan_id: z.string(),
  state: z.string(),
  completeness: z.string(),
  comparison: z
    .object({
      baseline_scan_id: z.string().nullable(),
      changes: z.record(z.string(), z.string()),
    })
    .nullable(),
});
const tabs = ['Summary', 'Evidence', 'AI Guidance', 'History', 'Policy'];
const tabId = (name: string) => `finding-tab-${name.replaceAll(' ', '-')}`;
const statuses = [
  'new',
  'recurring',
  'changed',
  'resolved',
  'reopened',
  'accepted_risk',
  'false_positive',
];
const label = (value: string) => value.replaceAll('_', ' ');
function Badge({ value }: { value: string }) {
  return (
    <span className={`badge finding-badge finding-${value}`}>
      {label(value)}
    </span>
  );
}
export default function Findings(props: { org: string; role: string }) {
  const [params] = useSearchParams();
  return (
    <FindingContent key={`${props.org}:${params.toString()}`} {...props} />
  );
}
function FindingContent({ org, role }: { org: string; role: string }) {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<z.infer<typeof pageSchema> | null>(null);
  const [detail, setDetail] = useState<z.infer<typeof detailSchema> | null>(
    null,
  );
  const [comparison, setComparison] = useState<z.infer<
    typeof comparisonSchema
  > | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState('Summary');
  const [occurrenceIndex, setOccurrenceIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const selected = params.get('finding');
  const compare = params.get('compare');
  const serialized = params.toString();
  useEffect(() => {
    let active = true;
    const query = new URLSearchParams(serialized);
    query.delete('finding');
    query.delete('compare');
    query.set('organization_id', org);
    const work = selected
      ? request(
          `/findings/${selected}?organization_id=${org}`,
          detailSchema,
        ).then((v) => {
          if (active) setDetail(v);
        })
      : compare
        ? request(
            `/findings/comparison/${compare}?organization_id=${org}`,
            comparisonSchema,
          ).then((v) => {
            if (active) setComparison(v);
          })
        : request(`/findings?${query}`, pageSchema).then((v) => {
            if (active) setPage(v);
          });
    void work
      .then(() => {
        if (active) setError('');
      })
      .catch((e: unknown) => {
        if (active)
          setError(e instanceof Error ? e.message : 'Findings unavailable.');
      });
    return () => {
      active = false;
    };
  }, [org, serialized, selected, compare, revision]);
  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next);
  }
  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = new URLSearchParams();
    new FormData(event.currentTarget).forEach((value, key) => {
      if (String(value)) next.set(key, String(value));
    });
    setParams(next);
  }
  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail) return;
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setError('');
    try {
      await request(
        `/findings/${detail.finding.id}/review?organization_id=${org}`,
        findingSchema,
        'POST',
        {
          action: values.get('action'),
          note: values.get('note'),
          version: detail.finding.version,
          verification_scan_id: values.get('verification_scan_id') || null,
        },
      );
      setRevision((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Review failed.');
    } finally {
      setBusy(false);
    }
  }
  const listParams = new URLSearchParams(params);
  listParams.delete('finding');
  listParams.delete('compare');
  const occurrence = detail?.occurrences[occurrenceIndex];
  return (
    <section className="findings-page">
      <p className="eyebrow">WORKSPACE / FINDINGS</p>
      <h1>
        {detail
          ? detail.finding.title
          : compare
            ? 'Scan comparison'
            : 'Evidence-backed findings'}
      </h1>
      {error && (
        <p role="alert">
          {error}{' '}
          <Button onClick={() => setRevision((v) => v + 1)}>Retry</Button>
        </p>
      )}
      {(selected || compare) && (
        <Link to={`/app/findings?${listParams}`}>← All findings</Link>
      )}
      {!error && !page && !detail && !comparison && (
        <p role="status">Loading findings…</p>
      )}
      {page && (
        <>
          <Button
            variant="secondary"
            disabled={!page.items.length}
            onClick={() =>
              exportCSV(
                [
                  'Title',
                  'Severity',
                  'Status',
                  'CWE',
                  'First seen',
                  'Last seen',
                ],
                page.items.map((f) => [
                  f.title,
                  f.severity,
                  f.status,
                  f.cwe ?? '',
                  f.first_seen_at,
                  f.last_seen_at,
                ]),
              )
            }
          >
            Export this page as CSV
          </Button>
          <form onSubmit={filter} className="finding-filters" key={serialized}>
            {['project', 'target', 'scan', 'route', 'cwe', 'owasp'].map(
              (key) => (
                <label key={key}>
                  {key === 'owasp'
                    ? 'OWASP category'
                    : ['project', 'target', 'scan'].includes(key)
                      ? `${label(key)} ID`
                      : label(key)}
                  <input name={key} defaultValue={params.get(key) ?? ''} />
                </label>
              ),
            )}
            {[
              [
                'severity',
                ['informational', 'low', 'medium', 'high', 'critical'],
              ],
              [
                'confidence',
                ['false_positive', 'low', 'medium', 'high', 'confirmed'],
              ],
              ['status', statuses],
            ].map(([key, options]) => (
              <label key={String(key)}>
                {String(key)}
                <select
                  name={String(key)}
                  defaultValue={params.get(String(key)) ?? ''}
                >
                  <option value="">All</option>
                  {(options as string[]).map((v) => (
                    <option key={v} value={v}>
                      {label(v)}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            {['date_from', 'date_to'].map((key) => (
              <label key={key}>
                {label(key)}
                <input
                  name={key}
                  type="datetime-local"
                  defaultValue={params.get(key) ?? ''}
                />
              </label>
            ))}
            <Button type="submit">Apply filters</Button>
            <Link to="/app/findings">Clear filters</Link>
          </form>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              update(
                'compare',
                String(
                  new FormData(event.currentTarget).get('comparison_scan'),
                ),
              );
            }}
          >
            <label>
              Compare scan ID <input required name="comparison_scan" />
            </label>{' '}
            <Button type="submit" variant="secondary">
              Compare scan
            </Button>
          </form>
          <p>{page.total} findings</p>
          <div className="finding-table-scroll">
            <table>
              <thead>
                <tr>
                  {[
                    'title',
                    'severity',
                    'confidence',
                    'status',
                    'route',
                    'last_seen_at',
                  ].map((key) => (
                    <th
                      key={key}
                      aria-sort={
                        params.get('sort') === key
                          ? params.get('direction') === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      }
                    >
                      <button
                        onClick={() => {
                          const next = new URLSearchParams(params);
                          next.set('sort', key);
                          next.set(
                            'direction',
                            params.get('sort') === key &&
                              params.get('direction') === 'asc'
                              ? 'desc'
                              : 'asc',
                          );
                          next.delete('page');
                          setParams(next);
                        }}
                      >
                        {label(key)}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link to={`?${serialized}&finding=${item.id}`}>
                        {item.title}
                      </Link>
                    </td>
                    <td>
                      <Badge value={item.severity} />
                    </td>
                    <td>{label(item.confidence)}</td>
                    <td>
                      <Badge value={item.status} />
                    </td>
                    <td>{item.route}</td>
                    <td>{new Date(item.last_seen_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!page.items.length && <p>No findings match these filters.</p>}
          <nav aria-label="Finding pages">
            <Button
              disabled={page.page === 1}
              onClick={() => update('page', String(page.page - 1))}
            >
              Previous
            </Button>{' '}
            <span>Page {page.page}</span>{' '}
            <Button
              disabled={page.page * page.page_size >= page.total}
              onClick={() => update('page', String(page.page + 1))}
            >
              Next
            </Button>
          </nav>
        </>
      )}
      {comparison && (
        <>
          <p>
            Scan {comparison.scan_id}: {comparison.state}, coverage{' '}
            {comparison.completeness}.
          </p>
          {comparison.comparison ? (
            <>
              <p>
                Baseline:{' '}
                {comparison.comparison.baseline_scan_id ??
                  'No comparable completed scan'}
              </p>
              {statuses.map((status) => (
                <section key={status}>
                  <h2>{label(status)}</h2>
                  <ul>
                    {Object.entries(comparison.comparison?.changes ?? {})
                      .filter(([, state]) => state === status)
                      .map(([id]) => (
                        <li key={id}>
                          <Link to={`/app/findings?finding=${id}`}>
                            Finding {id}
                          </Link>
                        </li>
                      ))}
                  </ul>
                  <p>
                    {
                      Object.values(
                        comparison.comparison?.changes ?? {},
                      ).filter((v) => v === status).length
                    }{' '}
                    findings
                  </p>
                </section>
              ))}
            </>
          ) : (
            <p>
              No normalized comparison is available. This scan cannot establish
              resolution.
            </p>
          )}
        </>
      )}
      {detail && (
        <>
          <p>
            <Badge value={detail.finding.severity} />{' '}
            <Badge value={detail.finding.status} /> Scanner confidence:{' '}
            {label(detail.finding.confidence)}
          </p>
          <div
            role="tablist"
            aria-label="Finding detail sections"
            className="finding-tabs"
          >
            {tabs.map((name) => (
              <Button
                key={name}
                variant={tab === name ? 'primary' : 'secondary'}
                role="tab"
                id={tabId(name)}
                aria-selected={tab === name}
                aria-controls="finding-panel"
                tabIndex={tab === name ? 0 : -1}
                onKeyDown={(event) => {
                  const index = tabs.indexOf(name);
                  const next =
                    event.key === 'ArrowRight'
                      ? (index + 1) % tabs.length
                      : event.key === 'ArrowLeft'
                        ? (index + tabs.length - 1) % tabs.length
                        : event.key === 'Home'
                          ? 0
                          : event.key === 'End'
                            ? tabs.length - 1
                            : null;
                  if (next === null) return;
                  event.preventDefault();
                  const destination = tabs[next];
                  if (destination) {
                    setTab(destination);
                    document.getElementById(tabId(destination))?.focus();
                  }
                }}
                onClick={() => setTab(name)}
              >
                {name}
              </Button>
            ))}
          </div>
          <section
            role="tabpanel"
            id="finding-panel"
            aria-labelledby={tabId(tab)}
            tabIndex={0}
          >
            {tab === 'Summary' && (
              <>
                <h2>Summary</h2>
                <p>
                  {detail.normalized.method} {detail.finding.route}
                </p>
                <p>
                  Rule {detail.normalized.rule} · Parameter:{' '}
                  {detail.normalized.parameter || 'None'} · Location:{' '}
                  {detail.normalized.location}
                </p>
                <p>
                  CWE: {detail.finding.cwe ?? 'Not supplied'} · WASC:{' '}
                  {detail.normalized.wasc ?? 'Not supplied'}
                </p>
                <p>
                  OWASP:{' '}
                  {detail.finding.owasp.join(', ') || 'Not supplied by scanner'}
                </p>
                <p className="finding-digest">
                  {detail.fingerprint_version}: {detail.fingerprint}
                </p>
                <h3>References</h3>
                <ul>
                  {detail.normalized.references?.map((ref) => (
                    <li key={ref}>{ref}</li>
                  ))}
                </ul>
              </>
            )}
            {tab === 'Evidence' && (
              <>
                <h2>Evidence</h2>
                <label>
                  Occurrence{' '}
                  <select
                    value={occurrenceIndex}
                    onChange={(event) =>
                      setOccurrenceIndex(Number(event.target.value))
                    }
                  >
                    {detail.occurrences.map((o, index) => (
                      <option key={o.id} value={index}>
                        {new Date(o.observed_at).toLocaleString()} · {o.scan_id}
                      </option>
                    ))}
                  </select>
                </label>
                {occurrence ? (
                  <>
                    <p>
                      Artifact: {occurrence.artifact_id} · Occurrence:{' '}
                      {occurrence.id}
                    </p>
                    <p>
                      {occurrence.normalizer} · {occurrence.evidence_reference}
                    </p>
                    <div className="http-evidence">
                      <div>
                        <h3>HTTP request</h3>
                        <pre>{occurrence.normalized.request}</pre>
                      </div>
                      <div>
                        <h3>HTTP response</h3>
                        <pre>{occurrence.normalized.response}</pre>
                      </div>
                    </div>
                    <h3>Redaction</h3>
                    <ul>
                      {Object.entries(
                        occurrence.normalized.redaction ?? {},
                      ).map(([key, value]) => (
                        <li key={key}>
                          {key}: {value}
                        </li>
                      ))}
                    </ul>
                    <details>
                      <summary>Field provenance (raw JSON pointers)</summary>
                      <pre>
                        {JSON.stringify(occurrence.normalized.sources, null, 2)}
                      </pre>
                    </details>
                    <Link to={`/app/findings?compare=${occurrence.scan_id}`}>
                      Compare this scan
                    </Link>
                  </>
                ) : (
                  <p>No normalized occurrences available.</p>
                )}
              </>
            )}
            {tab === 'AI Guidance' && (
              <AIGuidance
                org={org}
                finding={detail.finding.id}
                role={role}
                cite={(id) => {
                  const index = detail.occurrences.findIndex(
                    (o) => o.id === id,
                  );
                  if (index >= 0) {
                    setOccurrenceIndex(index);
                    setTab('Evidence');
                    document.getElementById(tabId('Evidence'))?.focus();
                  }
                }}
              />
            )}
            {tab === 'History' && (
              <>
                <h2>History</h2>
                <ol>
                  {detail.history.map((h) => (
                    <li key={h.id}>
                      <p>
                        {new Date(h.created_at).toLocaleString()} ·{' '}
                        {label(h.action)} · {label(h.previous_state)} →{' '}
                        {label(h.state)}
                      </p>
                      <p>{h.note}</p>
                      <small>
                        {h.actor_id
                          ? `Reviewer ${h.actor_id}`
                          : `Scan ${h.scan_id}`}
                      </small>
                    </li>
                  ))}
                </ol>
              </>
            )}
            {tab === 'Policy' && (
              <>
                <h2>Policy impact</h2>
                <p>
                  Only versioned deterministic policy evaluations decide gates.
                </p>
                {detail.policy_impact.length ? (
                  detail.policy_impact.map((p) => (
                    <p key={p.id}>
                      Scan {p.scan_id}: {p.outcome}
                    </p>
                  ))
                ) : (
                  <p>
                    No policy evaluation is available. No passing gate is
                    implied.
                  </p>
                )}
              </>
            )}
          </section>
          {role !== 'viewer' && (
            <form
              onSubmit={(event) => void review(event)}
              className="finding-review"
            >
              <h2>Review finding</h2>
              <label>
                Action
                <select name="action">
                  <option value="note">Add note</option>
                  <option value="accept_risk">Accept risk</option>
                  <option value="false_positive">Mark false positive</option>
                  <option value="reopen">Reopen</option>
                  <option value="resolve">Resolve after verification</option>
                </select>
              </label>
              <label>
                Reviewer note (do not include secrets)
                <textarea name="note" required maxLength={2000} />
              </label>
              <label>
                Verification scan ID (required for resolution)
                <input name="verification_scan_id" />
              </label>
              <Button type="submit" disabled={busy}>
                {busy ? 'Saving…' : 'Save review'}
              </Button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
