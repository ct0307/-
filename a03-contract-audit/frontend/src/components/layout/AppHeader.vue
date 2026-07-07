<script setup lang="ts">
// 顶栏：eyebrow 英文小标 + 中文大标题（读路由 meta）+ 右侧通知铃铛。
// 支持默认插槽，页面可注入自己的操作控件（分段/导出等）。
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import NotifyBell from './NotifyBell.vue'

const route = useRoute()
const eyebrow = computed(() => (route.meta.eyebrow as string) || '')
const title = computed(() => (route.meta.title as string) || '')
</script>

<template>
  <header class="topbar">
    <div class="topbar-title">
      <p class="eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
    </div>
    <div class="topbar-actions">
      <slot />
      <NotifyBell />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 22px 36px 14px;
  border-bottom: 2px solid var(--brass);
  box-shadow: 0 1px 0 var(--line);
  background: var(--ink);
}
.eyebrow {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.16em;
  color: var(--brass);
  font-family: var(--mono);
  font-weight: 500;
}
.topbar-title h1 {
  margin: 4px 0 0;
  font-size: 24px;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
