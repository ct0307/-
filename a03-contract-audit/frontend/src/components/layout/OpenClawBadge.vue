<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  getRuntimeStatus,
  runtimeStatusText,
  type RuntimeStatus,
} from '@/api/runtime'

const runtime = ref<RuntimeStatus>({
  status: 'unknown',
  checked_at: '',
  provider: null,
  model: null,
  endpoint: null,
  detail: null,
})
const label = computed(() => runtimeStatusText(runtime.value))
const title = computed(() => {
  const parts = [runtime.value.detail, runtime.value.endpoint]
  return parts.filter(Boolean).join(' · ') || label.value
})
let timer: ReturnType<typeof setInterval> | undefined

async function refreshRuntime() {
  try {
    runtime.value = await getRuntimeStatus()
  } catch {
    runtime.value = {
      status: 'unknown',
      checked_at: new Date().toISOString(),
      provider: null,
      model: null,
      endpoint: null,
      detail: '运行状态接口不可用',
    }
  }
}

onMounted(() => {
  void refreshRuntime()
  timer = setInterval(refreshRuntime, 30_000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div
    class="compute-badge"
    :class="`is-${runtime.status}`"
    :title="title"
    role="status"
    aria-live="polite"
  >
    <span class="pulse"><i /></span>
    <div class="txt">
      <b>本地算力</b>
      <small>{{ label }}</small>
    </div>
  </div>
</template>

<style scoped>
.compute-badge {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin: 0 8px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
}
.pulse {
  position: relative;
  width: 10px;
  height: 10px;
  flex: none;
}
.pulse i {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--sage);
}
.pulse::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid var(--sage);
  animation: ring 2.4s var(--ease) infinite;
}
.is-offline .pulse i { background: var(--muted); }
.is-offline .pulse::after { display: none; }
.is-unknown .pulse i { background: var(--amber); }
.is-unknown .pulse::after { display: none; }
.txt {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  min-width: 0;
}
.txt b     { font-size: 12px; color: var(--ivory); }
.txt small {
  max-width: 142px;
  overflow: hidden;
  font-size: 11px;
  color: var(--ivory-dim);
  font-family: var(--mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}
@keyframes ring {
  0%   { transform: scale(0.7); opacity: 0.8; }
  100% { transform: scale(1.6); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .pulse::after { animation: none; }
}
</style>
