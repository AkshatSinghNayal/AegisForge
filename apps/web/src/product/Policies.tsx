import { usePagedOptions } from './usePagedOptions';
import { MoreOptions } from './PagedOptions';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { z } from 'zod';
import { Button } from '@/ui';
import { messageSchema, request } from './client';

const matchSchema = z.object({
  severities: z.array(z.string()),
  minimum_confidence: z.string(),
  statuses: z.array(z.string()),
  cwes: z.array(z.number()),
  owasp: z.array(z.string()),
  route: z.string(),
  route_operator: z.enum(['exact', 'prefix']),
  environments: z.array(z.string()),
  baseline: z.enum(['any', 'new', 'existing']),
});
const ruleSchema = z.object({
  id: z.string(),
  match: matchSchema,
  max_open: z.number(),
  outcome: z.enum(['warn', 'fail']),
});
const policySchema = z.object({
  schema_version: z.literal('gate-v1'),
  incomplete_outcome: z.enum(['incomplete', 'fail']),
  allow_exceptions: z.boolean(),
  rules: z.array(ruleSchema),
  exceptions: z.array(
    z.object({
      finding_id: z.string(),
      owner_id: z.string(),
      reason: z.string(),
      expires_at: z.string(),
      created_at: z.string(),
      approved_by: z.string(),
    }),
  ),
});
const versionSchema = z.object({
  id: z.string(),
  version: z.number(),
  snapshot: policySchema,
});
const listSchema = z.object({
  active_id: z.string().nullable(),
  versions: z.array(versionSchema),
});
const resultSchema = z.object({
  outcome: z.enum(['pass', 'warn', 'fail', 'incomplete']),
  matches: z.array(
    z.object({
      rule_id: z.string(),
      outcome: z.string(),
      reason: z.string(),
      finding_ids: z.array(z.string()),
      occurrence_ids: z.array(z.string()),
    }),
  ),
  excluded_finding_ids: z.array(z.string()),
});
const evaluationSchema = z.object({
  id: z.string(),
  input_digest: z.string(),
  evaluation_version: z.string(),
  input_snapshot: z.record(z.string(), z.unknown()),
  result_snapshot: resultSchema,
});
type Rule = z.infer<typeof ruleSchema>;
const newRule = (n: number): Rule => ({
  id: `rule-${n}`,
  match: {
    severities: ['high', 'critical'],
    minimum_confidence: 'medium',
    statuses: ['new', 'recurring', 'reopened', 'changed', 'accepted_risk'],
    cwes: [],
    owasp: [],
    route: '',
    route_operator: 'exact',
    environments: [],
    baseline: 'new',
  },
  max_open: 0,
  outcome: 'fail',
});
const split = (text: string) =>
  text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

const projectOptionsSchema = z.array(
  z.object({ id: z.string(), name: z.string() }),
);

