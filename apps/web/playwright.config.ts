import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  workers: 2,
  use: { baseURL: 'http://127.0.0.1:4173' },
  projects: [
    { name: 'production', testMatch: /health|production/ },
    {
      name: 'labs',
      testMatch: /labs/,
      use: { baseURL: 'http://127.0.0.1:5174' },
    },
  ],
  webServer: [
    {
      command: 'pnpm build && pnpm preview --port 4173',
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: false,
    },
    {
      command: 'pnpm dev --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
    },
  ],
});
