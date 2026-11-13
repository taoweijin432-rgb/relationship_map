import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const baseURL = `http://127.0.0.1:${process.env.RELATIONSHIP_WEB_PORT || 5173}`

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    viewport: { width: 1600, height: 1000 },
    headless: true,
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'bash ../scripts/dev.sh',
    env:
      process.env.RELATIONSHIP_REAL_BROWSER === '1' ||
      process.env.RELATIONSHIP_NUMERIC_BROWSER === '1' ||
      process.env.RELATIONSHIP_UUID_BROWSER === '1' ||
      [
        'RELATIONSHIP_DATABASE',
        'RELATIONSHIP_MYSQL_URL',
        'RELATIONSHIP_SOURCE_API_MANIFEST',
        'RELATIONSHIP_SOURCE_RELEASE_STORE',
        'RELATIONSHIP_NUMERIC_RELEASE_STORE',
        'RELATIONSHIP_NEBULA_MANIFEST',
      ].some((name) => process.env[name])
        ? {}
        : {
            RELATIONSHIP_DATABASE: fileURLToPath(
              new URL('../data/mock-v1.sqlite', import.meta.url),
            ),
          },
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
    timeout: 180000,
  },
})
