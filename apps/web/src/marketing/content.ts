export const features = [
  {
    slug: 'web-scanning',
    title: 'Web scanning',
    headline: 'Follow the application. Keep the evidence.',
    problem:
      'A URL is a starting point, not a complete picture of an application.',
    workflow: [
      'Validate target ownership and scope',
      'Discover routes with spidering',
      'Review passive observations before confirming active tests',
    ],
    detail:
      'ZAP observations retain their source and context so a reviewer can trace a finding back to evidence.',
    safety:
      'Every scan requires current authorization. Active tests additionally require explicit, one-use confirmation.',
  },
  {
    slug: 'api-scanning',
    title: 'API scanning',
    headline: 'Bring your API contract into the review.',
    problem:
      'Endpoints hidden behind application flows need an explicit discovery path.',
    workflow: [
      'Review an OpenAPI definition',
      'Bind imported endpoints to an authorized target',
      'Inspect coverage and evidence together',
    ],
    detail:
      'API import belongs inside the same target boundary as browser discovery. An imported URL does not grant permission to scan it.',
    safety:
      'Scope and egress checks apply at execution time. Credentials are secret references, never ordinary target metadata.',
  },
  {
    slug: 'ai-analysis',
    title: 'AI analysis',
    headline: 'Understand the finding. Keep the source.',
    problem:
      'Scanner output needs context before a developer can choose a useful next step.',
    workflow: [
      'Minimize and redact evidence',
      'Request structured Gemini guidance',
      'Validate references and review the advice',
    ],
    detail:
      'Guidance explains impact, remediation options and verification steps alongside the underlying observation.',
    safety:
      'AI is advisory. It cannot invent evidence, change scanner severity or decide a gate. Unavailable enrichment is visible.',
  },
  {
    slug: 'ci-cd',
    title: 'CI/CD',
    headline: 'A release decision you can trace.',
    problem:
      'A green check is only useful when it means the same thing on every run.',
    workflow: [
      'Select a versioned policy',
      'Evaluate evidence and scan completeness',
      'Publish the gate with its decision trail',
    ],
    detail:
      'Deterministic policy separates pass, warn and fail from generated explanations. GitHub branch protection must require the check to block a merge.',
    safety:
      'Failed, cancelled, partial and timed-out scans never produce a passing gate.',
  },
  {
    slug: 'reports',
    title: 'Reports',
    headline: 'Carry the evidence into the conversation.',
    problem:
      'A summary without provenance leaves the next reviewer starting over.',
    workflow: [
      'Select a completed review context',
      'Include redacted evidence and policy versions',
      'Export a PDF or validated JSON trail',
    ],
    detail:
      'Reports keep scanner observations, advisory guidance and policy evaluations distinct so each conclusion has a source.',
    safety:
      'Reports support review, not compliance certification. Restricted artifacts require separate authorized access.',
  },
];
export const steps = [
  {
    title: 'Discover',
    headline: 'Start with a boundary.',
    text: 'Validate the target, establish authorization, then discover routes through spidering or API import.',
    rows: [
      'Target scope · review required',
      'Ownership · current authorization',
      'Discovery · spider / OpenAPI',
    ],
  },
  {
    title: 'Scan',
    headline: 'Observe before you conclude.',
    text: 'Run passive checks and explicitly authorized active ZAP tests. Preserve source evidence and make incomplete coverage visible.',
    rows: [
      'Engine · ZAP',
      'Active tests · confirmation required',
      'Evidence · source-linked observations',
    ],
  },
  {
    title: 'Explain',
    headline: 'Give evidence a next step.',
    text: 'Review evidence-linked Gemini guidance for impact, remediation and verification. The observation stays authoritative.',
    rows: [
      'Input · minimized and redacted',
      'Guidance · advisory only',
      'References · schema validated',
    ],
  },
  {
    title: 'Enforce and report',
    headline: 'Make the decision reviewable.',
    text: 'Apply a deterministic versioned policy, then carry the evidence and decision trail into PDF and JSON reports.',
    rows: [
      'Gate · deterministic policy',
      'Incomplete scan · never pass',
      'Exports · PDF / JSON',
    ],
  },
];
export const docs = [
  {
    slug: 'getting-started',
    title: 'Create a workspace',
    text: 'Create an account at /auth/sign-up, then sign in to your organization workspace. For local development, start the services and apply migrations first.',
    code: 'python3 scripts/setup_env.py\nmake dev\nmake migrate',
    note: 'Run these commands from the repository after installing the toolchain listed in README. Docker Engine must be running. The current executable backend exposes health checks only; it does not run scans.',
  },
  {
    slug: 'architecture',
    title: 'Architecture',
    text: 'The public React site is separate from the authenticated application. The planned FastAPI control plane queues isolated worker jobs; ZAP observations feed separate evidence, guidance and policy records.',
    code: 'Authorized target → isolated ZAP worker\nZAP → restricted artifacts → redacted observations\nRedacted evidence → advisory Gemini analysis\nEvidence + completeness + policy version → gate',
    note: 'Organization and project authorization are enforced by the API. The scanner runner and policy engine remain planned capabilities.',
  },
  {
    slug: 'authorization',
    title: 'Scanning authorization',
    text: 'Scan only systems you own or have explicit permission to test. Record who granted authorization, its evidence, target scope and expiry. Revalidate before every scan, including passive scans.',
    code: 'Target + configuration + policy version\n              ↓\nOne-use active confirmation\n              ↓\nExecution-time scope and egress checks',
    note: 'A URL, imported API definition or previous scan is not authorization. Stop when permission expires or scope changes.',
  },
  {
    slug: 'policies',
    title: 'Policies and evidence',
    text: 'Versioned deterministic rules evaluate scanner severity, completeness and approved risk dispositions. Generated text never supplies a gate decision.',
    code: 'failed / cancelled / partial / timed out → never pass\nAI unavailable → visible degraded enrichment\nraw artifact ≠ finding ≠ AI analysis ≠ policy evaluation',
    note: 'Preserve evidence provenance. Ordinary views, prompts and reports use redacted derivatives; restricted originals require encrypted storage and authorized access.',
  },
  {
    slug: 'integrations',
    title: 'Integration guide',
    text: 'The integration roadmap connects release checks, notifications, storage and analysis. No integration is connected by this marketing site.',
    code: 'GitHub Actions → required policy check\nSlack / email / webhooks → sanitized notifications\nS3 → private artifact storage\nGemini → advisory enrichment\nZAP → authoritative observations',
    note: 'Use least-privilege credentials and verified destinations. GitHub branch protection must require the check. Never include secrets or sensitive response bodies in notifications.',
  },
];
