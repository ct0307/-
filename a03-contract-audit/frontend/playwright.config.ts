import { defineConfig } from '@playwright/test'

interface E2ERuntime {
  baseURL: string
  webServer?: {
    command: string
    url: string
    reuseExistingServer: boolean
  }
}

export function resolveE2ERuntime(
  env: Record<string, string | undefined> = process.env,
): E2ERuntime {
  const configuredBaseUrl = env.E2E_BASE_URL?.trim()
  if (configuredBaseUrl) return { baseURL: configuredBaseUrl }

  const rawPort = env.E2E_PORT?.trim() || '41739'
  const port = Number(rawPort)
  if (!/^\d+$/.test(rawPort) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`E2E_PORT 必须是 1-65535 的整数，当前值：${rawPort}`)
  }
  const baseURL = `http://127.0.0.1:${port}`
  return {
    baseURL,
    webServer: {
      command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
      url: baseURL,
      reuseExistingServer: false,
    },
  }
}

const runtime = resolveE2ERuntime()

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  reporter: 'line',
  workers: 2,
  use: { baseURL: runtime.baseURL },
  webServer: runtime.webServer,
})
