import { expect, test } from '@playwright/test'

import * as playwrightConfig from '../playwright.config'

test('derives isolated local servers from E2E_PORT while preserving external base urls', () => {
  const resolver = (playwrightConfig as unknown as {
    resolveE2ERuntime?: (env: Record<string, string | undefined>) => {
      baseURL: string
      webServer?: { command: string; url: string }
    }
  }).resolveE2ERuntime

  expect(typeof resolver).toBe('function')
  if (!resolver) return

  const first = resolver({ E2E_PORT: '43101' })
  const second = resolver({ E2E_PORT: '43102' })
  const external = resolver({
    E2E_PORT: '43103',
    E2E_BASE_URL: 'http://127.0.0.1:5199',
  })

  expect(first.baseURL).toBe('http://127.0.0.1:43101')
  expect(first.webServer?.url).toBe(first.baseURL)
  expect(first.webServer?.command).toContain('--port 43101')
  expect(second.baseURL).toBe('http://127.0.0.1:43102')
  expect(second.webServer?.command).toContain('--port 43102')
  expect(second.baseURL).not.toBe(first.baseURL)
  expect(external.baseURL).toBe('http://127.0.0.1:5199')
  expect(external.webServer).toBeUndefined()
})
