import type { RuntimeStatus } from '@/api/runtime'


export interface RuntimeStatusState {
  current: RuntimeStatus
  consecutiveFailures: number
  lastOnline: RuntimeStatus | null
}


export function createRuntimeStatusState(): RuntimeStatusState {
  return {
    current: {
      status: 'checking',
      checked_at: '',
    },
    consecutiveFailures: 0,
    lastOnline: null,
  }
}


export function transitionRuntimeStatus(
  state: RuntimeStatusState,
  result: RuntimeStatus,
): RuntimeStatusState {
  if (result.status === 'online') {
    return { current: result, consecutiveFailures: 0, lastOnline: result }
  }

  if (result.status === 'checking') {
    const previous = state.lastOnline
    return {
      current: {
        ...result,
        provider: result.provider ?? previous?.provider ?? null,
        model: result.model ?? previous?.model ?? null,
        endpoint: result.endpoint ?? previous?.endpoint ?? null,
        last_success_at: result.last_success_at ?? previous?.checked_at ?? null,
      },
      consecutiveFailures: 0,
      lastOnline: previous,
    }
  }

  const consecutiveFailures = state.consecutiveFailures + 1
  const previous = state.lastOnline
  const current: RuntimeStatus = {
    ...result,
    status: consecutiveFailures >= 2 ? 'offline' : 'degraded',
    provider: result.provider ?? previous?.provider ?? null,
    model: result.model ?? previous?.model ?? null,
    endpoint: result.endpoint ?? previous?.endpoint ?? null,
    last_success_at: result.last_success_at ?? previous?.checked_at ?? null,
  }
  return { current, consecutiveFailures, lastOnline: previous }
}
