import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: fileURLToPath(new URL('../tests/ui/e2e', import.meta.url)),
  outputDir: fileURLToPath(new URL('./test-results', import.meta.url)),
  use: { baseURL: 'http://localhost:5173', channel: 'chrome' },
  webServer: {
    command: 'npm run dev:ui',
    cwd: fileURLToPath(new URL('..', import.meta.url)),
    url: 'http://localhost:5173',
    reuseExistingServer: true,
  },
});
