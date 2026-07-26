import { expect, test } from '@playwright/test'

import { runtimeStatusText, type RuntimeStatus } from '../src/api/runtime'


function status(state: RuntimeStatus['status']): RuntimeStatus {
  return {
    status: state,
    checked_at: '2026-07-26T10:00:00Z',
    provider: state === 'online' ? 'qwen' : null,
    model: state === 'online' ? 'qwen2.5:14b' : null,
    endpoint: 'http://localhost:11434/v1',
    detail: state === 'unknown' ? '健康探测响应缺少模型标识' : null,
  }
}


test('maps online runtime to model-aware label', () => {
  expect(runtimeStatusText(status('online'))).toBe('QWEN · qwen2.5:14b')
})

test('keeps offline and unknown states distinct', () => {
  expect(runtimeStatusText(status('offline'))).toBe('模型服务离线')
  expect(runtimeStatusText(status('unknown'))).toBe('状态待确认')
})
