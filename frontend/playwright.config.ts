import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command:
        '. .venv/bin/activate && python scripts/reset_dev_db.py && uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001',
      cwd: '..',
      env: {
        FYNISH_SQLITE_DATABASE_PATH: '/private/tmp/fynish-e2e.sqlite3',
      },
      port: 8001,
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      cwd: '.',
      env: {
        VITE_API_BASE_URL: 'http://127.0.0.1:8001/api',
      },
      port: 4173,
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
})
