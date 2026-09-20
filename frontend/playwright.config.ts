import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  webServer: {
    command: 'uv run python ../scripts/e2e_demo.py',
    url: 'http://127.0.0.1:8001/api/health',
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
    timeout: 30000,
  },
  use: {
    baseURL: 'http://127.0.0.1:8001',
    viewport: { width: 390, height: 844 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  reporter: 'list',
})
