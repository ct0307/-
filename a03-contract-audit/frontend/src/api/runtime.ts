import client from './client'


export type RuntimeState = 'checking' | 'online' | 'degraded' | 'offline' | 'unknown'

export interface RuntimeStatus {
  status: RuntimeState
  checked_at: string
  provider?: string | null
  model?: string | null
  endpoint?: string | null
  detail?: string | null
  error_code?: string | null
  latency_ms?: number | null
  last_success_at?: string | null
  processing_mode?: 'private_model' | 'external_model' | 'rules_fallback'
}

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  return client.get<RuntimeStatus>('/runtime/status')
}

const runtimeErrorLabels: Record<string, string> = {
  auth_failed: '模型鉴权失败',
  endpoint_not_found: '模型地址不可用',
  model_not_found: '配置模型不存在',
  timeout: '模型服务响应超时',
  network_error: '模型网络连接失败',
  invalid_configuration: '模型配置无效',
  status_unavailable: '状态接口不可用',
}

function runtimeErrorLabel(runtime: RuntimeStatus): string {
  return runtime.error_code ? runtimeErrorLabels[runtime.error_code] ?? '模型服务异常' : '连接波动'
}

export function runtimeStatusText(runtime: RuntimeStatus): string {
  if (runtime.processing_mode === 'rules_fallback') return '模型调用已禁用，使用规则降级'
  if (runtime.status === 'online') {
    const provider = runtime.provider?.toUpperCase() || '本地模型'
    return runtime.model ? `${provider} · ${runtime.model}` : `${provider} · 运行中`
  }
  if (runtime.status === 'checking') return '正在检测模型服务'
  if (runtime.status === 'degraded') {
    const provider = runtime.provider?.toUpperCase() || '本地模型'
    const model = runtime.model ? `${provider} · ${runtime.model} · ` : ''
    return `${model}${runtimeErrorLabel(runtime)}，正在重试`
  }
  if (runtime.status === 'offline') {
    return `${runtimeErrorLabel(runtime) === '连接波动' ? '模型服务离线' : runtimeErrorLabel(runtime)}，将继续重试`
  }
  return '状态待确认'
}
