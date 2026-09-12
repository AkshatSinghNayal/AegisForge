import { usePagedOptions } from './usePagedOptions';
import { MoreOptions } from './PagedOptions';
import { useEffect, useState, type FormEvent } from 'react';
import {
  Link,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { z } from 'zod';
import { Button, Input } from '@/ui';
import { policySchema, targetSchema } from './configurationModels';
import { eventSchema, mergeEvents, type Event } from './scanEvents';
import { ApiError, request, scanStream } from './client';

const scanSchema = z.object({
  id: z.string().uuid(),
  state: z.string(),
  mode: z.string(),
  target: z.string(),
  target_id: z.string(),
  project: z.string(),
  project_id: z.string(),
  initiator: z.string(),
  trigger: z.object({
    source: z.string(),
    branch: z.string().nullable(),
    commit: z.string().nullable(),
  }),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  deadline_at: z.string(),
  completeness: z.string(),
  enrichment_status: z.string(),
  report_status: z.string(),
  is_demo: z.boolean(),
  effective_gate: z.enum(['pass', 'warn', 'fail', 'incomplete']),
  gate_reason: z.string(),
  failure_code: z.string().nullable(),
});
type Scan = z.infer<typeof scanSchema>;

const terminal = new Set(['completed', 'failed', 'cancelled', 'timed_out']);
const stages = [
  'queued',
  'validating_target',
  'preparing_scanner',
  'spidering',
  'passive_scanning',
  'active_scanning',
  'collecting_results',
  'normalizing',
  'enriching',
  'evaluating_policy',
  'generating_report',
  'completed',
];
const label = (value: string) => value.replaceAll('_', ' ');
const errorText = (e: unknown) =>
  e instanceof Error ? e.message : 'Unable to load scans.';
const url = (org: string, suffix = '') =>
  `/scans${suffix}?organization_id=${encodeURIComponent(org)}`;
const duration = (scan: Scan, clock: number) =>
  `${Math.max(0, Math.floor(((scan.finished_at ? Date.parse(scan.finished_at) : clock) - Date.parse(scan.started_at ?? scan.created_at)) / 1000))}s`;

function ScanList({ org, role }: { org: string; role: string }) {
  const [scans, setScans] = useState<Scan[]>();
  const [clock, setClock] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [filters, setFilters] = useSearchParams();
  const filterQuery = ['state', 'project', 'target']
    .map((key) =>
      filters.get(key)
        ? `&${key}=${encodeURIComponent(filters.get(key) || '')}`
        : '',
    )
    .join('');
  useEffect(() => {
    let active = true;
    void request(url(org) + filterQuery, z.array(scanSchema))
      .then((data) => {
        if (active) {
          setScans(data);
          setError('');
        }
      })
      .catch((e: unknown) => {
        if (active) setError(errorText(e));
      });
    return () => {
      active = false;
    };
  }, [org, refresh, filterQuery]);
  return (
    <section>
      <p className="eyebrow">WORKSPACE / SCANS</p>
      <h1>Scan history</h1>
      <p className="muted">
        Execution progress and security outcomes remain separate.
      </p>
      <label>
        Scan state
        <select
          value={filters.get('state') || ''}
          onChange={(e) => {
            const next = new URLSearchParams(filters);
            if (e.target.value) next.set('state', e.target.value);
            else next.delete('state');
            setFilters(next);
          }}
        >
          <option value="">All states</option>
          {['completed', 'failed', 'timed_out', 'cancelled', 'queued'].map(
            (state) => (
              <option key={state} value={state}>
                {label(state)}
              </option>
            ),
          )}
        </select>
      </label>
      <div className="scan-actions">
        {role !== 'viewer' && (
          <Link className="button primary" to="/app/scans/new">
            New scan
          </Link>
        )}
        <Button variant="secondary" onClick={() => setRefresh((n) => n + 1)}>
          Refresh scans
        </Button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!scans && !error && <p role="status">Loading scans…</p>}
      {scans?.length === 0 && (
        <p>No scans yet. Choose an authorized target to begin.</p>
      )}
      <div className="scan-list">
        {scans?.map((scan) => (
          <article className="scan-card" key={scan.id}>
            <div className="scan-actions">
              <Link to={`/app/scans/${scan.id}`}>
                <strong>{scan.target}</strong>
              </Link>
              <span className="badge">{label(scan.state)}</span>
              {scan.is_demo && <span className="badge">DEMO</span>}
            </div>
            <p>
              {scan.project} · {scan.mode} · Initiated by {scan.initiator}
            </p>
            <p className="muted">
              Started{' '}
              {scan.started_at
                ? new Date(scan.started_at).toLocaleString()
                : 'Not started'}{' '}
              · Duration {duration(scan, clock)}
            </p>
            {(scan.trigger.branch || scan.trigger.commit) && (
              <p>
                Branch {scan.trigger.branch ?? '—'} · Commit{' '}
                {scan.trigger.commit ?? '—'}
              </p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

const targetOptionsSchema = z.array(targetSchema);
const policyOptionsSchema = z.array(policySchema);
function NewScan({ org, role }: { org: string; role: string }) {
  const navigate = useNavigate();
  const targetOptions = usePagedOptions(
    `/organizations/${org}/targets`,
    targetOptionsSchema,
  );
  const policyOptions = usePagedOptions(
    `/organizations/${org}/policies`,
    policyOptionsSchema,
  );
  const targets = (targetOptions.data ?? []).filter(
    (v) => v.status === 'active',
  );
  const policies = policyOptions.data ?? [];
  const [targetId, setTarget] = useState('');
  const [policyId, setPolicy] = useState('');
  const [step, setStep] = useState(0);
  const [branch, setBranch] = useState('');
  const [commit, setCommit] = useState('');
  const [source, setSource] = useState('manual');
  const [ack, setAck] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const target = targets.find((t) => t.id === targetId);
  const policy = policies.find((p) => p.id === policyId);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!target || !policy) return;
    if (step < 3) {
      setStep(step + 1);
      return;
    }
    setBusy(true);
    setError('');
    const body = {
      target_id: target.id,
      target_version: target.version,
      policy_id: policy.id,
      policy_version: policy.version,
      secret_reference_ids: target.credentials
        .filter((c) => !c.revoked)
        .map((c) => c.id),
      trigger: { source, branch: branch || null, commit: commit || null },
      active_acknowledgement: ack,
    };
    try {
      let token: string | undefined;
      if (policy.mode === 'active')
        token = (
          await request(
            url(org, '/confirmations'),
            z.object({ token: z.string(), expires_at: z.string() }),
            'POST',
            body,
          )
        ).token;
      const result = await request(
        url(org),
        scanSchema,
        'POST',
        { ...body, ...(token ? { confirmation_token: token } : {}) },
        true,
        { 'Idempotency-Key': key },
      );
      navigate(`/app/scans/${result.id}`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (role === 'viewer') return <p>Your role cannot start scans.</p>;
  return (
    <section>
      <p className="eyebrow">WORKSPACE / NEW SCAN</p>
      <h1>Review. Authorize. Run.</h1>
      <MoreOptions label="targets" options={targetOptions} />
      <MoreOptions label="policies" options={policyOptions} />
      <ol className="scan-stepper" aria-label="Scan setup steps">
        {['Target', 'Policy', 'Trigger & consent', 'Final review'].map(
          (name, i) => (
            <li key={name} aria-current={step === i ? 'step' : undefined}>
              {i + 1}. {name}
            </li>
          ),
        )}
      </ol>
      <form
        className="config-form"
        onSubmit={(e) => void submit(e)}
        onChange={() => setKey(crypto.randomUUID())}
      >
        {step === 0 && (
          <>
            <h2>Choose an authorized target</h2>
            <label>
              Target
              <select
                required
                value={targetId}
                onChange={(e) => {
                  setAck(false);
                  setTarget(e.target.value);
                  setPolicy(
                    targets.find((t) => t.id === e.target.value)?.policy_id ??
                      '',
                  );
                }}
              >
                <option value="">Select target</option>
                {targets.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.display_name} · {t.environment}
                  </option>
                ))}
              </select>
            </label>
            <Link to="/app/targets/new">Register a target</Link>
          </>
        )}
        {step === 1 && (
          <>
            <h2>Choose an immutable policy version</h2>
            <label>
              Policy
              <select
                required
                value={policyId}
                onChange={(e) => {
                  setPolicy(e.target.value);
                  setAck(false);
                }}
              >
                <option value="">Select policy</option>
                {policies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} v{p.version} · {p.mode}
                  </option>
                ))}
              </select>
            </label>
            {policy && (
              <p>
                Maximum {policy.max_duration_seconds}s · {policy.max_requests}{' '}
                requests · depth {policy.max_depth}
              </p>
            )}
          </>
        )}
        {step === 2 && (
          <>
            <h2>Trigger metadata and consent</h2>
            <label>
              Trigger
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="manual">Manual</option>
                <option value="ci">CI</option>
              </select>
            </label>
            <Input
              label="Branch (optional)"
              value={branch}
              maxLength={120}
              pattern="[A-Za-z0-9._\/\-]+"
              onChange={(e) => setBranch(e.target.value)}
            />
            <Input
              label="Commit (optional)"
              value={commit}
              pattern="[0-9a-fA-F]{7,40}"
              onChange={(e) => setCommit(e.target.value)}
            />
            {policy?.mode === 'active' && (
              <label className="scan-consent">
                <input
                  type="checkbox"
                  required
                  checked={ack}
                  onChange={(e) => setAck(e.target.checked)}
                />
                I authorize active requests against this target with this
                policy. Active scans can change data or disrupt service.
              </label>
            )}
          </>
        )}
        {step === 3 && (
          <>
            <h2>Final review</h2>
            <dl className="scan-details">
              <dt>Target</dt>
              <dd>
                {target?.display_name} · version {target?.version}
              </dd>
              <dt>Policy</dt>
              <dd>
                {policy?.name} · version {policy?.version} · {policy?.mode}
              </dd>
              <dt>Trigger</dt>
              <dd>
                {source} · {branch || 'No branch'} · {commit || 'No commit'}
              </dd>
              <dt>Credentials</dt>
              <dd>
                {target?.credentials.filter((c) => !c.revoked).length} masked
                reference(s)
              </dd>
            </dl>
            <p>
              The server rechecks current authorization and limits. When
              enabled, the mock provider produces only labeled demo progress; a
              missing provider fails visibly.
            </p>
          </>
        )}
        {error && <p role="alert">{error}</p>}
        <div className="scan-actions">
          {step > 0 && (
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() => setStep(step - 1)}
            >
              Back
            </Button>
          )}
          <Button
            type="submit"
            disabled={busy || (step === 0 && !target) || (step > 0 && !policy)}
          >
            {busy ? 'Starting…' : step === 3 ? 'Start scan' : 'Continue'}
          </Button>
          <Link to="/app/scans">Scan history</Link>
        </div>
      </form>
    </section>
  );
}

function LiveScan({ org, role }: { org: string; role: string }) {
  const { scanId = '' } = useParams();
  const [scan, setScan] = useState<Scan>();
  const [events, setEvents] = useState<Event[]>([]);
  const [connection, setConnection] = useState('Connecting');
  const [error, setError] = useState('');
  const [clock, setClock] = useState(Date.now);
  const [cancelling, setCancelling] = useState(false);
  useEffect(() => {
    const interval = window.setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(interval);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let cursor = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    const refresh = async () => {
      const data = await request(url(org, `/${scanId}`), scanSchema);
      if (!controller.signal.aborted) setScan(data);
    };
    const connect = async () => {
      try {
        await refresh();
        const response = await scanStream(
          url(org, `/${scanId}/events`),
          cursor,
          controller.signal,
        );
        if (!response.body) throw new Error('Live stream unavailable.');
        setConnection('Connected');
        attempts = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let pending = '';
        try {
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            pending += decoder
              .decode(value, { stream: true })
              .replaceAll('\r\n', '\n');
            let end: number;
            while ((end = pending.indexOf('\n\n')) >= 0) {
              const frame = pending.slice(0, end);
              pending = pending.slice(end + 2);
              if (frame.includes('event: session_expired'))
                throw new Error('Session expired; reconnecting.');
              if (frame.includes('event: access_revoked'))
                throw new ApiError(
                  403,
                  'Access changed. Reload your workspace.',
                );
              if (frame.includes('event: end')) {
                await refresh();
                setConnection('History synchronized');
                return;
              }
              const data = frame
                .split('\n')
                .find((line) => line.startsWith('data: '));
              if (frame.includes('event: scan') && data) {
                const event = eventSchema.parse(JSON.parse(data.slice(6)));
                if (event.sequence <= cursor) continue;
                if (event.sequence !== cursor + 1)
                  throw new Error('Event gap; replaying history.');
                cursor = event.sequence;
                setEvents((previous) => mergeEvents(previous, event));
                await refresh();
              }
            }
            if (pending.length > 65536) throw new Error('Invalid live event.');
          }
        } finally {
          await reader.cancel();
        }
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && [401, 403, 404].includes(e.status)) {
          setError(errorText(e));
          setConnection('Access unavailable');
          return;
        }
      }
      if (!controller.signal.aborted) {
        setConnection('Reconnecting — replaying saved events');
        timer = setTimeout(
          () => void connect(),
          Math.min(1000 * 2 ** attempts++, 10000),
        );
      }
    };
    void connect();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [org, scanId]);
  async function cancel() {
    setCancelling(true);
    setError('');
    try {
      setScan(await request(url(org, `/${scanId}/cancel`), scanSchema, 'POST'));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setCancelling(false);
    }
  }
  return (
    <section>
      <p className="eyebrow">WORKSPACE / LIVE SCAN</p>
      <h1>{scan?.target ?? 'Scan progress'}</h1>
      <p role="status">{connection}</p>
      {error && <p role="alert">{error}</p>}
      {scan && (
        <>
          <div className="scan-actions">
            <span className="badge">{label(scan.state)}</span>
            {scan.is_demo && <strong>DEMO · Simulated lifecycle</strong>}
            <span>Elapsed {duration(scan, clock)}</span>
            {!terminal.has(scan.state) && role !== 'viewer' && (
              <Button
                variant="secondary"
                disabled={cancelling}
                onClick={() => void cancel()}
              >
                {cancelling ? 'Cancelling…' : 'Cancel scan'}
              </Button>
            )}
          </div>
          <p>
            {scan.project} · {scan.mode} · Initiated by {scan.initiator}
          </p>
          <p>
            Current stage: <strong>{label(scan.state)}</strong>
          </p>
          <ol className="scan-stepper" aria-label="Execution stages">
            {stages
              .filter((s) => s !== 'active_scanning' || scan.mode === 'active')
              .map((s) => (
                <li
                  key={s}
                  aria-current={scan.state === s ? 'step' : undefined}
                >
                  {label(s)}
                </li>
              ))}
          </ol>
          <dl className="scan-details">
            <dt>Completeness</dt>
            <dd>{scan.completeness}</dd>
            <dt>Enrichment</dt>
            <dd>{scan.enrichment_status}</dd>
            <dt>Report</dt>
            <dd>{scan.report_status}</dd>
            <dt>Effective gate</dt>
            <dd>
              <span>
                {scan.effective_gate} · {label(scan.gate_reason)}
              </span>{' '}
              <Link
                to={`/app/gates?project=${scan.project_id}&scan=${scan.id}`}
              >
                View policy evaluations
              </Link>
            </dd>
          </dl>
          {scan.failure_code && (
            <p role="alert">Scan stopped: {label(scan.failure_code)}.</p>
          )}
          {scan.is_demo && (
            <p className="workspace-notice">
              These are deterministic demo events. No target requests,
              vulnerability findings or security report are produced.
            </p>
          )}
        </>
      )}
      <div className="scan-terminal" aria-label="Sanitized scan event timeline">
        <div className="scan-terminal-title">
          AEGISFORGE / EVENT STREAM <span>Sanitized · Ordered · Durable</span>
        </div>
        <ol>
          {events.map((event) => (
            <li key={event.sequence}>
              <span className="muted">
                {String(event.sequence).padStart(3, '0')} ·{' '}
                {new Date(event.created_at).toLocaleTimeString()}
              </span>{' '}
              <strong>{label(event.stage)}</strong>{' '}
              <span>
                {label(event.message_code)} · attempt {event.attempt}
              </span>
            </li>
          ))}
        </ol>
        {events.length === 0 && <p>Waiting for saved events…</p>}
      </div>
      <Link to="/app/scans">Back to scan history</Link>
    </section>
  );
}
export default function Scans(props: { org: string; role: string }) {
  return (
    <div className="configuration">
      <Routes>
        <Route path="scans" element={<ScanList {...props} />} />
        <Route path="scans/new" element={<NewScan {...props} />} />
        <Route
          path="scans/:scanId"
          element={<LiveScan key={location.pathname} {...props} />}
        />
      </Routes>
    </div>
  );
}
