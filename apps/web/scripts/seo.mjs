import { envSchema } from '../src/env-schema.ts';
import { URL } from 'node:url';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { loadEnv } from 'vite';
const parsed = envSchema.safeParse(loadEnv('production', '../..', 'VITE_'));
if (!parsed.success) {
  throw new Error(
    `Invalid public configuration: ${parsed.error.issues.map((issue) => issue.path.join('.')).join(', ')}`,
  );
}
const origin = new URL(parsed.data.VITE_SITE_URL);
const routes = {
  '/': [
    'Scan. Understand. Enforce.',
    'Developer-first vulnerability intelligence with evidence preservation, advisory AI and deterministic policy.',
  ],
  '/platform': [
    'Platform',
    'Explore the AegisForge architecture and its distinct evidence, guidance and policy boundaries.',
  ],
  '/pricing': [
    'Project packaging',
    'Community and Team/Research example packaging. No purchasable plans or checkout.',
  ],
  '/docs': [
    'Documentation',
    'Setup and architecture guides for the AegisForge research project.',
  ],
  '/security': [
    'Security',
    'Responsible scanning, authorization, redaction and AI limitations.',
  ],
  '/privacy': [
    'Privacy',
    'How the public AegisForge project website handles information.',
  ],
  '/terms': [
    'Terms',
    'Responsible use and availability of the AegisForge research project.',
  ],
};
for (const [slug, title] of Object.entries({
  'web-scanning': 'Web scanning',
  'api-scanning': 'API scanning',
  'ai-analysis': 'AI analysis',
  'ci-cd': 'CI/CD',
  reports: 'Reports',
}))
  routes[`/features/${slug}`] = [
    title,
    `Explore the planned ${title.toLowerCase()} workflow, evidence context and safety boundaries in AegisForge.`,
  ];
for (const [slug, title] of Object.entries({
  'getting-started': 'Create a workspace',
  architecture: 'Architecture',
  authorization: 'Scanning authorization',
  policies: 'Policies and evidence',
  integrations: 'Integration guide',
}))
  routes[`/docs/${slug}`] = [
    title,
    `AegisForge documentation: ${title.toLowerCase()}, current release scope and implementation requirements.`,
  ];
const escape = (value) =>
  value
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
const template = await readFile('dist/index.html', 'utf8');
for (const [route, [title, description]] of Object.entries(routes)) {
  const url = new URL(route, origin).href;
  const metadata = `<title>${escape(title)} | AegisForge</title>\n<meta data-static-seo name="description" content="${escape(description)}"><link data-static-seo rel="canonical" href="${escape(url)}"><meta data-static-seo property="og:title" content="${escape(title)} | AegisForge"><meta data-static-seo property="og:description" content="${escape(description)}"><meta data-static-seo property="og:url" content="${escape(url)}"><meta data-static-seo property="og:type" content="website"><meta data-static-seo property="og:site_name" content="AegisForge"><script data-static-seo type="application/ld+json">${JSON.stringify(
    {
      '@context': 'https://schema.org',
      '@graph': [
        { '@type': 'Organization', name: 'AegisForge', url: origin.href },
        {
          '@type': 'SoftwareApplication',
          name: 'AegisForge',
          applicationCategory: 'DeveloperApplication',
          operatingSystem: 'Web',
        },
      ],
    },
  )}</script>`;
  const directory = `dist${route === '/' ? '' : route}`;
  await mkdir(directory, { recursive: true });
  await writeFile(
    `${directory}/index.html`,
    template.replace(/<title>.*?<\/title>/, metadata),
  );
}
await writeFile(
  'dist/sitemap.xml',
  `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${Object.keys(
    routes,
  )
    .map(
      (route) => `<url><loc>${escape(new URL(route, origin).href)}</loc></url>`,
    )
    .join('')}</urlset>`,
);
await writeFile(
  'dist/robots.txt',
  `User-agent: *\n${origin.hostname === 'localhost' ? 'Disallow: /' : 'Allow: /\nDisallow: /dev/\nDisallow: /status\nDisallow: /app/'}\nSitemap: ${new URL('/sitemap.xml', origin).href}\n`,
);
