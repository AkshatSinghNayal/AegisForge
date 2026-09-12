import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { z } from 'zod';
import { Button } from '@/ui';
import { ApiError, request } from './client';
import { usePagedOptions } from './usePagedOptions';
import { MoreOptions } from './PagedOptions';
import {
  dashboardSchema,
  series,
  exportCSV,
  optionsSchema,
} from './analyticsModels';
function Chart({
  title,
  rows,
  unit = '',
}: {
  title: string;
  rows: z.infer<typeof series>;
  unit?: string;
}) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <section className="analytics-panel">
      <h2>{title}</h2>
      {rows.length ? (
        <div
          className="analytics-series"
          tabIndex={0}
          role="region"
          aria-label={title}
        >
          <table>
            <thead>
              <tr>
                <th scope="col">Category / date</th>
                <th scope="col">Value {unit}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td>
                    <span
                      className="analytics-bar"
                      style={{ width: `${(row.value / max) * 100}%` }}
                    />
                    <span>
                      {row.value.toLocaleString(undefined, {
                        maximumFractionDigits: 1,
                      })}
                      {unit}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">Insufficient data for this selection.</p>
      )}
    </section>
  );
}
export default function Dashboard({ org }: { org: string }) {
  const [params, setParams] = useSearchParams();
  const [reload, setReload] = useState(0);
  const [data, setData] = useState<z.infer<typeof dashboardSchema> | null>(
    null,
  );
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);

  const [clock, setClock] = useState(Date.now);
  const timezone =
    params.get('timezone') || Intl.DateTimeFormat().resolvedOptions().timeZone;
  const project = params.get('project') || '';
  const target = params.get('target') || '';
  const page = Number(params.get('page') || 1);
  const query = new URLSearchParams({ organization_id: org, timezone });
  for (const key of ['project', 'target', 'date_from', 'date_to', 'page']) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const queryString = query.toString();
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const projectOptions = usePagedOptions(
    `/organizations/${org}/resources/projects`,
    optionsSchema,
  );
  const targetOptions = usePagedOptions(
    `/organizations/${org}/resources/targets${project ? `?project_id=${project}` : ''}`,
    optionsSchema,
  );
  const projects = projectOptions.data ?? [];
  const options = targetOptions.data ?? [];
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) {
        setBusy(true);
        setError('');
        setData(null);
      }
    });
    void request(`/analytics/dashboard?${queryString}`, dashboardSchema)
      .then((result) => {
        if (active) {
          setData(result);
          setClock(Date.now());
        }
      })
      .catch((e: unknown) => {
        if (active)
          setError(
            e instanceof ApiError && e.status === 403
              ? 'Permission denied. Ask your organization owner for access.'
              : e instanceof Error
                ? e.message
                : 'Dashboard unavailable.',
          );
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [queryString, reload]);
  function refreshDashboard() {
    projectOptions.refresh();
    targetOptions.refresh();
    setReload((v) => v + 1);
  }
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    next.set('organization', org);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === 'project') next.delete('target');
    if (key !== 'page') next.delete('page');
    setParams(next);
  }
  return (
    <div className="analytics">
      <p className="eyebrow">SECURITY OVERVIEW</p>
      <h1>Dashboard</h1>
      <p className="muted">
        Evidence in context. A clear view of what needs attention.
      </p>
      <form className="analytics-filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Project
          <select
            value={project}
            onChange={(e) => filter('project', e.target.value)}
          >
            <option value="">All permitted projects</option>
            {project && !projects.some((p) => p.id === project) && (
              <option value={project}>
                Selected project ({project.slice(0, 8)})
              </option>
            )}
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Target
          <select
            value={target}
            onChange={(e) => filter('target', e.target.value)}
          >
            <option value="">All permitted targets</option>
            {target && !options.some((t) => t.id === target) && (
              <option value={target}>
                Selected target ({target.slice(0, 8)})
              </option>
            )}
            {options
              .filter((t) => !project || t.project_id === project)
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
          </select>
        </label>
        {['date_from', 'date_to'].map((key) => (
          <label key={key}>
            {key === 'date_from' ? 'From (UTC)' : 'Until (UTC, exclusive)'}
            <input
              type="date"
              value={params.get(key)?.slice(0, 10) || ''}
              onChange={(e) =>
                filter(key, e.target.value ? `${e.target.value}T00:00:00Z` : '')
              }
            />
          </label>
        ))}
        <label>
          Display timezone
          <input
            value={timezone}
            onChange={(e) => filter('timezone', e.target.value)}
          />
        </label>
        <Button variant="secondary" onClick={refreshDashboard}>
          Refresh
        </Button>
      </form>
      <MoreOptions label="projects" options={projectOptions} />
      <MoreOptions label="targets" options={targetOptions} />
      <p className="muted">
        Default window: last 30 days. Dates use UTC boundaries; charts and
        activity use the selected timezone.
      </p>
      {error && (
        <div role="alert">
          <h2>Dashboard unavailable</h2>
          <p>{error}</p>
          <Button onClick={refreshDashboard}>Retry</Button>
        </div>
      )}
      {busy && (
        <div
          role="status"
          aria-label="Loading dashboard"
          className="analytics-kpis"
        >
          {Array.from({ length: 6 }, (_, i) => (
            <div className="analytics-panel skeleton" key={i}>
              Loading…
            </div>
          ))}
        </div>
      )}
      {data && (
        <>
          <p role="status" className="muted">
            Updated{' '}
            {new Date(data.generated_at).toLocaleString(undefined, {
              timeZone: data.timezone,
            })}{' '}
            · {data.timezone}
            {clock - Date.parse(data.generated_at) > 300000
              ? ' · Stale data — refresh to update'
              : ''}
          </p>
          <div className="analytics-kpis">
            {data.metrics
              .filter((m) => m.unit !== 'hours' || m.value !== null)
              .map((m) => (
                <article className="analytics-panel" key={m.label}>
                  <h2>{m.label}</h2>
                  <strong>
                    {m.value === null
                      ? 'Insufficient data'
                      : m.value.toLocaleString(undefined, {
                          maximumFractionDigits: 1,
                        })}
                    {m.value !== null && m.unit !== 'count' ? ` ${m.unit}` : ''}
                  </strong>
                </article>
              ))}
          </div>
          <p className="workspace-notice">
            {data.excluded_scans} scans excluded from completed-scan, duration,
            recently-scanned and policy metrics because they are incomplete or
            unfinished. Demo scans are excluded. Findings include observed
            evidence even when a scan is partial.
          </p>
          <ul className="muted">
            {data.exclusions.map((item) => (
              <li key={item.label}>
                {item.label}: {item.value}
              </li>
            ))}
          </ul>
          <div className="analytics-grid">
            <Chart
              title="Findings by OWASP category · top 30"
              rows={data.owasp}
            />
            <Chart
              title="Severity distribution · open findings"
              rows={data.severity}
            />
            <Chart
              title="Findings by CWE category · top 30"
              rows={data.categories}
            />
            <Chart
              title="New / recurring / resolved observations"
              rows={data.lifecycle}
            />
            <Chart
              title="Mean completed scan duration"
              rows={data.duration}
              unit=" min"
            />
            <Chart
              title="Scan completion by creation date"
              rows={data.completion}
              unit="%"
            />
            <section className="analytics-panel">
              <h2>Needs attention</h2>
              <ul>
                {data.actions.map((a) => (
                  <li key={a.label}>
                    {a.label}
                    <strong> {a.value}</strong>
                  </li>
                ))}
              </ul>
              <h3>Next actions</h3>
              <p className="muted">Up to 10 records per category.</p>
              {data.action_items.length ? (
                <ul>
                  {data.action_items.map((a) => (
                    <li key={a.path + a.label}>
                      <Link
                        to={`${a.path}${a.path.includes('?') ? '&' : '?'}organization=${org}`}
                      >
                        {a.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No actions in this selection.</p>
              )}
            </section>
          </div>
          <section className="analytics-panel">
            <h2>Project / target risk</h2>
            <p>
              Open findings last observed in the selected window.{' '}
              {data.risk_total} permitted targets.
            </p>
            <Button
              variant="secondary"
              disabled={!data.risk.length}
              onClick={() =>
                exportCSV(
                  ['Project', 'Target', 'Open findings', 'High / critical'],
                  data.risk.map((r) => [
                    r.project,
                    r.target,
                    r.open_findings,
                    r.high_critical,
                  ]),
                )
              }
            >
              Export this page as CSV
            </Button>
            <div
              className="analytics-series"
              tabIndex={0}
              role="region"
              aria-label="Project and target risk"
            >
              <table>
                <thead>
                  <tr>
                    <th scope="col">Project</th>
                    <th scope="col">Target</th>
                    <th scope="col">Open</th>
                    <th scope="col">High / critical</th>
                  </tr>
                </thead>
                <tbody>
                  {data.risk.map((r) => (
                    <tr key={r.target_id}>
                      <td>
                        <Link
                          to={`/app/projects/${r.project_id}?organization=${org}`}
                        >
                          {r.project}
                        </Link>
                      </td>
                      <th scope="row">
                        <Link
                          to={`/app/findings?organization=${org}&project=${r.project_id}&target=${r.target_id}`}
                        >
                          {r.target}
                        </Link>
                      </th>
                      <td>{r.open_findings}</td>
                      <td>{r.high_critical}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.risk.length && <p>No targets match these filters.</p>}
            <Button
              variant="ghost"
              disabled={page <= 1}
              onClick={() => filter('page', String(page - 1))}
            >
              Previous
            </Button>
            <span>Page {page}</span>
            <Button
              variant="ghost"
              disabled={page * 50 >= data.risk_total}
              onClick={() => filter('page', String(page + 1))}
            >
              Next
            </Button>
          </section>
          <section className="analytics-panel">
            <h2>Recent scan activity</h2>
            {!data.activity.length ? (
              <p>No scans in this window.</p>
            ) : (
              <ul>
                {data.activity.map((s) => (
                  <li key={s.id}>
                    <Link to={`/app/scans/${s.id}?organization=${org}`}>
                      Scan {s.id.slice(0, 8)}
                    </Link>{' '}
                    · {s.state} · {s.completeness} ·{' '}
                    {new Date(s.created_at).toLocaleString(undefined, {
                      timeZone: data.timezone,
                    })}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
