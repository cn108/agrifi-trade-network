import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    // Must be `localhost`: the API at localhost:8000 sets cookies for that site only.
    baseURL: 'http://localhost:4201',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: 'node e2e/start-api.mjs',
      url: 'http://localhost:8010/healthz/',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run start -- --configuration=e2e --host localhost --port 4201',
      url: 'http://localhost:4201/login',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
