import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { z } from 'zod';
import { Button } from '@/ui';
import { request } from './client';

const controlsSchema = z.object({
  disabled_policy_ids: z.array(z.string()),
  scans_enabled: z.boolean(),
  active_scans_enabled: z.boolean(),
  concurrency: z.number(),
  target_concurrency: z.number(),
  daily_quota: z.number(),
  report_retention_days: z.number(),
  raw_retention_days: z.number(),
  allow_networks: z.array(z.string()),
  deny_networks: z.array(z.string()),
});
const auditSchema = z.array(
  z.object({
    id: z.string(),
    organization_id: z.string(),
    source_ip: z.string().nullable(),
    actor_id: z.string().nullable(),
    action: z.string(),
    resource_type: z.string(),
    resource_id: z.string(),
    request_id: z.string(),
    timestamp: z.string(),
    result: z.string(),
    changed_fields: z.array(z.string()),
  }),
);
const systemSchema = z.object({
  api: z.string(),
  database: z.string(),
  redis: z.string(),
  worker: z.string(),
  scanner: z.string(),
  storage: z.string(),
  ai_provider: z.string(),
  emergency_stop: z.boolean(),
  active_scans_enabled: z.boolean(),
});
const jobsSchema = z.array(
  z.object({
    id: z.string(),
    kind: z.string(),
    state: z.string(),
    retry: z.string(),
    created_at: z.string(),
  }),
);
const message = z.object({ message: z.string() });
type Controls = z.infer<typeof controlsSchema>;

