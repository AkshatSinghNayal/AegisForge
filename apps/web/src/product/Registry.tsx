import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { z } from 'zod';
import { Button } from '@/ui';
import { ApiError, request } from './client';
import DeliveryTools from './DeliveryTools';
import GitHubIntegration from './GitHubIntegration';
import { exportCSV } from './analyticsModels';
const schema = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      status: z.string(),
      created_at: z.string(),
      expires_at: z.string().nullable(),
      scan_id: z.string().nullable(),
    }),
  ),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
});
const titles: Record<string, string> = {
  reports: 'Reports',
  integrations: 'Integrations',
  'api-keys': 'API Keys',
  'audit-log': 'Audit Log',
};
export default function Registry({ org, kind }: { org: string; kind: string }) {
  const [params, setParams] = useSearchParams();
  const page = Number(params.get('page') || 1);
  const [data, setData] = useState<z.infer<typeof schema> | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void request(
      `/workspace/${kind}?organization_id=${org}&page=${page}`,
      schema,
    )
      .then((d) => {
        if (active) {
          setData(d);
          setError('');
        }
      })
      .catch((e: unknown) => {
        if (active) {
          setData(null);
          setError(
            e instanceof ApiError && e.status === 403
              ? 'Permission denied. Organization administration access is required.'
              : e instanceof Error
                ? e.message
                : 'Unable to load records.',
          );
        }
      });
    return () => {
      active = false;
    };
  }, [org, kind, page, reload]);
  async function deactivate(id: string) {
    setBusy(true);
    try {
      await request(
        `/workspace/${kind}/${id}?organization_id=${org}`,
        z.object({ ok: z.boolean() }),
        'DELETE',
      );
      setReload((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to save.');
    } finally {
      setBusy(false);
    }
  }
  async function download(id: string) {
    setBusy(true);
    try {
      const link = await request(
        `/reports/${id}/download?organization_id=${org}`,
        z.object({ url: z.string(), expires_at: z.string() }),
        'POST',
      );
      window.location.assign(link.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to download.');
    } finally {
      setBusy(false);
    }
  }
  function move(value: number) {
    const next = new URLSearchParams(params);
    next.set('page', String(value));
    setData(null);
    setParams(next);
  }
  return (
    <section className="analytics-panel registry-panel">
      <h1>{titles[kind]}</h1>
      <p className="muted">
        Retained organization records. Sensitive evidence and credentials are
        excluded.
      </p>
      {error && (
        <div role="alert">
          <p>{error}</p>
          <Button onClick={() => setReload((v) => v + 1)}>Retry</Button>
        </div>
      )}
      {!data && !error && (
        <div className="skeleton" role="status">
          Loading records…
        </div>
      )}
      {org && kind === 'integrations' && (
        <GitHubIntegration key={org} org={org} />
      )}
      {org && (
        <DeliveryTools
          key={`${org}:${kind}`}
          org={org}
          kind={kind}
          onChange={() => setReload((v) => v + 1)}
        />
      )}
      <Button variant="secondary" onClick={() => setReload((v) => v + 1)}>
        Refresh records
      </Button>
      {data && (
        <>
          <p>
            {data.total} records · Page {page}
          </p>
          <Button
            variant="secondary"
            disabled={!data.items.length}
            onClick={() =>
              exportCSV(
                ['Record', 'Status', 'Created', 'Expires'],
                data.items.map((r) => [
                  r.label,
                  r.status,
                  r.created_at,
                  r.expires_at || '',
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
            aria-label={titles[kind]}
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">Record</th>
                  <th scope="col">Status</th>
                  <th scope="col">Created (local time)</th>
                  <th scope="col">Expires (local time)</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id}>
                    <th scope="row">{r.label}</th>
                    <td>{r.status}</td>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                    <td>
                      {r.expires_at
                        ? new Date(r.expires_at).toLocaleString()
                        : '—'}
                    </td>
                    <td>
                      {kind === 'reports' && r.status === 'complete' && (
                        <Button
                          disabled={busy}
                          onClick={() => void download(r.id)}
                        >
                          Download report
                        </Button>
                      )}
                      {r.scan_id && (
                        <Link
                          to={`/app/scans/${r.scan_id}?organization=${org}`}
                        >
                          View scan
                        </Link>
                      )}
                      {['api-keys', 'integrations'].includes(kind) &&
                        r.status === 'active' && (
                          <Button
                            variant="secondary"
                            disabled={busy}
                            onClick={() => void deactivate(r.id)}
                          >
                            {kind === 'api-keys' ? 'Revoke key' : 'Deactivate'}
                          </Button>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.items.length && <p>No {titles[kind]?.toLowerCase()} found.</p>}
          <Button
            variant="ghost"
            disabled={page <= 1}
            onClick={() => move(page - 1)}
          >
            Previous
          </Button>
          <Button
            variant="ghost"
            disabled={page * data.page_size >= data.total}
            onClick={() => move(page + 1)}
          >
            Next
          </Button>
        </>
      )}
    </section>
  );
}