export default function Policies({ org, role }: { org: string; role: string }) {
  const projectOptions = usePagedOptions(
    `/organizations/${org}/projects`,
    projectOptionsSchema,
  );
  const projects = projectOptions.data;
  const [project, setProject] = useState('');
  useEffect(() => {
    if (!projects) return;
    const requested = new URLSearchParams(window.location.search).get(
      'project',
    );
    void Promise.resolve().then(() =>
      setProject((current) => current || requested || projects[0]?.id || ''),
    );
  }, [projects]);
  return (
    <div className="policy-page">
      <p className="eyebrow">WORKSPACE / DETERMINISTIC GATES</p>
      <h1>Project gate policies</h1>
      <p>
        Versioned rules evaluate scanner evidence and reviewer states. AI
        guidance has no influence on outcomes.
      </p>
      <MoreOptions label="projects" options={projectOptions} />
      <label>
        Project
        <select value={project} onChange={(e) => setProject(e.target.value)}>
          {project && !projects?.some((p) => p.id === project) && (
            <option value={project}>
              Selected project ({project.slice(0, 8)})
            </option>
          )}
          {(projects ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      {project ? (
        <ProjectPolicies
          key={`${org}-${project}`}
          org={org}
          project={project}
          admin={['owner', 'admin'].includes(role)}
        />
      ) : (
        <p>Create a project to configure its gate.</p>
      )}
    </div>
  );
}
function Result({ result }: { result: z.infer<typeof resultSchema> }) {
  return (
    <section aria-label="Evaluation result">
      <h3>Outcome: {result.outcome}</h3>
      {result.matches.length === 0 && <p>No thresholds exceeded.</p>}
      {result.matches.map((m) => (
        <article key={m.rule_id}>
          <h4>
            {m.rule_id} — {m.outcome}
          </h4>
          <p>{m.reason}</p>
          <ul>
            {m.finding_ids.map((id) => (
              <li key={id}>
                <Link to={`/app/findings/${id}`}>Finding {id}</Link>
              </li>
            ))}
          </ul>
          <details>
            <summary>Contributing occurrence IDs</summary>
            <ul>
              {m.occurrence_ids.map((id) => (
                <li key={id}>{id}</li>
              ))}
            </ul>
          </details>
        </article>
      ))}
      {result.excluded_finding_ids.length > 0 && (
        <p>
          Approved accepted-risk exclusions:{' '}
          {result.excluded_finding_ids.join(', ')}
        </p>
      )}
    </section>
  );
}
function ProjectPolicies({
  org,
  project,
  admin,
}: {
  org: string;
  project: string;
  admin: boolean;
}) {
  const path = `/organizations/${org}/projects/${project}/gate-policies`;
  const [data, setData] = useState<z.infer<typeof listSchema>>();
  const [selected, setSelected] = useState('');
  const [rules, setRules] = useState<Rule[]>([newRule(1)]);
  const [incomplete, setIncomplete] = useState<'incomplete' | 'fail'>(
    'incomplete',
  );
  const [allow, setAllow] = useState(false);
  const [exceptions, setExceptions] = useState<
    {
      finding_id: string;
      owner_id: string;
      reason: string;
      expires_at: string;
    }[]
  >([]);
  const [scan, setScan] = useState(
    new URLSearchParams(window.location.search).get('scan') ?? '',
  );
  const [history, setHistory] = useState<z.infer<typeof evaluationSchema>[]>(
    [],
  );
  const [result, setResult] = useState<z.infer<typeof resultSchema>>();
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const reload = async () => {
    const d = await request(path, listSchema);
    setData(d);
    setSelected(d.active_id ?? d.versions[0]?.id ?? '');
  };
  useEffect(() => {
    let live = true;
    void request(path, listSchema)
      .then((d) => {
        if (live) {
          setData(d);
          setSelected(d.active_id ?? d.versions[0]?.id ?? '');
        }
      })
      .catch((e: unknown) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, [path]);
  async function run(work: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed.');
    } finally {
      setBusy(false);
    }
  }
  function change(i: number, rule: Rule) {
    setRules((rows) => rows.map((r, j) => (j === i ? rule : r)));
  }
  const selectedVersion = data?.versions.find((v) => v.id === selected);
  const scanPath = `/scans/${scan}?organization_id=${org}`;
  return (
    <>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <h2>Published versions</h2>
      <p>
        Active:{' '}
        {data?.versions.find((v) => v.id === data.active_id)?.version ??
          'None — scans remain incomplete'}
      </p>
      <label>
        Policy version
        <select
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setResult(undefined);
          }}
        >
          <option value="">Select a version</option>
          {data?.versions.map((v) => (
            <option key={v.id} value={v.id}>
              Version {v.version}
            </option>
          ))}
        </select>
      </label>
      {selectedVersion && (
        <details>
          <summary>Read policy version {selectedVersion.version}</summary>
          <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
            {JSON.stringify(selectedVersion.snapshot, null, 2)}
          </pre>
        </details>
      )}
      {admin && (
        <div className="form-actions">
          <Button
            disabled={busy || !selected}
            onClick={() =>
              void run(async () => {
                await request(`${path}/activation`, messageSchema, 'POST', {
                  policy_id: selected,
                });
                await reload();
                setNotice('Policy activated for future scans.');
              })
            }
          >
            Activate selected version
          </Button>
          <Button
            disabled={busy || !data?.active_id}
            onClick={() =>
              void run(async () => {
                await request(`${path}/activation`, messageSchema, 'POST', {
                  policy_id: null,
                });
                await reload();
                setNotice('Policy deactivated.');
              })
            }
          >
            Deactivate
          </Button>
        </div>
      )}
      {admin && (
        <form
          className="policy-builder"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              const version = await request(path, versionSchema, 'POST', {
                policy: {
                  schema_version: 'gate-v1',
                  incomplete_outcome: incomplete,
                  allow_exceptions: allow,
                  rules,
                  exceptions: [],
                },
                exceptions: exceptions.map((ex) => ({
                  ...ex,
                  expires_at: new Date(ex.expires_at).toISOString(),
                })),
              });
              await reload();
              setSelected(version.id);
              setNotice(
                `Published immutable version ${version.version}. Activate it when ready.`,
              );
            });
          }}
        >
          <h2>Publish a new version</h2>
          <p>
            Conditions within a rule are combined with AND. Comma-separated
            values match any listed value; empty lists match all. Counts are
            distinct findings. A prohibited category uses a maximum count of
            zero.
          </p>
          {selectedVersion && (
            <Button
              type="button"
              onClick={() => {
                setRules(selectedVersion.snapshot.rules);
                setIncomplete(selectedVersion.snapshot.incomplete_outcome);
                setAllow(selectedVersion.snapshot.allow_exceptions);
                setExceptions(
                  selectedVersion.snapshot.exceptions.map((ex) => ({
                    finding_id: ex.finding_id,
                    owner_id: ex.owner_id,
                    reason: ex.reason,
                    expires_at: new Date(
                      new Date(ex.expires_at).getTime() -
                        new Date(ex.expires_at).getTimezoneOffset() * 60000,
                    )
                      .toISOString()
                      .slice(0, 16),
                  })),
                );
              }}
            >
              Copy selected version into builder
            </Button>
          )}
          <label>
            Incomplete scan outcome
            <select
              value={incomplete}
              onChange={(e) =>
                setIncomplete(e.target.value as 'incomplete' | 'fail')
              }
            >
              <option value="incomplete">Incomplete</option>
              <option value="fail">Fail closed</option>
            </select>
          </label>
          {rules.map((r, i) => (
            <fieldset key={i}>
              <legend>Rule {i + 1}</legend>
              <label>
                Rule ID
                <input
                  required
                  pattern="[a-zA-Z0-9_-]{1,64}"
                  value={r.id}
                  onChange={(e) => change(i, { ...r, id: e.target.value })}
                />
              </label>
              {(['severities', 'statuses'] as const).map((field) => (
                <fieldset key={field}>
                  <legend>
                    Rule {i + 1} {field}
                  </legend>
                  {(field === 'severities'
                    ? ['informational', 'low', 'medium', 'high', 'critical']
                    : [
                        'new',
                        'recurring',
                        'reopened',
                        'changed',
                        'accepted_risk',
                        'false_positive',
                        'resolved',
                      ]
                  ).map((value) => (
                    <label key={value}>
                      <input
                        type="checkbox"
                        checked={r.match[field].includes(value)}
                        onChange={(e) =>
                          change(i, {
                            ...r,
                            match: {
                              ...r.match,
                              [field]: e.target.checked
                                ? [...r.match[field], value]
                                : r.match[field].filter((v) => v !== value),
                            },
                          })
                        }
                      />
                      {value}
                    </label>
                  ))}
                </fieldset>
              ))}
              {(['owasp', 'environments'] as const).map((field) => (
                <label key={field}>
                  {field}
                  <CommaValues
                    values={r.match[field]}
                    onChange={(values) =>
                      change(i, {
                        ...r,
                        match: { ...r.match, [field]: values },
                      })
                    }
                  />
                </label>
              ))}
              <label>
                CWE numbers
                <CommaValues
                  values={r.match.cwes.map(String)}
                  onChange={(values) =>
                    change(i, {
                      ...r,
                      match: { ...r.match, cwes: values.map(Number) },
                    })
                  }
                />
              </label>
              <label>
                Minimum scanner confidence
                <select
                  value={r.match.minimum_confidence}
                  onChange={(e) =>
                    change(i, {
                      ...r,
                      match: { ...r.match, minimum_confidence: e.target.value },
                    })
                  }
                >
                  {['false_positive', 'low', 'medium', 'high', 'confirmed'].map(
                    (c) => (
                      <option key={c}>{c}</option>
                    ),
                  )}
                </select>
              </label>
              <label>
                Route
                <input
                  value={r.match.route}
                  onChange={(e) =>
                    change(i, {
                      ...r,
                      match: { ...r.match, route: e.target.value },
                    })
                  }
                />
              </label>
              <label>
                Route operator
                <select
                  value={r.match.route_operator}
                  onChange={(e) =>
                    change(i, {
                      ...r,
                      match: {
                        ...r.match,
                        route_operator: e.target.value as 'exact' | 'prefix',
                      },
                    })
                  }
                >
                  <option value="exact">Exact</option>
                  <option value="prefix">Prefix</option>
                </select>
              </label>
              <label>
                Baseline comparison
                <select
                  value={r.match.baseline}
                  onChange={(e) =>
                    change(i, {
                      ...r,
                      match: {
                        ...r.match,
                        baseline: e.target.value as 'any' | 'new' | 'existing',
                      },
                    })
                  }
                >
                  {['any', 'new', 'existing'].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                Maximum matching findings
                <input
                  type="number"
                  min="0"
                  max="100000"
                  required
                  value={r.max_open}
                  onChange={(e) =>
                    change(i, { ...r, max_open: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                Outcome
                <select
                  value={r.outcome}
                  onChange={(e) =>
                    change(i, {
                      ...r,
                      outcome: e.target.value as 'warn' | 'fail',
                    })
                  }
                >
                  <option value="fail">Fail</option>
                  <option value="warn">Warn</option>
                </select>
              </label>
              <Button
                type="button"
                onClick={() => setRules(rules.filter((_, j) => j !== i))}
              >
                Remove rule {i + 1}
              </Button>
            </fieldset>
          ))}
          <Button
            type="button"
            disabled={rules.length >= 100}
            onClick={() => setRules([...rules, newRule(rules.length + 1)])}
          >
            Add rule
          </Button>
          <label>
            <input
              type="checkbox"
              checked={allow}
              onChange={(e) => setAllow(e.target.checked)}
            />
            Allow approved accepted-risk exceptions
          </label>
          <p>
            Publishing records your approval. Each exception applies only to the
            specified finding while its reviewer state is accepted risk. Expired
            exceptions never suppress findings.
          </p>
          {exceptions.map((ex, i) => (
            <fieldset key={i}>
              <legend>Exception {i + 1}</legend>
              {(
                ['finding_id', 'owner_id', 'reason', 'expires_at'] as const
              ).map((field) => (
                <label key={field}>
                  {field}
                  <input
                    required
                    type={field === 'expires_at' ? 'datetime-local' : 'text'}
                    value={ex[field]}
                    onChange={(e) =>
                      setExceptions(
                        exceptions.map((v, j) =>
                          j === i ? { ...v, [field]: e.target.value } : v,
                        ),
                      )
                    }
                  />
                </label>
              ))}
              <Button
                type="button"
                onClick={() =>
                  setExceptions(exceptions.filter((_, j) => j !== i))
                }
              >
                Remove exception {i + 1}
              </Button>
            </fieldset>
          ))}
          <Button
            type="button"
            disabled={exceptions.length >= 100}
            onClick={() =>
              setExceptions([
                ...exceptions,
                { finding_id: '', owner_id: '', reason: '', expires_at: '' },
              ])
            }
          >
            Add exception
          </Button>
          <Button disabled={busy} type="submit">
            Publish version
          </Button>
        </form>
      )}
      <section>
        <h2>Historical scan preview and evaluations</h2>
        <label>
          Scan ID
          <input
            disabled={busy}
            value={scan}
            onChange={(e) => {
              setScan(e.target.value);
              setResult(undefined);
              setHistory([]);
            }}
          />
        </label>
        <Button
          disabled={busy || !selected || !scan}
          onClick={() =>
            void run(async () => {
              setResult(
                await request(
                  `/scans/${scan}/policy-preview?organization_id=${org}`,
                  resultSchema,
                  'POST',
                  { policy_id: selected },
                ),
              );
            })
          }
        >
          Preview selected policy
        </Button>
        <Button
          disabled={busy || !scan}
          onClick={() =>
            void run(async () => {
              setHistory(
                await request(
                  scanPath.replace('?', '/policy-evaluations?'),
                  z.array(evaluationSchema),
                ),
              );
            })
          }
        >
          Load evaluation history
        </Button>
        {admin && (
          <Button
            disabled={busy || !selected || !scan}
            onClick={() =>
              void run(async () => {
                const saved = await request(
                  `/scans/${scan}/policy-evaluations?organization_id=${org}`,
                  evaluationSchema,
                  'POST',
                  { policy_id: selected },
                );
                setHistory([saved, ...history]);
                setResult(saved.result_snapshot);
                setNotice(
                  'New evaluation retained. Earlier evaluations are unchanged.',
                );
              })
            }
          >
            Save re-evaluation
          </Button>
        )}
        {result && <Result result={result} />}
        <ol>
          {history.map((ev) => (
            <li key={ev.id}>
              <h3>Evaluation {ev.id}</h3>
              <p>Engine: {ev.evaluation_version}</p>
              <Result result={ev.result_snapshot} />
              <details>
                <summary>Immutable input snapshot and digest</summary>
                <p style={{ overflowWrap: 'anywhere' }}>{ev.input_digest}</p>
                <pre
                  style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
                >
                  {JSON.stringify(ev.input_snapshot, null, 2)}
                </pre>
              </details>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function CommaValues({
  values,
  onChange,
}: {
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const [draft, setDraft] = useState(values.join(', '));
  const [previous, setPrevious] = useState(values);
  if (previous !== values && values.join(',') !== split(draft).join(',')) {
    setPrevious(values);
    setDraft(values.join(', '));
  }
  return (
    <input
      value={draft}
      onChange={(e) => {
        setDraft(e.target.value);
        onChange(split(e.target.value));
      }}
    />
  );
}
