import { useEffect, useState } from 'react';
import { z } from 'zod';
import { Button } from '@/ui';
import { request } from './client';

const mapping = z.object({
  id: z.string(),
  integration_id: z.string(),
  repository: z.string(),
  branch: z.string(),
  project_id: z.string(),
  target_id: z.string(),
  policy_id: z.string(),
  target_version: z.number(),
  policy_version: z.number(),
  gate_policy_version: z.number(),
  events: z.array(z.string()),
  enabled: z.boolean(),
  webhook_path: z.string(),
  environment: z.string(),
});
const delivery = z.object({
  id: z.string(),
  mapping_id: z.string(),
  delivery_id: z.string(),
  event: z.string(),
  state: z.string(),
  scan_id: z.string().nullable(),
  created_at: z.string(),
});
const instructions =
  'Create an organization API key with scans:create and scans:read. Copy it once into GitHub Settings → Secrets and variables → Actions as AEGISFORGE_API_KEY. Store the one-time webhook secret in GitHub Settings → Webhooks. Use application/json, SSL verification, and only the configured events. Never put either secret in workflow YAML.';

export default function GitHubIntegration({ org }: { org: string }) {
  const [mappings, setMappings] = useState<z.infer<typeof mapping>[]>([]);
  const [deliveries, setDeliveries] = useState<z.infer<typeof delivery>[]>([]);
  const [secret, setSecret] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    let active = true;
    void Promise.all([
      request(
        `/github/mappings?organization_id=${org}&offset=${offset}`,
        z.array(mapping),
      ),
      request(
        `/github/deliveries?organization_id=${org}&offset=${offset}`,
        z.array(delivery),
      ),
    ])
      .then(([a, b]) => {
        if (active) {
          setLoaded(true);
          setMappings(a);
          setDeliveries(b);
          setError('');
        }
      })
      .catch(() => {
        if (active) {
          setLoaded(false);
          setError(
            'Unable to load GitHub integration. Administrator access is required.',
          );
        }
      });
    return () => {
      active = false;
    };
  }, [org, reload, offset]);
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setMessage('Copied.');
    } catch {
      setError('Clipboard unavailable. Select and copy the text manually.');
    }
  }
  async function create(form: HTMLFormElement) {
    setBusy(true);
    setError('');
    setSecret('');
    setMessage('');
    const data = new FormData(form);
    try {
      const issued = await request(
        `/github/mappings?organization_id=${org}`,
        mapping.extend({ secret: z.string() }),
        'POST',
        {
          repository: data.get('repository'),
          branch: data.get('branch'),
          project_id: data.get('project'),
          target_id: data.get('target'),
          policy_id: data.get('policy'),
          environment: data.get('environment'),
          events: data.getAll('event'),
        },
      );
      setSecret(issued.secret);
      setEndpoint(issued.webhook_path);
      setReload((v) => v + 1);
      setMessage(
        'Mapping created. Copy the secret now; it cannot be retrieved again.',
      );
      form.reset();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to create mapping.');
    } finally {
      setBusy(false);
    }
  }
  async function action(row: z.infer<typeof mapping>, disable: boolean) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      if (disable) {
        await request(
          `/workspace/integrations/${row.integration_id}?organization_id=${org}`,
          z.object({ ok: z.boolean() }),
          'DELETE',
        );
        setReload((v) => v + 1);
        setMessage('Mapping disabled.');
      } else {
        const result = await request(
          `/github/mappings/${row.id}/test?organization_id=${org}`,
          z.object({ ok: z.boolean(), message: z.string() }),
          'POST',
        );
        setMessage(result.message);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to verify mapping.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="delivery-tools github-tools"
      aria-label="GitHub Actions setup"
    >
      <h2>GitHub Actions and webhooks</h2>
      <p>{instructions}</p>
      <Button onClick={() => void copy(instructions)}>
        Copy secrets instructions
      </Button>
      <p>
        Automated scans use registered passive targets with current
        authorization and an active deterministic gate. Branch matching is
        exact; pull requests match the base branch and forks are rejected. To
        change settings or rotate a secret, disable the mapping and create a
        replacement.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void create(e.currentTarget);
        }}
      >
        <h3>Repository mapping</h3>
        <label>
          Repository (owner/repo)
          <input
            required
            name="repository"
            pattern="[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
            maxLength={200}
          />
        </label>
        <label>
          Push / PR base branch
          <input required name="branch" maxLength={120} defaultValue="main" />
        </label>
        <label>
          Project ID
          <input required name="project" pattern="[a-fA-F0-9-]{36}" />
        </label>
        <label>
          Registered target ID
          <input required name="target" pattern="[a-fA-F0-9-]{36}" />
        </label>
        <label>
          Passive scanner policy ID
          <input required name="policy" pattern="[a-fA-F0-9-]{36}" />
        </label>
        <label>
          Target environment
          <input
            required
            name="environment"
            maxLength={64}
            defaultValue="development"
          />
        </label>
        <fieldset>
          <legend>GitHub events</legend>
          {['push', 'pull_request'].map((value) => (
            <label key={value}>
              <input
                type="checkbox"
                name="event"
                value={value}
                defaultChecked={value === 'push'}
              />
              {value}
            </label>
          ))}
        </fieldset>
        <Button type="submit" disabled={busy}>
          Create GitHub mapping
        </Button>
      </form>
      {secret && (
        <div>
          <p>
            Webhook path (append to your public API origin):{' '}
            <code>{endpoint}</code>
          </p>
          <label>
            One-time webhook secret
            <input
              readOnly
              value={secret}
              onFocus={(e) => e.currentTarget.select()}
            />
          </label>
          <Button onClick={() => void copy(secret)}>Copy webhook secret</Button>
          <Button onClick={() => setSecret('')}>Dismiss webhook secret</Button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      <Button onClick={() => setReload((v) => v + 1)}>
        Refresh GitHub records
      </Button>
      <h3>Configured repositories</h3>
      {loaded && mappings.length === 0 && <p>No mappings on this page.</p>}
      {mappings.map((row) => (
        <article key={row.id}>
          <h4>
            {row.repository} · {row.branch}
          </h4>
          <p>
            {row.enabled ? 'Enabled' : 'Disabled'} · {row.events.join(', ')} ·{' '}
            {row.environment}
          </p>
          <p>
            Target {row.target_id} v{row.target_version} · Scanner policy{' '}
            {row.policy_id} v{row.policy_version} · Gate v
            {row.gate_policy_version}
          </p>
          <p>
            <code>{row.webhook_path}</code>
          </p>
          <Button
            disabled={busy || !row.enabled}
            onClick={() => void action(row, false)}
          >
            Test connection for {row.repository}
          </Button>
          <Button
            disabled={busy || !row.enabled}
            onClick={() => void action(row, true)}
          >
            Disable {row.repository}
          </Button>
        </article>
      ))}
      <h3>Last GitHub deliveries</h3>
      <p>
        Connection testing checks local readiness. A signed GitHub ping confirms
        inbound delivery. Only safe receipt metadata is retained.
      </p>
      {loaded && deliveries.length === 0 && (
        <p>No GitHub deliveries on this page.</p>
      )}
      {deliveries.map((row) => (
        <p key={row.id}>
          {row.event} · {row.state} · {row.delivery_id} ·{' '}
          {new Date(row.created_at).toLocaleString()}
        </p>
      ))}
      <Button
        disabled={offset === 0}
        onClick={() => setOffset((v) => Math.max(0, v - 100))}
      >
        Previous GitHub records
      </Button>
      <Button
        disabled={mappings.length < 100 && deliveries.length < 100}
        onClick={() => setOffset((v) => v + 100)}
      >
        Next GitHub records
      </Button>
    </section>
  );
}
