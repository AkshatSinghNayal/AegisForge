import { useEffect, useState } from 'react';
import { z } from 'zod';
import { Button } from '@/ui';
import { request } from './client';

const scopes = [
  'scans:create',
  'scans:read',
  'findings:read',
  'reports:read',
  'integrations:write',
];
const events = [
  'scan.completed',
  'scan.failed',
  'policy.failed',
  'finding.high',
  'report.ready',
  'exception.expiring',
];
const destination = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  enabled: z.boolean(),
  subscriptions: z.array(z.string()),
});
const delivery = z.object({
  id: z.string(),
  state: z.string(),
  attempts: z.number(),
  event_key: z.string().nullable(),
  failure_code: z.string().nullable(),
});
const ok = z.object({ ok: z.boolean() });

export default function DeliveryTools({
  org,
  kind,
  onChange,
}: {
  org: string;
  kind: string;
  onChange: () => void;
}) {
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState('');
  const [destinations, setDestinations] = useState<
    z.infer<typeof destination>[]
  >([]);
  const [deliveries, setDeliveries] = useState<z.infer<typeof delivery>[]>([]);
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (kind !== 'integrations') return;
    let active = true;
    void Promise.all([
      request(
        `/notifications/destinations?organization_id=${org}`,
        z.array(destination),
      ),
      request(
        `/notifications/deliveries?organization_id=${org}&offset=${offset}`,
        z.array(delivery),
      ),
    ])
      .then(([a, b]) => {
        if (active) {
          setLoaded(true);
          setDestinations(a);
          setDeliveries(b);
          setError('');
        }
      })
      .catch((e: unknown) => {
        if (active)
          setError(
            e instanceof Error ? e.message : 'Unable to load notifications.',
          );
      });
    return () => {
      active = false;
    };
  }, [org, kind, reload, offset]);
  function refresh() {
    setLoaded(false);
    setReload((v) => v + 1);
  }
  async function submit(form: HTMLFormElement) {
    const data = new FormData(form);
    setBusy(true);
    setError('');
    setMessage('');
    setSecret('');
    try {
      if (kind === 'api-keys') {
        const key = await request(
          `/api-keys?organization_id=${org}`,
          z.object({ secret: z.string() }),
          'POST',
          {
            name: data.get('name'),
            scopes: data.getAll('scope'),
            expires_at: new Date(String(data.get('expiry'))).toISOString(),
          },
        );
        setSecret(key.secret);
        setMessage('Key created. Copy it now; it cannot be retrieved again.');
      } else if (kind === 'reports') {
        const report = await request(
          `/reports?organization_id=${org}`,
          z.object({ id: z.string(), version: z.number() }),
          'POST',
          { scan_id: data.get('scan'), format: data.get('format') },
        );
        setMessage(
          `Report version ${report.version} queued. Refresh the records to check its progress.`,
        );
      } else {
        await request(
          `/notifications/destinations?organization_id=${org}`,
          destination,
          'POST',
          {
            name: data.get('name'),
            kind: data.get('provider'),
            address: data.get('address'),
            secret: data.get('secret') || '',
            subscriptions: data.getAll('event'),
          },
        );
        setMessage('Notification destination enabled for future events.');
        refresh();
      }
      form.reset();
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to save.');
    } finally {
      setBusy(false);
    }
  }
  async function action(path: string, method: string) {
    setBusy(true);
    setError('');
    try {
      await request(
        `${path}?organization_id=${org}`,
        z.union([ok, delivery]),
        method,
      );
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to save.');
    } finally {
      setBusy(false);
    }
  }
  if (!['reports', 'api-keys', 'integrations'].includes(kind)) return null;
  return (
    <div className="delivery-tools">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit(e.currentTarget);
        }}
      >
        <h2>
          {kind === 'api-keys'
            ? 'Create API key'
            : kind === 'reports'
              ? 'Generate report'
              : 'Add notification destination'}
        </h2>
        {kind === 'reports' ? (
          <>
            <label>
              Scan ID
              <input
                name="scan"
                required
                pattern="[a-fA-F0-9-]{36}"
                placeholder="Scan UUID"
              />
            </label>
            <label>
              Format
              <select name="format">
                <option value="pdf">PDF</option>
                <option value="json">JSON</option>
              </select>
            </label>
            <p>
              Each request captures a new immutable version. Incomplete scans
              are labeled incomplete.
            </p>
          </>
        ) : (
          <label>
            Name
            <input name="name" required maxLength={120} />
          </label>
        )}
        {kind === 'api-keys' && (
          <>
            <label>
              Expires at (local time)
              <input type="datetime-local" name="expiry" required />
            </label>
            <fieldset>
              <legend>Key scopes</legend>
              {scopes.map((s) => (
                <label key={s}>
                  <input type="checkbox" name="scope" value={s} />
                  {s}
                </label>
              ))}
            </fieldset>
          </>
        )}
        {kind === 'integrations' && (
          <>
            <label>
              Provider
              <select name="provider">
                <option value="email">Email</option>
                <option value="slack">Slack incoming webhook</option>
                <option value="webhook">Signed webhook</option>
                <option value="github">GitHub PR comment</option>
              </select>
            </label>
            <label>
              Email address or HTTPS endpoint
              <input
                name="address"
                required
                autoComplete="off"
                maxLength={2000}
              />
            </label>
            <label>
              HMAC secret or GitHub token
              <input
                type="password"
                name="secret"
                autoComplete="new-password"
                maxLength={2000}
              />
            </label>
            <p>
              Generic webhooks require at least 32 secret characters. For GitHub
              use
              https://api.github.com/repos/OWNER/REPO/issues/PR_NUMBER/comments
              and a token with pull request write access.
            </p>
            <fieldset>
              <legend>Events</legend>
              {events.map((s) => (
                <label key={s}>
                  <input type="checkbox" name="event" value={s} />
                  {s}
                </label>
              ))}
            </fieldset>
          </>
        )}
        <Button type="submit" disabled={busy}>
          {busy ? 'Saving…' : kind === 'reports' ? 'Queue report' : 'Create'}
        </Button>
      </form>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {secret && (
        <div>
          <label>
            One-time API secret
            <input
              readOnly
              value={secret}
              onFocus={(e) => e.currentTarget.select()}
            />
          </label>
          <Button onClick={() => setSecret('')}>Dismiss secret</Button>
        </div>
      )}
      {kind === 'integrations' && (
        <>
          <h2>Notification destinations</h2>
          <Button variant="secondary" onClick={() => refresh()}>
            Refresh notifications
          </Button>
          {loaded && destinations.length === 0 && (
            <p>No notification destinations.</p>
          )}
          {loaded &&
            destinations.map((d) => (
              <p key={d.id}>
                {d.name} · {d.kind} · {d.enabled ? 'Enabled' : 'Disabled'}{' '}
                {d.enabled && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void action(
                        `/notifications/destinations/${d.id}`,
                        'DELETE',
                      )
                    }
                  >
                    Disable {d.name}
                  </Button>
                )}
              </p>
            ))}
          <h2>Delivery history</h2>
          {loaded && deliveries.length === 0 && (
            <p>No deliveries on this page.</p>
          )}
          {loaded &&
            deliveries.map((d) => (
              <p key={d.id}>
                {d.event_key} · {d.state} · {d.attempts} attempts{' '}
                {['failed', 'dead_letter'].includes(d.state) && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void action(
                        `/notifications/deliveries/${d.id}/retry`,
                        'POST',
                      )
                    }
                  >
                    Retry delivery
                  </Button>
                )}
              </p>
            ))}
          <Button
            disabled={!loaded || offset === 0}
            onClick={() => {
              setLoaded(false);
              setOffset((v) => Math.max(0, v - 100));
            }}
          >
            Previous deliveries
          </Button>
          <Button
            disabled={!loaded || deliveries.length < 100}
            onClick={() => {
              setLoaded(false);
              setOffset((v) => v + 100);
            }}
          >
            Next deliveries
          </Button>
        </>
      )}
    </div>
  );
}
