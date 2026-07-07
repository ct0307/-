<script setup lang="ts">
// OpenClaw 一体机运行状态徽标：脉冲绿点 + 文案。迁移自 a03-demo 侧栏。
import { useDemoStore } from '@/stores/demo'

const demo = useDemoStore()
</script>

<template>
  <div class="openclaw" :class="{ offline: !demo.runtimeOnline }">
    <span class="pulse"><i /></span>
    <div class="txt">
      <b>算力运行状态</b>
      <small>{{ demo.runtimeStatus }}</small>
    </div>
  </div>
</template>

<style scoped>
.openclaw {
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
.offline .pulse i {
  background: var(--muted);
}
.offline .pulse::after {
  display: none;
}
.txt {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.txt b {
  font-size: 12px;
  color: var(--ivory);
}
.txt small {
  font-size: 11px;
  color: var(--ivory-dim);
  font-family: var(--mono);
}
@keyframes ring {
  0% {
    transform: scale(0.7);
    opacity: 0.8;
  }
  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}
</style>
