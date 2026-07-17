import { defineConfig, devices } from '@playwright/test';

// Optional smoke test. Runs the built app via `vite preview`. The advisory
// banner renders even without the API (it defaults to advisory/no-write), so
// this smoke does not require the backend to be running.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
