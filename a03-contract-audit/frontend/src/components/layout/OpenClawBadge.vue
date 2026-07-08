<script setup lang="ts">
// 本地算力运行状态徽标（避免技术术语"OpenClaw"暴露给普通用户）
import { useDemoStore } from '@/stores/demo'

const demo = useDemoStore()
</script>

<template>
  <div class="compute-badge" :class="{ offline: !demo.runtimeOnline }">
    <span class="pulse"><i /></span>
    <div class="txt">
      <b>本地算力</b>
      <small>{{ demo.runtimeOnline ? '运行中' : '离线' }}</small>
    </div>
  </div>
</template>

<style scoped>
.compute-badge {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--sage-soft);
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
  animation: ring 1.8s var(--ease) infinite;
}
.offline .pulse i { background: var(--muted); }
.offline .pulse::after { display: none; }
.txt {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.txt b     { font-size: 12px; color: var(--ivory); }
.txt small { font-size: 11px; color: var(--ivory-dim); font-family: var(--mono); }
@keyframes ring {
  0%   { transform: scale(0.7); opacity: 0.8; }
  100% { transform: scale(1.6); opacity: 0; }
}
</style>
