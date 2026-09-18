import { defineConfig } from '@playwright/test';
const devServer = {
  command: 'pnpm dev --port 5174 --strictPort',
  timeout: 120000,
  url: 'http://127.0.0.1:5174',
  reuseExistingServer: false,
};
export default defineConfig({
  testDir: './e2e',
  workers: 2,
  use: { baseURL: 'http://127.0.0.1:4173' },
  projects: [
    {
      name: 'auth',
      testMatch: /auth.spec|configuration.spec|scans.spec/,
      use: { baseURL: 'http://127.0.0.1:5174' },
    },
    {
      name: 'production',
      testMatch:
        /health|production|marketing|findings|policies|dashboard|reporting/,
    },
    {
      name: 'labs',
      testMatch: /labs/,
      use: { baseURL: 'http://127.0.0.1:5174' },
    },
  ],
  webServer:
    process.env.AEGIS_E2E_AUTH === '1'
      ? [devServer]
      : [
          {
            command: 'pnpm build && pnpm preview --port 4173',
            timeout: 120000,
            url: 'http://127.0.0.1:4173',
            reuseExistingServer: false,
          },
          devServer,
        ],
});
