import { env } from '@/env';
import { useLocation, Link } from 'react-router-dom';
import { Metadata } from './Shared';
const content = {
  security: {
    title: 'Security by explicit boundaries.',
    intro:
      'Responsible scanning begins with permission and ends with evidence that can be reviewed.',
    sections: [
      [
        'Scan only with authorization',
        'Use only systems you own or have explicit, current permission to test. Passive scans also require authorization. Active tests require an additional one-use confirmation tied to target, configuration and policy versions.',
      ],
      [
        'Protect the evidence',
        'The architecture calls for encrypted restricted originals and redacted derivatives for routine UI, AI and reports. Never submit credentials, session cookies, tokens or sensitive response bodies to this public site.',
      ],
      [
        'Keep AI in its role',
        'Gemini guidance is advisory and requires schema validation and evidence references. Only deterministic policy decides a gate. Incomplete or failed scans must never look clean.',
      ],
      [
        'Implementation status',
        'This release is a public project website and health scaffold. Scanner isolation, account management, evidence storage and policy enforcement are future implementation work. No certification or operational security guarantee is claimed.',
      ],
    ],
  },
  privacy: {
    title: 'Privacy, with a clear scope.',
    intro:
      'This notice describes the public AegisForge project website, not a deployed scanning service.',
    sections: [
      [
        'Data you provide',
        'The public site has no account registration, scan submission or payment form. Documentation search runs locally in your browser and is not sent to an API.',
      ],
      [
        'Browser and hosting data',
        'The site does not add marketing analytics or tracking cookies. A hosting provider may process ordinary request metadata such as IP address and user agent under its own policies. Deployment-specific details must be reviewed before public operation.',
      ],
      [
        'Future scan data',
        'Planned services require explicit retention rules, access controls and redaction for scan artifacts. This website does not collect those artifacts. Do not send secrets through a disclosure email.',
      ],
      [
        'Questions and updates',
        'The configured disclosure contact on the Security page is the contact route when available. This project notice must be revisited when data processing changes.',
      ],
    ],
  },
  terms: {
    title: 'Use the project responsibly.',
    intro:
      'Project terms for this public research website. No paid service or hosted scanning agreement is offered here.',
    sections: [
      [
        'Permitted use',
        'Read the documentation and explore the illustrative interfaces. Any future scanning must be limited to systems you own or are explicitly authorized to test.',
      ],
      [
        'Project availability',
        'The project is under development. Product mockups and architecture descriptions do not represent available hosted services, guaranteed coverage or performance commitments.',
      ],
      [
        'Review is required',
        'Security guidance is informational. Generated advice requires human review and verification. Reports do not establish regulatory compliance or certification.',
      ],
      [
        'Before operating a service',
        'Deployment-specific legal terms, privacy details and contact information require review before offering accounts, collecting scan data or charging for access.',
      ],
    ],
  },
};
export default function Legal() {
  const { pathname: routePath } = useLocation();
  const pathname = routePath.replace(/\/+$/, '');
  const key = pathname.slice(1) as keyof typeof content;
  const page = content[key];
  const raw = env.VITE_SECURITY_CONTACT;
  const contact =
    raw && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw) ? raw : undefined;
  return (
    <main id="main" className="m-container legal-page">
      <Metadata
        title={key[0]!.toUpperCase() + key.slice(1)}
        description={page.intro}
      />
      <p className="eyebrow">AEGISFORGE / {key} · UPDATED SEPTEMBER 2026</p>
      <h1>{page.title}</h1>
      <p className="m-lead">{page.intro}</p>
      {page.sections.map(([title, text]) => (
        <section key={title}>
          <h2>{title}</h2>
          <p>{text}</p>
        </section>
      ))}
      {key === 'security' && (
        <section>
          <h2>Responsible disclosure</h2>
          {contact ? (
            <p>
              Send a minimal reproduction without secrets to{' '}
              <a href={`mailto:${contact}`}>{contact}</a>. Avoid accessing other
              people’s data or running disruptive tests.
            </p>
          ) : (
            <p>
              Disclosure contact is not configured for this project release. The
              operator must set VITE_SECURITY_CONTACT before public operation.
              Do not send sensitive reports until a verified contact is
              published.
            </p>
          )}
        </section>
      )}
      <Link className="button secondary" to="/docs/authorization">
        Read the authorization guide →
      </Link>
    </main>
  );
}
