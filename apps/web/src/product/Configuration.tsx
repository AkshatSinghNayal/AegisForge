import { usePagedOptions } from './usePagedOptions';
import { MoreOptions } from './PagedOptions';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { z } from 'zod';
import { Button, Input } from '@/ui';
import { request } from './client';
import {
  targetSchema,
  policySchema,
  credentialSchema,
} from './configurationModels';

const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  description: z.string(),
  repository_url: z.string().nullable(),
  default_branch: z.string(),
  environment: z.string(),
  owner_id: z.string(),
  member_ids: z.array(z.string()),
  status: z.string(),
  version: z.number(),
});
const membersSchema = z.array(
  z.object({ id: z.string(), display_name: z.string(), status: z.string() }),
);
type Project = z.infer<typeof projectSchema>;
type Target = z.infer<typeof targetSchema>;
type Policy = z.infer<typeof policySchema>;
type Context = { org: string; role: string; userId: string };
const split = (s: string) =>
  s
    .split(/[\n,]/)
    .map((v) => v.trim())
    .filter(Boolean);
const errorText = (e: unknown) =>
  e instanceof Error ? e.message : 'The request could not be completed.';
const canAdmin = (role: string) => ['owner', 'admin'].includes(role);
function useData<T>(path: string, schema: z.ZodType<T>) {
  const [result, setResult] = useState<{ path: string; data: T }>();
  const [failure, setFailure] = useState<{ path: string; message: string }>();
  const [version, refresh] = useState(0);
  useEffect(() => {
    let active = true;
    void request(path, schema)
      .then((result) => {
        if (active) {
          setResult({ path, data: result });
          setFailure(undefined);
        }
      })
      .catch((e: unknown) => {
        if (active) {
          setResult(undefined);
          setFailure({ path, message: errorText(e) });
        }
      });
    return () => {
      active = false;
    };
  }, [path, schema, version]);
  return {
    data: result?.path === path ? result.data : undefined,
    error: failure?.path === path ? failure.message : '',
    refresh: () => refresh((v) => v + 1),
  };
}
const projectsSchema = z.array(projectSchema);
const targetsSchema = z.array(targetSchema);
const policiesSchema = z.array(policySchema);
function Feedback({ error }: { error: string }) {
  return error ? (
    <p role="alert" className="workspace-notice">
      {error}
    </p>
  ) : null;
}
function LoadingDetail({
  title,
  error,
  retry,
}: {
  title: string;
  error: string;
  retry: () => void;
}) {
  return (
    <>
      <h1>{title}</h1>
      {error ? (
        <Button onClick={retry}>Retry</Button>
      ) : (
        <div className="skeleton" role="status">
          Loading {title.toLowerCase()}…
        </div>
      )}
    </>
  );
}
function Select({
  label,
  name,
  value,
  onChange,
  children,
}: {
  label: string;
  name?: string;
  value?: string;
  onChange?: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label>
      {label}
      <select
        name={name}
        value={value}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
      >
        {children}
      </select>
    </label>
  );
}
export default function Configuration(ctx: Context) {
  return (
    <div className="configuration">
      <Routes>
        <Route path="projects" element={<ProjectList {...ctx} />} />
        <Route path="projects/new" element={<ProjectEditor {...ctx} />} />
        <Route path="projects/:id" element={<ProjectDetail {...ctx} />} />
        <Route
          path="projects/:id/settings"
          element={<ProjectSettings {...ctx} />}
        />
        <Route path="targets" element={<TargetList {...ctx} />} />
        <Route path="targets/new" element={<TargetWizard {...ctx} />} />
        <Route path="targets/:id" element={<TargetDetail {...ctx} />} />
        <Route path="policies" element={<PolicyList {...ctx} />} />
        <Route path="policies/new" element={<PolicyEditor {...ctx} />} />
        <Route path="policies/:id" element={<PolicyDetail {...ctx} />} />
      </Routes>
    </div>
  );
}
function ProjectList(ctx: Context) {
  const options = usePagedOptions(
    `/organizations/${ctx.org}/projects`,
    projectsSchema,
  );
  const { data, error, refresh } = options;
  return (
    <>
      <MoreOptions label="projects" options={options} />
      <p className="eyebrow">APPLICATION INVENTORY</p>
      <h1>Projects</h1>
      <p>Define ownership, organize targets, and retain security history.</p>
      {canAdmin(ctx.role) && (
        <Link className="button primary" to="/app/projects/new">
          Create project
        </Link>
      )}
      <Feedback error={error} />
      {!data &&
        (error ? (
          <Button onClick={refresh}>Retry</Button>
        ) : (
          <div className="skeleton" role="status">
            Loading records…
          </div>
        ))}
      <div className="config-grid">
        {data?.map((p) => (
          <article key={p.id}>
            <span className="badge">
              {p.status === 'active' ? p.environment : 'Archived'}
            </span>
            <h2>
              <Link to={`/app/projects/${p.id}`}>{p.name}</Link>
            </h2>
            <p>{p.description || 'No description provided.'}</p>
            <small>
              {p.slug} · {p.default_branch}
            </small>
          </article>
        ))}
      </div>
      {data?.length === 0 && (
        <p>No projects yet. An administrator can create your first project.</p>
      )}
    </>
  );
}
const overviewSchema = z.object({
  project: projectSchema,
  open_findings: z.number(),
  targets: targetsSchema,
  recent_scans: z.array(
    z.object({
      id: z.string(),
      state: z.string(),
      completeness: z.string(),
      created_at: z.string(),
    }),
  ),
});
function ProjectDetail(ctx: Context) {
  const { id } = useParams();
  const targetOptions = usePagedOptions(
    `/organizations/${ctx.org}/targets?project_id=${id}`,
    targetsSchema,
  );
  const { data, error, refresh } = useData(
    `/organizations/${ctx.org}/projects/${id}`,
    overviewSchema,
  );
  const [feedback, setFeedback] = useState('');
  async function archive() {
    try {
      await request(
        `/organizations/${ctx.org}/projects/${id}${data?.project.status === 'active' ? '' : '/restore'}`,
        z.unknown(),
        data?.project.status === 'active' ? 'DELETE' : 'POST',
      );
      refresh();
    } catch (e) {
      setFeedback(errorText(e));
    }
  }
  return (
    <>
      <Link to="/app/projects">← Projects</Link>
      <Feedback error={error || feedback} />
      {!data && <LoadingDetail title="Project" error={error} retry={refresh} />}
      {data && (
        <>
          <h1>{data.project.name}</h1>
          <p>{data.project.description}</p>
          <span className="badge">
            {data.project.status === 'active'
              ? data.project.environment
              : 'Archived'}
          </span>
          {canAdmin(ctx.role) && (
            <div className="config-actions">
              <Link
                className="button secondary"
                to={`/app/projects/${id}/settings`}
              >
                Project settings
              </Link>
              <Button variant="secondary" onClick={() => void archive()}>
                {data.project.status === 'active'
                  ? 'Archive project'
                  : 'Restore project'}
              </Button>
            </div>
          )}
          <div className="config-grid">
            <article>
              <h2>Open findings</h2>
              <strong className="config-number">{data.open_findings}</strong>
              <p>
                Recorded open findings. An empty count does not establish scan
                coverage.
              </p>
            </article>
            <article>
              <h2>Recent scans</h2>
              {data.recent_scans.length ? (
                <ul>
                  {data.recent_scans.map((s) => (
                    <li key={s.id}>
                      {s.state} · {s.completeness} ·{' '}
                      {new Date(s.created_at).toLocaleString()}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No scans recorded. Start a scan from Scan history.</p>
              )}
            </article>
          </div>
          <h2>Targets</h2>
          {ctx.role !== 'viewer' && data.project.status === 'active' && (
            <Link
              className="button primary"
              to={`/app/targets/new?project=${id}`}
            >
              Register target
            </Link>
          )}
          <MoreOptions label="targets" options={targetOptions} />
          {targetOptions.data && <TargetCards data={targetOptions.data} />}
        </>
      )}
    </>
  );
}
function ProjectSettings(ctx: Context) {
  const { id } = useParams();
  const { data, error, refresh } = useData(
    `/organizations/${ctx.org}/projects/${id}`,
    overviewSchema,
  );
  return (
    <>
      <Feedback error={error} />
      {!data && (
        <LoadingDetail title="Project settings" error={error} retry={refresh} />
      )}
      {data && <ProjectEditor {...ctx} existing={data.project} />}
    </>
  );
}
function ProjectEditor(ctx: Context & { existing?: Project }) {
  const navigate = useNavigate();
  const { data: members, error } = useData(
    `/organizations/${ctx.org}/members`,
    membersSchema,
  );
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  if (!canAdmin(ctx.role))
    return (
      <>
        <h1>Project settings</h1>
        <p role="alert">Permission denied. Your role cannot edit projects.</p>
      </>
    );
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const f = new FormData(e.currentTarget);
    try {
      const body = {
        ...Object.fromEntries(f),
        member_ids: f.getAll('member_ids'),
        repository_url: f.get('repository_url') || null,
      };
      const result = await request(
        `/organizations/${ctx.org}/projects${ctx.existing ? `/${ctx.existing.id}` : ''}`,
        projectSchema,
        ctx.existing ? 'PUT' : 'POST',
        body,
      );
      navigate(`/app/projects/${result.id}`);
    } catch (e) {
      setFeedback(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h1>{ctx.existing ? 'Project settings' : 'Create project'}</h1>
      <Feedback error={error || feedback} />
      <form onSubmit={(e) => void submit(e)} className="config-form">
        <Input
          label="Project name"
          name="name"
          required
          maxLength={120}
          defaultValue={ctx.existing?.name}
        />
        <Input
          label="Slug"
          name="slug"
          required
          pattern="[a-z0-9]+(-[a-z0-9]+)*"
          defaultValue={ctx.existing?.slug}
        />
        <label>
          Description
          <textarea
            name="description"
            maxLength={4000}
            defaultValue={ctx.existing?.description}
          />
        </label>
        <Input
          label="Repository URL"
          name="repository_url"
          type="url"
          defaultValue={ctx.existing?.repository_url ?? ''}
        />
        <Input
          label="Default branch"
          name="default_branch"
          required
          defaultValue={ctx.existing?.default_branch ?? 'main'}
        />
        <Input
          label="Environment"
          name="environment"
          required
          maxLength={64}
          defaultValue={ctx.existing?.environment ?? 'development'}
        />
        <label>
          Project owner
          <select
            name="owner_id"
            defaultValue={ctx.existing?.owner_id}
            required
          >
            {members
              ?.filter((m) => m.status === 'active')
              .map((m) => (
                <option value={m.id} key={m.id}>
                  {m.display_name}
                </option>
              ))}
          </select>
        </label>
        <fieldset>
          <legend>Assigned members</legend>
          {members
            ?.filter((m) => m.status === 'active')
            .map((m) => (
              <label key={m.id} className="config-check">
                <input
                  type="checkbox"
                  name="member_ids"
                  value={m.id}
                  defaultChecked={ctx.existing?.member_ids.includes(m.id)}
                />
                {m.display_name}
              </label>
            ))}
        </fieldset>
        <Button type="submit" disabled={busy || !members?.length}>
          {busy ? 'Saving…' : 'Save project'}
        </Button>
      </form>
    </>
  );
}
function TargetCards({ data }: { data: Target[] }) {
  return (
    <div className="config-grid">
      {data.map((t) => (
        <article key={t.id}>
          <span className="badge">
            {t.status} · {t.kind.replaceAll('_', ' ')}
          </span>
          <h3>
            <Link to={`/app/targets/${t.id}`}>{t.display_name}</Link>
          </h3>
          <p className="break-url">{t.base_url}</p>
          <small>
            {t.verified_at
              ? `Reachability checked ${new Date(t.verified_at).toLocaleString()}`
              : 'Not validated'}
          </small>
        </article>
      ))}
    </div>
  );
}
function TargetList(ctx: Context) {
  const options = usePagedOptions(
    `/organizations/${ctx.org}/targets`,
    targetsSchema,
  );
  const { data, error, refresh } = options;
  return (
    <>
      <MoreOptions label="targets" options={options} />
      <h1>Targets</h1>
      <p>Every target needs explicit ownership and bounded scope.</p>
      {ctx.role !== 'viewer' && (
        <Link className="button primary" to="/app/targets/new">
          Register target
        </Link>
      )}
      <Feedback error={error} />
      {!data &&
        (error ? (
          <Button onClick={refresh}>Retry</Button>
        ) : (
          <div className="skeleton" role="status">
            Loading records…
          </div>
        ))}
      {data && <TargetCards data={data} />}
      {data?.length === 0 && <p>No targets registered.</p>}
    </>
  );
}
function TargetDetail(ctx: Context) {
  const { id } = useParams();
  const { data, error, refresh } = useData(
    `/organizations/${ctx.org}/targets/${id}`,
    targetSchema,
  );
  const [feedback, setFeedback] = useState('');
  async function remove(path: string) {
    try {
      await request(
        `/organizations/${ctx.org}/targets/${id}${path}`,
        z.unknown(),
        'DELETE',
      );
      refresh();
    } catch (e) {
      setFeedback(errorText(e));
    }
  }
  return (
    <>
      <Link to="/app/targets">← Targets</Link>
      <Feedback error={error || feedback} />
      {!data && <LoadingDetail title="Target" error={error} retry={refresh} />}
      {data && (
        <>
          <h1>{data.display_name}</h1>
          <p className="break-url">{data.base_url}</p>
          <span className="badge">
            {data.status} · {data.environment}
          </span>
          <div className="config-grid">
            <article>
              <h2>Authorized scope</h2>
              <p>{data.authorization_declaration}</p>
              <p>
                Consent recorded:{' '}
                {data.consent_at
                  ? new Date(data.consent_at).toLocaleString()
                  : 'Unavailable'}
              </p>
              <p>Include: {data.inclusion_patterns.join(', ')}</p>
              <p>Exclude: {data.exclusion_patterns.join(', ') || 'None'}</p>
              <p>Methods: {data.allowed_methods.join(', ')}</p>
              <p>
                {data.rate_limit} requests/second · {data.timeout_seconds}{' '}
                second limit
              </p>
              <p>
                OpenAPI:{' '}
                {data.has_openapi
                  ? 'Sanitized document stored'
                  : 'Not attached'}
              </p>
              {data.policy_id && (
                <Link to={`/app/policies/${data.policy_id}`}>
                  View exact policy version
                </Link>
              )}
            </article>
            <article>
              <h2>Authentication references</h2>
              {data.credentials.length === 0 && (
                <p>No authentication configured.</p>
              )}
              {data.credentials.map((c) => (
                <div key={c.id}>
                  <p>
                    {c.auth_type} · {c.header_name} · {c.masked} · v{c.version}
                  </p>
                  {ctx.role !== 'viewer' && (
                    <Button
                      variant="secondary"
                      onClick={() => void remove(`/credentials/${c.id}`)}
                    >
                      Revoke credential
                    </Button>
                  )}
                </div>
              ))}
              {ctx.role !== 'viewer' && data.status === 'active' && (
                <CredentialEditor
                  org={ctx.org}
                  target={data.id}
                  onSaved={refresh}
                />
              )}
            </article>
          </div>
          <p className="workspace-notice">
            Saved consent does not start a scan. Active execution will require a
            separate one-use confirmation bound to the exact target,
            configuration and policy version.
          </p>
          {ctx.role !== 'viewer' && data.status === 'active' && (
            <Button variant="danger" onClick={() => void remove('')}>
              Deactivate target and revoke authorization
            </Button>
          )}
        </>
      )}
    </>
  );
}
function AuthFields({
  kind,
  setKind,
}: {
  kind: string;
  setKind: (v: string) => void;
}) {
  return (
    <>
      <Select label="Authentication type" value={kind} onChange={setKind}>
        <option value="none">None</option>
        <option value="api_key">API-key header</option>
        <option value="bearer">Bearer token</option>
        <option value="basic">Basic authentication</option>
      </Select>
      <p>OAuth is a future provider interface and cannot be configured yet.</p>
      {kind === 'api_key' && (
        <Input
          label="Header name"
          name="header_name"
          defaultValue="X-API-Key"
          required
        />
      )}
      {kind === 'basic' && (
        <Input label="Username" name="username" required autoComplete="off" />
      )}
      {kind !== 'none' && (
        <Input
          label={kind === 'basic' ? 'Password' : 'Secret value'}
          name="secret"
          type="password"
          required
          autoComplete="new-password"
          maxLength={4096}
        />
      )}
    </>
  );
}
function CredentialEditor({
  org,
  target,
  onSaved,
}: {
  org: string;
  target: string;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState('bearer');
  const [feedback, setFeedback] = useState('');
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    try {
      if (kind === 'none')
        throw new Error(
          'Select an authentication type. Use Revoke to remove an existing credential.',
        );
      await request(
        `/organizations/${org}/targets/${target}/credentials`,
        credentialSchema,
        'POST',
        {
          auth_type: kind,
          value: f.get('secret'),
          username: kind === 'basic' ? f.get('username') : null,
          header_name: f.get('header_name') ?? 'Authorization',
        },
      );
      form.reset();
      setFeedback('Credential rotated. The previous reference is revoked.');
      onSaved();
    } catch (e) {
      setFeedback(errorText(e));
    }
  }
  return (
    <details>
      <summary>Set or rotate credential</summary>
      <form onSubmit={(e) => void submit(e)}>
        <AuthFields kind={kind} setKind={setKind} />
        <Button type="submit">Save credential reference</Button>
        <Feedback error={feedback} />
      </form>
    </details>
  );
}
function PolicyList(ctx: Context) {
  const options = usePagedOptions(
    `/organizations/${ctx.org}/policies`,
    policiesSchema,
  );
  const [feedback, setFeedback] = useState('');
  async function presets() {
    try {
      await request(
        `/organizations/${ctx.org}/policies/presets`,
        policiesSchema,
        'POST',
      );
      refresh();
    } catch (e) {
      setFeedback(errorText(e));
    }
  }
  const { data, error, refresh } = options;
  return (
    <>
      <MoreOptions label="policies" options={options} />
      <h1>Scan policies</h1>
      <p>
        Versioned limits and deterministic CI thresholds. Existing targets
        retain their selected version.
      </p>
      {canAdmin(ctx.role) && (
        <div className="config-actions">
          <Link className="button primary" to="/app/policies/new">
            Create custom policy
          </Link>
          <Button variant="secondary" onClick={() => void presets()}>
            Add standard policies
          </Button>
        </div>
      )}
      <Feedback error={error || feedback} />
      {!data &&
        (error ? (
          <Button onClick={refresh}>Retry</Button>
        ) : (
          <div className="skeleton" role="status">
            Loading records…
          </div>
        ))}
      <div className="config-grid">
        {data?.map((p) => (
          <article key={p.id}>
            <span className="badge">
              {p.mode} · version {p.version}
            </span>
            <h2>
              <Link to={`/app/policies/${p.id}`}>{p.name}</Link>
            </h2>
            <p>
              {p.max_duration_seconds}s · {p.rate_limit} requests/second · fail
              at {p.fail_severity}
            </p>
            {p.mode === 'active' && (
              <p className="workspace-notice">
                Active rules may alter application data. Explicit scan
                confirmation is required at execution.
              </p>
            )}
            {p.allow_private && (
              <p>Administrator-authorized internal test policy</p>
            )}
          </article>
        ))}
      </div>
      {data?.length === 0 && (
        <p>
          An administrator must add standard policies or create a custom policy
          before target setup.
        </p>
      )}
    </>
  );
}
function PolicyDetail(ctx: Context) {
  const { id } = useParams();
  const { data, error, refresh } = useData(
    `/organizations/${ctx.org}/policies/${id}`,
    policySchema,
  );
  return (
    <>
      <Feedback error={error} />
      {!data && (
        <LoadingDetail title="Scan policy" error={error} retry={refresh} />
      )}
      {data && <PolicyEditor {...ctx} existing={data} />}
    </>
  );
}
function PolicyEditor(ctx: Context & { existing?: Policy }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState(ctx.existing?.mode ?? 'baseline');
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const body = {
        ...Object.fromEntries(f),
        mode,
        max_duration_seconds: Number(f.get('max_duration_seconds')),
        max_requests: Number(f.get('max_requests')),
        max_depth: Number(f.get('max_depth')),
        rate_limit: Number(f.get('rate_limit')),
        active_rule_allowlist:
          mode === 'active'
            ? split(String(f.get('active_rule_allowlist')))
            : [],
        excluded_paths: split(String(f.get('excluded_paths'))),
        allow_private: f.has('allow_private'),
        active_warning_acknowledged: f.has('active_warning_acknowledged'),
      };
      const result = await request(
        `/organizations/${ctx.org}/policies${ctx.existing ? `/${ctx.existing.id}` : ''}`,
        policySchema,
        ctx.existing ? 'PUT' : 'POST',
        body,
      );
      navigate('/app/policies');
      setFeedback(`Version ${result.version} created.`);
    } catch (e) {
      setFeedback(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Link to="/app/policies">← Policies</Link>
      <h1>{ctx.existing?.name ?? 'Create custom policy'}</h1>
      {ctx.existing && (
        <p>
          Version {ctx.existing.version} is immutable. Saving creates a new
          version; existing targets and scans retain this version.
        </p>
      )}
      <Feedback error={feedback} />
      <form className="config-form" onSubmit={(e) => void submit(e)}>
        <fieldset disabled={!canAdmin(ctx.role) || busy}>
          <legend>Policy configuration</legend>
          <Input
            label="Policy name"
            name="name"
            required
            defaultValue={ctx.existing?.name}
            readOnly={!!ctx.existing}
          />
          <Select
            label="Mode"
            value={mode}
            onChange={(v) => setMode(v as Policy['mode'])}
          >
            <option value="baseline">Passive baseline</option>
            <option value="passive">API import / passive</option>
            <option value="active">Authorized active</option>
          </Select>
          <Input
            label="Max duration (seconds)"
            type="number"
            name="max_duration_seconds"
            min={30}
            max={3600}
            defaultValue={ctx.existing?.max_duration_seconds ?? 300}
            required
          />
          <Input
            label="Maximum requests"
            type="number"
            name="max_requests"
            min={1}
            max={100000}
            defaultValue={ctx.existing?.max_requests ?? 1000}
            required
          />
          <Input
            label="Maximum depth"
            type="number"
            name="max_depth"
            min={0}
            max={20}
            defaultValue={ctx.existing?.max_depth ?? 5}
            required
          />
          <Input
            label="Rate limit (requests/second)"
            type="number"
            name="rate_limit"
            min={1}
            max={100}
            defaultValue={ctx.existing?.rate_limit ?? 2}
            required
          />
          <label>
            Spider
            <select
              name="spider"
              defaultValue={ctx.existing?.spider ?? 'traditional'}
            >
              <option value="none">None / API import</option>
              <option value="traditional">Traditional</option>
              <option value="ajax">AJAX</option>
            </select>
          </label>
          <label>
            Excluded paths (one per line)
            <textarea
              name="excluded_paths"
              defaultValue={ctx.existing?.excluded_paths.join('\n')}
            />
          </label>
          {['warn', 'fail'].map((level) => (
            <label key={level}>
              {level === 'warn'
                ? 'CI warning threshold'
                : 'CI failure threshold'}
              <select
                name={`${level}_severity`}
                defaultValue={
                  level === 'warn'
                    ? (ctx.existing?.warn_severity ?? 'medium')
                    : (ctx.existing?.fail_severity ?? 'high')
                }
              >
                {['informational', 'low', 'medium', 'high', 'critical'].map(
                  (s) => (
                    <option key={s}>{s}</option>
                  ),
                )}
              </select>
            </label>
          ))}
          {mode === 'active' && (
            <>
              <p className="workspace-notice">
                Active scanning can modify data, trigger workflows and affect
                availability. Use only explicitly authorized environments. This
                policy does not authorize execution.
              </p>
              <Input
                label="Active rule allowlist (comma-separated ZAP rule IDs)"
                name="active_rule_allowlist"
                required
                defaultValue={ctx.existing?.active_rule_allowlist.join(', ')}
              />
              <label className="config-check">
                <input
                  type="checkbox"
                  name="active_warning_acknowledged"
                  required
                />
                I understand the risks of active scanning.
              </label>
            </>
          )}
          <label className="config-check">
            <input
              type="checkbox"
              name="allow_private"
              defaultChecked={ctx.existing?.allow_private}
            />
            Permit RFC1918 / IPv6 ULA for internal development tests
          </label>
          <label>
            Internal test authorization (required for private ranges)
            <textarea
              name="internal_test_declaration"
              maxLength={1000}
              defaultValue={ctx.existing?.internal_test_declaration}
            />
          </label>
          <p>Loopback, link-local, metadata and multicast remain blocked.</p>
          {canAdmin(ctx.role) && (
            <Button type="submit" disabled={busy}>
              {ctx.existing ? 'Save new version' : 'Create policy'}
            </Button>
          )}
        </fieldset>
      </form>
    </>
  );
}
function TargetWizard(ctx: Context) {
  const navigate = useNavigate();
  const projectOptions = usePagedOptions(
    `/organizations/${ctx.org}/projects`,
    projectsSchema,
  );
  const policyOptions = usePagedOptions(
    `/organizations/${ctx.org}/policies`,
    policiesSchema,
  );
  const { data: projects, error: projectsError } = projectOptions;
  const { data: policies, error: policiesError } = policyOptions;
  const [step, setStep] = useState(0);
  const [kind, setKind] = useState('web_url');
  const [authType, setAuthType] = useState('none');
  const [values, setValues] = useState<Record<string, FormDataEntryValue>>({});
  const [upload, setUpload] = useState<{ name: string; content: string }>();
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const [validated, setValidated] = useState(false);
  const [consented, setConsented] = useState(false);
  // Authorization identity is derived by the backend; fetch the actor's membership ID without accepting a role from the form.
  const selfSchema = z.object({ member_id: z.string() });
  const [memberId, setMemberId] = useState('');
  useEffect(() => {
    let active = true;
    void request(`/organizations/${ctx.org}/configuration-identity`, selfSchema)
      .then((v) => {
        if (active) setMemberId(v.member_id);
      })
      .catch((e: unknown) => {
        if (active) setFeedback(errorText(e));
      });
    return () => {
      active = false;
    };
  }, [ctx.org]); // eslint-disable-line react-hooks/exhaustive-deps
  const selectedPolicy = policies?.find((p) => p.id === values.policy_id);
  function payload() {
    return {
      project_id: values.project_id,
      display_name: values.display_name,
      kind,
      base_url: values.base_url,
      openapi_url: kind === 'openapi_url' ? values.openapi_url : null,
      environment: values.environment,
      policy_id: values.policy_id,
      inclusion_patterns: split(String(values.inclusion_patterns || '/*')),
      exclusion_patterns: split(String(values.exclusion_patterns || '')),
      allowed_methods: split(String(values.allowed_methods || 'GET,HEAD')),
      rate_limit: Number(values.rate_limit),
      timeout_seconds: Number(values.timeout_seconds),
      authorization_owner_id: memberId,
      authorization_declaration: values.authorization_declaration,
      consent: true,
      upload_filename: upload?.name ?? null,
      upload_content: upload?.content ?? null,
      credential:
        authType === 'none'
          ? null
          : {
              auth_type: authType,
              header_name: values.header_name || 'Authorization',
              value: values.secret,
              username: authType === 'basic' ? values.username : null,
            },
    };
  }
  async function validate() {
    setBusy(true);
    setFeedback('');
    try {
      const result = await request(
        `/organizations/${ctx.org}/targets/validate`,
        z.object({
          valid: z.boolean(),
          message: z.string(),
          http_status: z.number(),
          openapi_valid: z.boolean(),
        }),
        'POST',
        payload(),
      );
      setValidated(result.valid);
      setFeedback(
        `${result.message} HTTP ${result.http_status}.${result.openapi_valid ? ' OpenAPI valid.' : ''}`,
      );
    } catch (e) {
      setFeedback(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    try {
      const target = await request(
        `/organizations/${ctx.org}/targets`,
        targetSchema,
        'POST',
        payload(),
      );
      setValues({});
      setUpload(undefined);
      navigate(`/app/targets/${target.id}`);
    } catch (e) {
      setFeedback(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  function next(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (step === 0 && kind === 'openapi_upload' && !upload) {
      setFeedback('Wait for the OpenAPI file to finish loading.');
      return;
    }
    const submitted = Object.fromEntries(new FormData(e.currentTarget));
    setValues((v) => ({ ...v, ...submitted }));
    setFeedback('');
    setValidated(false);
    setConsented(false);
    setStep((s) => s + 1);
  }
  if (ctx.role === 'viewer')
    return (
      <>
        <h1>Register target</h1>
        <MoreOptions label="projects" options={projectOptions} />
        <MoreOptions label="policies" options={policyOptions} />
        <p role="alert">
          Permission denied. Your role cannot register targets.
        </p>
      </>
    );
  return (
    <>
      <Link to="/app/targets">← Targets</Link>
      <h1>Register target</h1>
      <MoreOptions label="projects" options={projectOptions} />
      <MoreOptions label="policies" options={policyOptions} />
      <ol className="wizard-steps" aria-label="Setup progress">
        {['Basics', 'Scope', 'Authentication', 'Review and authorize'].map(
          (s, i) => (
            <li key={s} aria-current={step === i ? 'step' : undefined}>
              {i + 1}. {s}
            </li>
          ),
        )}
      </ol>
      <Feedback error={projectsError || policiesError || feedback} />
      {step < 3 ? (
        <form key={step} onSubmit={next} className="config-form">
          {step === 0 && (
            <>
              <h2>Basics</h2>
              <label>
                Project
                <select
                  name="project_id"
                  required
                  defaultValue={String(
                    values.project_id ||
                      new URLSearchParams(location.search).get('project') ||
                      '',
                  )}
                >
                  <option value="">Choose project</option>
                  {projects
                    ?.filter((p) => p.status === 'active')
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </select>
              </label>
              <Input
                label="Display name"
                name="display_name"
                required
                defaultValue={String(values.display_name || '')}
              />
              <Select
                label="Target type"
                value={kind}
                onChange={(v) => {
                  setKind(v);
                  setUpload(undefined);
                }}
              >
                <option value="web_url">Web URL</option>
                <option value="openapi_url">OpenAPI URL</option>
                <option value="openapi_upload">OpenAPI upload</option>
                <option value="rest_base_url">Direct REST base URL</option>
              </Select>
              <Input
                label="Base URL"
                name="base_url"
                type="url"
                required
                defaultValue={String(values.base_url || '')}
              />
              <p>
                HTTP(S) only, without embedded credentials or query strings.
              </p>
              {kind === 'openapi_url' && (
                <Input
                  label="OpenAPI document URL"
                  name="openapi_url"
                  type="url"
                  required
                  defaultValue={String(values.openapi_url || '')}
                />
              )}
              {kind === 'openapi_upload' && (
                <label>
                  OpenAPI JSON or YAML (max 1 MiB)
                  <input
                    type="file"
                    accept=".json,.yaml,.yml"
                    required={!upload}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      setUpload(undefined);
                      if (file) {
                        if (file.size > 1048576) {
                          e.target.value = '';
                          setFeedback(
                            'OpenAPI documents must be at most 1 MiB.',
                          );
                          return;
                        }
                        void file
                          .text()
                          .then((content) =>
                            setUpload({ name: file.name, content }),
                          );
                      }
                    }}
                  />
                  {upload && (
                    <span>{upload.name} ready for backend validation</span>
                  )}
                </label>
              )}
              <Input
                label="Environment"
                name="environment"
                required
                maxLength={64}
                defaultValue={String(values.environment || 'development')}
              />
            </>
          )}
          {step === 1 && (
            <>
              <h2>Scope</h2>
              <label>
                Policy version
                <select
                  name="policy_id"
                  required
                  defaultValue={String(values.policy_id || '')}
                >
                  <option value="">Choose a policy</option>
                  {policies?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · v{p.version} · {p.mode}
                    </option>
                  ))}
                </select>
              </label>
              <Link to="/app/policies">Manage policies</Link>
              <label>
                Inclusion patterns
                <textarea
                  name="inclusion_patterns"
                  required
                  defaultValue={String(values.inclusion_patterns || '/*')}
                />
              </label>
              <label>
                Exclusion patterns
                <textarea
                  name="exclusion_patterns"
                  defaultValue={String(values.exclusion_patterns || '')}
                />
              </label>
              <p>
                Path globs only, one per line. Exclusions take precedence at
                execution.
              </p>
              <Input
                label="Allowed methods (comma-separated)"
                name="allowed_methods"
                defaultValue={String(values.allowed_methods || 'GET,HEAD')}
                required
              />
              <Input
                label="Rate limit (requests/second)"
                name="rate_limit"
                type="number"
                min={1}
                max={100}
                defaultValue={Number(values.rate_limit || 2)}
                required
              />
              <Input
                label="Timeout (seconds)"
                name="timeout_seconds"
                type="number"
                min={30}
                max={3600}
                defaultValue={Number(values.timeout_seconds || 300)}
                required
              />
            </>
          )}
          {step === 2 && (
            <>
              <h2>Authentication</h2>
              <p>
                Values are encrypted by the configured local secret provider.
                Only masked reference metadata is returned. Validation requests
                never send your credentials.
              </p>
              <AuthFields kind={authType} setKind={setAuthType} />
              <label>
                Authorization declaration
                <textarea
                  name="authorization_declaration"
                  required
                  minLength={20}
                  maxLength={2000}
                  defaultValue={String(values.authorization_declaration || '')}
                  placeholder="Describe your ownership or permission to test this target."
                />
              </label>
            </>
          )}
          <div className="config-actions">
            {step > 0 && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => setStep(step - 1)}
              >
                Back
              </Button>
            )}
            <Button type="submit">Continue</Button>
          </div>
        </form>
      ) : (
        <section className="config-form">
          <h2>Review and authorize</h2>
          <dl>
            <dt>Target</dt>
            <dd>
              {String(values.display_name)} · {kind.replaceAll('_', ' ')}
            </dd>
            <dt>URL</dt>
            <dd className="break-url">{String(values.base_url)}</dd>
            <dt>Scope</dt>
            <dd>
              {String(values.inclusion_patterns)} ·{' '}
              {String(values.allowed_methods)}
            </dd>
            <dt>Policy</dt>
            <dd>
              {selectedPolicy?.name} · v{selectedPolicy?.version} ·{' '}
              {selectedPolicy?.mode}
            </dd>
            <dt>Limits</dt>
            <dd>
              {String(values.rate_limit)} requests/second ·{' '}
              {String(values.timeout_seconds)} seconds
            </dd>
            <dt>Authentication</dt>
            <dd>{authType === 'none' ? 'None' : `${authType} · ••••••••`}</dd>
            <dt>Authorization</dt>
            <dd>{String(values.authorization_declaration)}</dd>
          </dl>
          {selectedPolicy?.mode === 'active' && (
            <p className="workspace-notice">
              Active scanning may modify application data. This setup records
              target consent only. A separate one-use confirmation is required
              before any active scan.
            </p>
          )}
          <p>
            You are recorded as the authorization owner. The server timestamps
            consent. Registration rechecks the URL and OpenAPI document.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <label className="config-check">
              <input
                type="checkbox"
                required
                disabled={busy}
                checked={consented}
                onChange={(e) => setConsented(e.target.checked)}
              />
              I own this target or have explicit permission to test this exact
              scope and authorize credential-free reachability checks.
            </label>
            <div className="config-actions">
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  setStep(0);
                  setValidated(false);
                }}
              >
                Edit setup
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={busy || !memberId || !consented}
                onClick={() => void validate()}
              >
                Validate URL and OpenAPI
              </Button>
              <Button type="submit" disabled={busy || !validated || !consented}>
                {busy ? 'Checking…' : 'Authorize and register target'}
              </Button>
            </div>
          </form>
        </section>
      )}
    </>
  );
}
