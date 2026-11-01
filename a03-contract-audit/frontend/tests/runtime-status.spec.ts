import { expect, test } from '@playwright/test'

import { runtimeStatusText, type RuntimeStatus } from '../src/api/runtime'

test('规则模式明确禁用模型，不伪装为离线重试', () => {
  expect(runtimeStatusText({ status: 'degraded', checked_at: '', processing_mode: 'rules_fallback' })).toBe('模型调用已禁用，使用规则降级')
})


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
  expect(runtimeStatusText(status('offline'))).toBe('模型服务离线，将继续重试')
  expect(runtimeStatusText(status('unknown'))).toBe('状态待确认')
})

test('maps safe classified failures without exposing backend detail', () => {
  const failed = status('offline')
  failed.error_code = 'auth_failed'
  failed.detail = 'Authorization=Bearer secret'

  expect(runtimeStatusText(failed)).toBe('模型鉴权失败，将继续重试')
  expect(runtimeStatusText(failed)).not.toContain('secret')
})

test('shows the last online model and retry reason while degraded', () => {
  const degraded = status('degraded')
  degraded.provider = 'deepseek'
  degraded.model = 'deepseek-v4-pro'
  degraded.error_code = 'timeout'
  degraded.detail = '内部堆栈 secret'

  expect(runtimeStatusText(degraded)).toBe('DEEPSEEK · deepseek-v4-pro · 模型服务响应超时，正在重试')
  expect(runtimeStatusText(degraded)).not.toContain('secret')
})

test('explains that offline status will continue retrying', () => {
  const offline = status('offline')
  offline.error_code = 'network_error'

  expect(runtimeStatusText(offline)).toBe('模型网络连接失败，将继续重试')
})
