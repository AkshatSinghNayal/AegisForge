import { useEffect, useState, type FormEvent } from 'react';
import { z } from 'zod';
import { Button } from '@/ui';
import { request } from './client';

const text = z.string().max(1800);
const guidance = z.object({
  summary: text,
  vulnerability_explanation: text,
  root_cause_hypothesis: text,
  technical_impact: text,
  business_impact: text,
  remediation_steps: z.array(text).max(12),
  verification_steps: z.array(text).max(12),
  evidence_ids: z.array(z.string()).max(3),
  cwe_interpretation: text,
  owasp_mapping_interpretation: text,
  model_confidence: z.number().min(0).max(1),
  uncertainty_notes: z.array(text).max(12),
});
const analysis = z.object({
  id: z.string(),
  occurrence_id: z.string(),
  provider: z.string(),
  model: z.string(),
  schema_version: z.string(),
  prompt_version: z.string(),
  status: z.string(),
  generated_at: z.string().nullable(),
  output: guidance.nullable(),
  feedback: z
    .array(z.object({ id: z.string(), useful: z.boolean(), note: z.string() }))
    .optional(),
});

export default function AIGuidance({
  org,
  finding,
  role,
  cite,
}: {
  org: string;
  finding: string;
  role: string;
  cite: (id: string) => void;
}) {
  const [rows, setRows] = useState<z.infer<typeof analysis>[]>([]);
  const [revision, setRevision] = useState(0);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const endpoint = `/findings/${finding}/analyses`;
  useEffect(() => {
    let active = true;
    void request(
      `${endpoint}?organization_id=${org}&offset=${offset}`,
      z.array(analysis),
    )
      .then((value) => {
        if (active) {
          setRows(value);
          setLoaded(true);
          setError('');
        }
      })
      .catch((e: unknown) => {
        if (active)
          setError(e instanceof Error ? e.message : 'Guidance unavailable.');
      });
    return () => {
      active = false;
    };
  }, [endpoint, org, revision, offset]);
  async function generate() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await request(
        `${endpoint}?organization_id=${org}`,
        analysis,
        'POST',
      );
      setOffset(0);
      setRevision((v) => v + 1);
      setNotice(
        result.status === 'degraded'
          ? 'Enrichment failed. Scanner findings and prior guidance are preserved.'
          : 'A new advisory version was retained.',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Generation failed.');
    } finally {
      setBusy(false);
    }
  }
  async function feedback(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setNotice('');
    setBusy(true);
    setError('');
    try {
      await request(
        `${endpoint}/${id}/feedback?organization_id=${org}`,
        z.object({ id: z.string() }),
        'POST',
        {
          useful: data.get('useful') === 'yes',
          note: data.get('note'),
        },
      );
      setNotice(
        'Feedback saved for review. It is not used for automatic training.',
      );
      setRevision((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Feedback failed.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="ai-guidance">
      <h2>AI Guidance</h2>
      <p>
        Generated analysis · advisory only. Scanner evidence remains
        authoritative; guidance cannot change severity or CI/CD outcomes.
      </p>
      <p>
        Root causes are hypotheses requiring review. Only scanner
        classifications are shared; HTTP content is withheld.
      </p>
      {role !== 'viewer' && (
        <Button disabled={busy} onClick={() => void generate()}>
          {busy
            ? 'Working…'
            : rows.length
              ? 'Regenerate guidance'
              : 'Generate guidance'}
        </Button>
      )}
      {error && (
        <p role="alert">
          {error}{' '}
          <Button onClick={() => setRevision((v) => v + 1)}>
            Reload guidance
          </Button>
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {!loaded && !error && <p role="status">Loading guidance…</p>}
      {loaded && !rows.length && (
        <p>No AI analysis has been generated for this finding.</p>
      )}
      {rows.map((row, index) => (
        <details key={row.id} open={index === 0} className="ai-version">
          <summary>
            {row.status === 'mock'
              ? 'DEMO · Mock generated guidance'
              : 'Generated analysis'}{' '}
            · {row.status} ·{' '}
            {row.generated_at
              ? new Date(row.generated_at).toLocaleString()
              : 'Unknown date'}
          </summary>
          <p>
            {row.provider} / {row.model} · Prompt {row.prompt_version} · Schema{' '}
            {row.schema_version}
          </p>
          <small>Version ID: {row.id}</small>
          {row.output ? (
            <>
              <p>
                Model confidence:{' '}
                {Math.round(row.output.model_confidence * 100)}% (self-reported,
                not calibrated)
              </p>
              {(
                [
                  'summary',
                  'vulnerability_explanation',
                  'root_cause_hypothesis',
                  'technical_impact',
                  'business_impact',
                  'cwe_interpretation',
                  'owasp_mapping_interpretation',
                ] as const
              ).map((key) => (
                <section key={key}>
                  <h3>{key.replaceAll('_', ' ')}</h3>
                  <p>{row.output?.[key]}</p>
                </section>
              ))}
              <h3>Uncertainty</h3>
              <ul>
                {row.output.uncertainty_notes.map((value, i) => (
                  <li key={i}>{value}</li>
                ))}
              </ul>
              <h3>Scanner evidence citations</h3>
              <ul>
                {row.output.evidence_ids.map((id) => (
                  <li key={id}>
                    <Button variant="secondary" onClick={() => cite(id)}>
                      View occurrence {id}
                    </Button>
                  </li>
                ))}
              </ul>
              <h3>Remediation steps</h3>
              <ol>
                {row.output.remediation_steps.map((value, i) => (
                  <li key={i}>{value}</li>
                ))}
              </ol>
              <h3>Verification checklist</h3>
              <p>
                Local checklist only; checking an item does not verify a fix or
                change the finding.
              </p>
              {row.output.verification_steps.map((value, i) => (
                <label className="ai-check" key={i}>
                  <input type="checkbox" /> {value}
                </label>
              ))}
            </>
          ) : (
            <p>
              Enrichment is unavailable for this version. The scanner finding is
              preserved; no clean result is implied.
            </p>
          )}
          <h3>Reviewer feedback</h3>
          <p>
            Feedback stays in this workspace. No automatic training or provider
            submission.
          </p>
          {row.feedback?.map((f) => (
            <p key={f.id}>
              {f.useful ? 'Useful' : 'Not useful'}:{' '}
              {f.note || 'No reviewer note'}
            </p>
          ))}
          {role !== 'viewer' && (
            <form onSubmit={(e) => void feedback(e, row.id)}>
              <label>
                Usefulness{' '}
                <select name="useful">
                  <option value="yes">Useful</option>
                  <option value="no">Not useful</option>
                </select>
              </label>
              <label>
                Reviewer note <textarea name="note" maxLength={2000} />
              </label>
              <Button type="submit" disabled={busy}>
                Save feedback
              </Button>
            </form>
          )}
        </details>
      ))}
      <nav aria-label="Analysis versions">
        <Button
          disabled={!offset}
          onClick={() => setOffset((v) => Math.max(0, v - 20))}
        >
          Newer versions
        </Button>{' '}
        <Button
          disabled={rows.length < 20}
          onClick={() => setOffset((v) => v + 20)}
        >
          Older versions
        </Button>
      </nav>
    </div>
  );
}
