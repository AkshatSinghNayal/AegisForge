import { useEffect, useState, type FormEvent } from 'react';
import { Link, NavLink, useNavigate, useLocation } from 'react-router-dom';
import { z } from 'zod';
import { Button, Drawer, Input, Wordmark } from '@/ui';
import {
  ApiError,
  bootstrap,
  logout,
  meSchema,
  request,
  type Me,
} from './client';
import './product.css';
import Configuration from './Configuration';
import Scans from './Scans';
import Findings from './Findings';
import Policies from './Policies';
const progressSchema = z.object({
  create_project: z.boolean(),
  register_target: z.boolean(),
  run_safe_baseline: z.boolean(),
  configure_ci: z.boolean(),
});
const memberSchema = z.array(
  z.object({
    id: z.string(),
    email: z.string(),
    display_name: z.string(),
    role: z.string(),
    status: z.string(),
  }),
);
type Progress = z.infer<typeof progressSchema>;
const checklist = [
  {
    key: 'create_project',
    title: 'Create project',
    text: 'Group your application and its security evidence in a project.',
    to: '/app/projects',
  },
  {
    key: 'register_target',
    title: 'Register target',
    text: 'Record target scope and current ownership authorization before testing.',
    to: '/app/targets',
  },
  {
    key: 'run_safe_baseline',
    title: 'Run safe baseline scan',
    text: 'A completed baseline scan with complete evidence satisfies this step. Failed or partial scans do not.',
    to: '/docs/authorization',
  },
  {
    key: 'configure_ci',
    title: 'Configure CI/CD',
    text: 'Connect an active organization integration when CI/CD configuration becomes available.',
    to: '/docs/integrations',
  },
] as const;
export default function Workspace() {
  const navigate = useNavigate();
  const location = useLocation();
  const [me, setMe] = useState<Me | null>(null);
  const [organizationId, setOrganizationId] = useState('');
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    let active = true;
    void bootstrap()
      .then(async (ok) => {
        if (!ok) {
          navigate('/auth/sign-in', { replace: true });
          return;
        }
        const result = await request('/auth/me', meSchema);
        if (active) {
          setMe(result);
          setOrganizationId(result.organizations[0]?.id ?? '');
        }
      })
      .catch((e: unknown) => {
        if (active)
          setError(
            e instanceof Error ? e.message : 'Unable to load workspace.',
          );
      });
    return () => {
      active = false;
    };
  }, [navigate]);
  async function signOut(all = false) {
    try {
      await logout(all);
      navigate('/auth/sign-in', { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to sign out.');
    }
  }
  if (!me)
    return (
      <main className="lab-main">
        <h1>{error ? 'Workspace unavailable' : 'Opening your workspace…'}</h1>
        {error && (
          <>
            <p role="alert">{error}</p>
            <Button onClick={() => window.location.reload()}>Retry</Button>
          </>
        )}
      </main>
    );
  const org = me.organizations.find((o) => o.id === organizationId);
  const navigation = (
    <>
      <nav aria-label="Workspace">
        <NavLink to="/app/getting-started" onClick={() => setOpen(false)}>
          ◈ <span>Getting started</span>
        </NavLink>
        {['projects', 'targets', 'policies', 'gates', 'scans', 'findings'].map(
          (path) => (
            <NavLink
              key={path}
              to={`/app/${path}`}
              onClick={() => setOpen(false)}
            >
              {path[0]?.toUpperCase()}
              {path.slice(1)}
            </NavLink>
          ),
        )}
        <a
          href="/app/getting-started#organization"
          onClick={() => setOpen(false)}
        >
          ◎ <span>Organization</span>
        </a>
      </nav>
      <div className="workspace-support">
        <Link to="/docs">Documentation ↗</Link>
        <Link to="/security">Support & security ↗</Link>
        <Button variant="ghost" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    </>
  );
  return (
    <div className={`workspace ${collapsed ? 'is-collapsed' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="workspace-sidebar" aria-label="Workspace sidebar">
        <Link to="/" aria-label="AegisForge home">
          <Wordmark />
        </Link>
        <Button
          variant="ghost"
          aria-expanded={!collapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? '→' : '← Collapse'}
        </Button>
        {navigation}
      </aside>
      <div className="workspace-body">
        <header className="workspace-header">
          <Button
            className="workspace-menu"
            variant="secondary"
            aria-label="Open sidebar"
            onClick={() => setOpen(true)}
          >
            ☰
          </Button>
          <label>
            Organization
            <select
              aria-label="Organization"
              value={organizationId}
              onChange={(e) => setOrganizationId(e.target.value)}
            >
              {me.organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          <span className="badge">{org?.role ?? 'No membership'}</span>
          <span>{me.display_name}</span>
        </header>
        <main id="main" className="workspace-main">
          {org && location.pathname.startsWith('/app/gates') ? (
            <Policies key={org.id} org={org.id} role={org.role} />
          ) : org && location.pathname.startsWith('/app/findings') ? (
            <Findings key={org.id} org={org.id} role={org.role} />
          ) : org && location.pathname.startsWith('/app/scans') ? (
            <Scans key={org.id} org={org.id} role={org.role} />
          ) : org &&
            /^\/app\/(projects|targets|policies)/.test(location.pathname) ? (
            <Configuration
              key={org.id}
              org={org.id}
              role={org.role}
              userId={me.id}
            />
          ) : (
            <>
              <p className="eyebrow">WORKSPACE / GETTING STARTED</p>
              <h1>A clear path to your first scan.</h1>
              <p className="muted">
                Set the scope. Gather evidence. Make informed decisions.
              </p>
              {error && <p role="alert">{error}</p>}
              {!me.email_verified && (
                <p className="workspace-notice">
                  Email verification is pending. Open the verification link sent
                  to your email.
                </p>
              )}
              {org ? (
                <Onboarding key={org.id} organizationId={org.id} />
              ) : (
                <p>Create an organization below to begin.</p>
              )}
              <OrganizationSettings
                key={`settings-${organizationId}`}
                me={me}
                organizationId={organizationId}
                onRefresh={async () => {
                  const result = await request('/auth/me', meSchema);
                  setMe(result);
                  if (
                    !result.organizations.some((o) => o.id === organizationId)
                  )
                    setOrganizationId(result.organizations[0]?.id ?? '');
                }}
              />
              <section className="workspace-security">
                <h2>Session security</h2>
                <p>Sign out on every device, including this one.</p>
                <Button variant="secondary" onClick={() => void signOut(true)}>
                  Revoke all sessions
                </Button>
              </section>
            </>
          )}
        </main>
      </div>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Workspace navigation"
      >
        {navigation}
      </Drawer>
    </div>
  );
}
function Onboarding({ organizationId }: { organizationId: string }) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState('');
  async function load() {
    try {
      setProgress(
        await request(
          `/organizations/${organizationId}/onboarding`,
          progressSchema,
        ),
      );
      setError('');
    } catch (e) {
      setProgress(null);
      setError(e instanceof Error ? e.message : 'Progress unavailable.');
    }
  }
  useEffect(() => {
    let active = true;
    void request(`/organizations/${organizationId}/onboarding`, progressSchema)
      .then((p) => {
        if (active) setProgress(p);
      })
      .catch((e: unknown) => {
        if (active)
          setError(e instanceof Error ? e.message : 'Progress unavailable.');
      });
    return () => {
      active = false;
    };
  }, [organizationId]);
  const count = progress
    ? Object.values(progress).filter(Boolean).length
    : null;
  return (
    <div className="onboarding-grid">
      <section className="onboarding-cards" aria-label="Getting started stages">
        {[
          {
            title: 'Configure',
            number: '01',
            text: 'Define your application boundary and make authorization explicit.',
            to: '/docs/authorization',
            link: 'Read configuration guide',
          },
          {
            title: 'Scan',
            number: '02',
            text: 'Start with a safe baseline. Keep evidence connected to its source.',
            to: '/docs/architecture',
            link: 'Explore the scan lifecycle',
          },
          {
            title: 'Review',
            number: '03',
            text: 'Understand findings and deterministic gates before acting.',
            to: '/docs/policies',
            link: 'Understand policy results',
          },
        ].map((card) => (
          <article key={card.title}>
            <span className="stage-number">{card.number} /</span>
            <h2>{card.title}</h2>
            <p>{card.text}</p>
            <Link to={card.to}>{card.link} ↗</Link>
          </article>
        ))}
        <p className="workspace-notice">
          Project and target creation, scan execution, and CI/CD configuration
          arrive in later phases. These guides explain the prerequisites;
          progress reflects saved backend records only.
        </p>
      </section>
      <aside className="onboarding-checklist" aria-label="Onboarding checklist">
        <p className="eyebrow">YOUR FIRST MILESTONE</p>
        <h2>Workspace checklist</h2>
        <p aria-live="polite">
          {count === null ? 'Progress unavailable' : `${count} of 4 complete`}
        </p>
        {count !== null && (
          <progress max={4} value={count} aria-label="Onboarding completion" />
        )}
        {error && <p role="alert">{error}</p>}
        {checklist.map((item) => (
          <details key={item.key}>
            <summary>
              <span>{progress?.[item.key] ? '✓' : '○'}</span>
              {item.title}
            </summary>
            <p>{item.text}</p>
            <Link to={item.to}>Read guide ↗</Link>
          </details>
        ))}
        <Button variant="ghost" onClick={() => void load()}>
          Refresh progress
        </Button>
      </aside>
    </div>
  );
}
function OrganizationSettings({
  me,
  organizationId,
  onRefresh,
}: {
  me: Me;
  organizationId: string;
  onRefresh: () => Promise<void>;
}) {
  const org = me.organizations.find((o) => o.id === organizationId);
  const [members, setMembers] = useState<z.infer<typeof memberSchema>>([]);
  const [feedback, setFeedback] = useState('');
  const [busy, setBusy] = useState(false);
  const canManage = org?.role === 'owner' || org?.role === 'admin';
  async function refreshMembers() {
    if (canManage)
      setMembers(
        await request(`/organizations/${organizationId}/members`, memberSchema),
      );
  }
  useEffect(() => {
    let active = true;
    if (canManage)
      void request(`/organizations/${organizationId}/members`, memberSchema)
        .then((data) => {
          if (active) setMembers(data);
        })
        .catch((e: unknown) => {
          if (active)
            setFeedback(
              e instanceof Error ? e.message : 'Members unavailable.',
            );
        });
    return () => {
      active = false;
    };
  }, [organizationId, canManage]);
  async function action(path: string, method: string, body?: unknown) {
    setBusy(true);
    setFeedback('');
    try {
      await request(path, z.unknown(), method, body);
      await onRefresh();
      await refreshMembers();
      setFeedback('Changes saved.');
    } catch (e) {
      setFeedback(
        e instanceof ApiError || e instanceof Error
          ? e.message
          : 'Unable to save.',
      );
    } finally {
      setBusy(false);
    }
  }
  function submit(
    event: FormEvent<HTMLFormElement>,
    path: string,
    method: string,
  ) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    void action(path, method, data);
  }
  return (
    <section id="organization" className="organization-settings">
      <h2>Organization</h2>
      <p>
        {org ? `${org.name} · ${org.role}` : 'You have no active organization.'}
      </p>
      {feedback && <p role="status">{feedback}</p>}
      <details>
        <summary>Create an organization</summary>
        <form onSubmit={(e) => submit(e, '/organizations', 'POST')}>
          <Input
            name="name"
            label="New organization name"
            required
            maxLength={120}
          />
          <Button type="submit" disabled={busy}>
            Create organization
          </Button>
        </form>
      </details>
      {org?.role === 'owner' && (
        <details>
          <summary>Organization settings</summary>
          <form
            onSubmit={(e) =>
              submit(e, `/organizations/${organizationId}`, 'PATCH')
            }
          >
            <Input
              name="name"
              label="Organization name"
              defaultValue={org.name}
              required
              maxLength={120}
            />
            <Button type="submit" disabled={busy}>
              Save name
            </Button>
          </form>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              if (
                window.confirm(
                  'Deactivate this organization? All members will lose access. Evidence and history are retained.',
                )
              )
                void action(`/organizations/${organizationId}`, 'DELETE');
            }}
          >
            Deactivate organization
          </Button>
        </details>
      )}
      {canManage && (
        <details>
          <summary>Manage team</summary>
          <form
            onSubmit={(e) =>
              submit(e, `/organizations/${organizationId}/invitations`, 'POST')
            }
          >
            <Input label="Invite email" type="email" name="email" required />
            <label>
              Invitation role
              <select name="role" defaultValue="developer">
                <option value="viewer">Viewer</option>
                <option value="developer">Developer</option>
                {org?.role === 'owner' && <option value="admin">Admin</option>}
              </select>
            </label>
            <Button type="submit" disabled={busy}>
              Send invitation
            </Button>
          </form>
          <ul className="member-list">
            {members.map((m) => (
              <li key={m.id}>
                <strong>{m.display_name}</strong>
                <span>
                  {m.email} · {m.role} · {m.status}
                </span>
                {m.role !== 'owner' &&
                  m.status === 'active' &&
                  (org?.role === 'owner' || m.role !== 'admin') && (
                    <>
                      <label>
                        Role for {m.display_name}
                        <select
                          aria-label={`Role for ${m.email}`}
                          value={m.role}
                          disabled={busy}
                          onChange={(e) =>
                            void action(
                              `/organizations/${organizationId}/members/${m.id}`,
                              'PATCH',
                              { role: e.target.value },
                            )
                          }
                        >
                          <option value="viewer">Viewer</option>
                          <option value="developer">Developer</option>
                          {org?.role === 'owner' && (
                            <option value="admin">Admin</option>
                          )}
                        </select>
                      </label>
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() =>
                          void action(
                            `/organizations/${organizationId}/members/${m.id}`,
                            'DELETE',
                          )
                        }
                      >
                        Deactivate {m.display_name}
                      </Button>
                      {org?.role === 'owner' && (
                        <Button
                          variant="secondary"
                          disabled={busy}
                          onClick={() => {
                            if (
                              window.confirm(
                                `Transfer ownership to ${m.display_name}? You will become an admin.`,
                              )
                            )
                              void action(
                                `/organizations/${organizationId}/transfer-ownership`,
                                'POST',
                                { member_id: m.id },
                              );
                          }}
                        >
                          Transfer ownership to {m.display_name}
                        </Button>
                      )}
                    </>
                  )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