export default function Administration({
  org,
  auditOnly = false,
}: {
  org: string;
  auditOnly?: boolean;
}) {
  const [controls, setControls] = useState<Controls | null>(null);
  const [system, setSystem] = useState<z.infer<typeof systemSchema> | null>(
    null,
  );
  const [jobs, setJobs] = useState<z.infer<typeof jobsSchema>>([]);
  const [audits, setAudits] = useState<z.infer<typeof auditSchema>>([]);
  const [filter, setFilter] = useState('');
  const [appliedFilter, setAppliedFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const query = `organization_id=${encodeURIComponent(org)}`;
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        if (auditOnly) {
          const data = await request(
            `/admin/audit?${query}&offset=${offset}&limit=100${appliedFilter ? `&action=${encodeURIComponent(appliedFilter)}` : ''}`,
            auditSchema,
          );
          if (live) setAudits(data);
        } else {
          const [c, s, j] = await Promise.all([
            request(`/admin/controls?${query}`, controlsSchema),
            request(`/admin/system?${query}`, systemSchema),
            request(`/admin/jobs?${query}&offset=${offset}`, jobsSchema),
          ]);
          if (live) {
            setControls(c);
            setSystem(s);
            setJobs(j);
          }
        }
      } catch (e) {
        if (live)
          setFeedback(
            e instanceof Error ? e.message : 'Unable to load administration.',
          );
      }
    };
    void load();
    return () => {
      live = false;
    };
  }, [org, auditOnly, query, offset, appliedFilter]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setFeedback('');
    try {
      await fn();
    } catch (e) {
      setFeedback(e instanceof Error ? e.message : 'Operation failed.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="configuration-page administration-page">
      <h1>{auditOnly ? 'Audit log' : 'Administration'}</h1>
      {feedback && <p role="status">{feedback}</p>}
      {auditOnly ? (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setAppliedFilter(filter);
            }}
          >
            <label>
              Exact action{' '}
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                maxLength={100}
              />
            </label>
            <Button type="submit" disabled={busy}>
              Filter
            </Button>
          </form>
          <Button
            variant="secondary"
            onClick={() => {
              const url = URL.createObjectURL(
                new Blob([JSON.stringify(audits, null, 2)], {
                  type: 'application/json',
                }),
              );
              const a = document.createElement('a');
              a.href = url;
              a.download = 'aegisforge-audit-page.json';
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export displayed records (JSON)
          </Button>
          <p>
            Change summaries contain field names only. Times are shown in your
            local timezone.
          </p>
          <ul>
            {audits.map((a) => (
              <li key={a.id}>
                <strong>{a.action}</strong> ·{' '}
                {new Date(a.timestamp).toLocaleString()} · {a.result}
                <p>
                  Actor: {a.actor_id ?? 'System'} · {a.resource_type}:{' '}
                  {a.resource_id}
                </p>
                <p>
                  Request: {a.request_id} · Changed fields:{' '}
                  {a.changed_fields.join(', ') || 'None'}
                </p>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <nav aria-label="Administration tools">
            <Link to={`/app/team?organization=${org}`}>Users and sessions</Link>
            <Link to={`/app/policies?organization=${org}`}>Scan policies</Link>
            <Link to={`/app/integrations?organization=${org}`}>
              Integration health and deliveries
            </Link>
            <Link to={`/app/audit-log?organization=${org}`}>Audit log</Link>
          </nav>
          {controls && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void action(async () => {
                  setControls(
                    await request(
                      `/admin/controls?${query}`,
                      controlsSchema,
                      'PUT',
                      controls,
                    ),
                  );
                  setFeedback(
                    'Controls saved. Retention changes apply to new objects.',
                  );
                });
              }}
            >
              <h2>Scan safety and retention</h2>
              {(['scans_enabled', 'active_scans_enabled'] as const).map((k) => (
                <label key={k}>
                  <input
                    type="checkbox"
                    checked={controls[k]}
                    onChange={(e) =>
                      setControls({ ...controls, [k]: e.target.checked })
                    }
                  />
                  {k.replaceAll('_', ' ')}
                </label>
              ))}
              {(
                [
                  'concurrency',
                  'target_concurrency',
                  'daily_quota',
                  'report_retention_days',
                  'raw_retention_days',
                ] as const
              ).map((k) => (
                <label key={k}>
                  {k.replaceAll('_', ' ')}
                  <input
                    required
                    type="number"
                    min={1}
                    max={
                      k === 'daily_quota'
                        ? 10000
                        : k.endsWith('days')
                          ? 365
                          : 100
                    }
                    value={controls[k]}
                    onChange={(e) =>
                      setControls({ ...controls, [k]: Number(e.target.value) })
                    }
                  />
                </label>
              ))}
              {(['allow_networks', 'deny_networks'] as const).map((k) => (
                <label key={k}>
                  {k.replaceAll('_', ' ')} (one CIDR per line)
                  <textarea
                    value={controls[k].join('\n')}
                    onChange={(e) =>
                      setControls({
                        ...controls,
                        [k]: e.target.value.split('\n'),
                      })
                    }
                    onBlur={() =>
                      setControls({
                        ...controls,
                        [k]: controls[k].map((s) => s.trim()).filter(Boolean),
                      })
                    }
                  />
                </label>
              ))}
              <p>
                Deny rules override allow rules. An empty allow list adds no
                restriction. Operator limits still apply.
              </p>
              <Button type="submit" disabled={busy}>
                Save controls
              </Button>
            </form>
          )}
          {system && (
            <>
              <h2>System status</h2>
              <p>
                Configured or directory-present states are not end-to-end health
                checks.
              </p>
              <dl>
                {Object.entries(system).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k.replaceAll('_', ' ')}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          <h2>Failed jobs</h2>
          <ul>
            {jobs.map((j) => (
              <li key={j.id}>
                {j.kind} {j.id} · {j.state}
                {j.retry === 'regenerate_report' ? (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        await request(
                          `/admin/reports/${j.id}/retry?${query}`,
                          message,
                          'POST',
                        );
                        setJobs(jobs.filter((row) => row.id !== j.id));
                        setFeedback('Report queued.');
                      })
                    }
                  >
                    Retry report
                  </Button>
                ) : (
                  <Link to={`/app/scans/new?organization=${org}`}>
                    Create a newly authorized scan
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      <Button
        variant="secondary"
        disabled={offset === 0 || busy}
        onClick={() => setOffset(Math.max(0, offset - 100))}
      >
        Previous page
      </Button>
      <Button
        variant="secondary"
        disabled={busy || (auditOnly ? audits.length < 100 : jobs.length < 100)}
        onClick={() => setOffset(offset + 100)}
      >
        Next page
      </Button>
    </section>
  );
}
