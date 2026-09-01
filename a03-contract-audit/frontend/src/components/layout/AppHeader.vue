<script setup lang="ts">
// 顶栏：eyebrow 英文小标 + 中文大标题（读路由 meta）+ 右侧通知铃铛。
// 支持默认插槽，页面可注入自己的操作控件（分段/导出等）。
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import NotifyBell from './NotifyBell.vue'
import ThemeSwitcher from './ThemeSwitcher.vue'

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
      <ThemeSwitcher />
      <NotifyBell />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 72px;
  padding: 14px 28px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--ink-2);
  position: relative;
}
.topbar::after {
  content: '';
  position: absolute;
  left: 28px;
  bottom: -1px;
  width: 48px;
  height: 2px;
  background: var(--brass);
}
.eyebrow {
  margin: 0;
  font-size: 10px;
  letter-spacing: 0;
  color: var(--muted);
  font-family: var(--mono);
  font-weight: 500;
}
.topbar-title h1 {
  margin: 2px 0 0;
  font-size: 21px;
  line-height: 1.25;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
@media (max-width: 768px) {
  .topbar {
    min-height: 64px;
    padding: 12px 16px 10px;
  }
  .topbar::after { left: 16px; }
  .topbar-title h1 { font-size: 19px; }
}
</style>
