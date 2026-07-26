import client from './client'


export type RuntimeState = 'online' | 'offline' | 'unknown'

export interface RuntimeStatus {
  status: RuntimeState
  checked_at: string
  provider: string | null
  model: string | null
  endpoint: string | null
  detail: string | null
}

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  return client.get<RuntimeStatus>('/runtime/status') as unknown as RuntimeStatus
}

export function runtimeStatusText(runtime: RuntimeStatus): string {
  if (runtime.status === 'online') {
    const provider = runtime.provider?.toUpperCase() || '本地模型'
    return runtime.model ? `${provider} · ${runtime.model}` : `${provider} · 运行中`
  }
  return runtime.status === 'offline' ? '模型服务离线' : '状态待确认'
}
