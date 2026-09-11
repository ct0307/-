import { expect, test } from '@playwright/test'

import type { RuntimeStatus } from '../src/api/runtime'
import {
  createRuntimeStatusState,
  transitionRuntimeStatus,
} from '../src/utils/runtime-status'


function online(): RuntimeStatus {
  return {
    status: 'online',
    checked_at: '2026-09-11T10:00:00Z',
    provider: 'deepseek',
    model: 'deepseek-v4-pro',
  }
}


function failure(errorCode = 'timeout'): RuntimeStatus {
  return {
    status: 'offline',
    checked_at: '2026-09-11T10:00:30Z',
    error_code: errorCode,
  }
}


test('starts in checking state', () => {
  expect(createRuntimeStatusState().current.status).toBe('checking')
})


test('keeps last model and degrades after one failed probe', () => {
  const connected = transitionRuntimeStatus(createRuntimeStatusState(), online())
  const degraded = transitionRuntimeStatus(connected, failure())

  expect(degraded.current.status).toBe('degraded')
  expect(degraded.current.model).toBe('deepseek-v4-pro')
  expect(degraded.consecutiveFailures).toBe(1)
})


test('marks runtime offline only after two consecutive failures', () => {
  const connected = transitionRuntimeStatus(createRuntimeStatusState(), online())
  const once = transitionRuntimeStatus(connected, failure())
  const twice = transitionRuntimeStatus(once, failure('network_error'))

  expect(twice.current.status).toBe('offline')
  expect(twice.current.error_code).toBe('network_error')
  expect(twice.consecutiveFailures).toBe(2)
})


test('recovers immediately after a successful probe', () => {
  const once = transitionRuntimeStatus(createRuntimeStatusState(), failure())
  const recovered = transitionRuntimeStatus(once, online())

  expect(recovered.current.status).toBe('online')
  expect(recovered.consecutiveFailures).toBe(0)
  expect(recovered.current.model).toBe('deepseek-v4-pro')
})

test('transitions from degraded to offline and immediately back online', () => {
  const connected = transitionRuntimeStatus(createRuntimeStatusState(), online())
  const degraded = transitionRuntimeStatus(connected, failure('timeout'))
  const offline = transitionRuntimeStatus(degraded, failure('network_error'))
  const recovered = transitionRuntimeStatus(offline, online())

  expect(degraded.current.status).toBe('degraded')
  expect(degraded.current.model).toBe('deepseek-v4-pro')
  expect(offline.current.status).toBe('offline')
  expect(offline.current.error_code).toBe('network_error')
  expect(recovered.current.status).toBe('online')
  expect(recovered.consecutiveFailures).toBe(0)
})

test('does not count checking responses as probe failures', () => {
  const checking: RuntimeStatus = {
    status: 'checking',
    checked_at: '2026-09-11T10:00:00Z',
  }

  const once = transitionRuntimeStatus(createRuntimeStatusState(), checking)
  const twice = transitionRuntimeStatus(once, checking)

  expect(twice.current.status).toBe('checking')
  expect(twice.consecutiveFailures).toBe(0)
})
