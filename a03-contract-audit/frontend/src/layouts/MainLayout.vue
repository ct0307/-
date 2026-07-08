<script setup lang="ts">
// 主布局：侧栏（支持折叠）+ 顶栏 + 主区 router-view。
// collapsed 通过 provide 传给 AppSidebar，双方通过同一个 ref 驱动宽度和菜单状态。
import { ref, provide, computed } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'

const collapsed = ref(false)
provide('sidebarCollapsed', collapsed)

// 折叠态 64px（仅图标），展开态 264px
const sidebarWidth = computed(() => (collapsed.value ? '64px' : '264px'))
</script>

<template>
  <div class="app-shell">
    <AppSidebar class="shell-side" />
    <div class="shell-main">
      <AppHeader />
      <main class="shell-content">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: v-bind(sidebarWidth) 1fr;
  height: 100vh;
  overflow: hidden;
  transition: grid-template-columns 0.25s ease;
}
.shell-side {
  overflow: hidden;
}
.shell-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.shell-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px 36px 40px;
}

/* 响应式：≤1180 侧栏转顶部横向条 */
@media (max-width: 1180px) {
  .app-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    height: auto;
    min-height: 100vh;
    overflow: visible;
  }
  .shell-side {
    height: auto;
  }
  .shell-content {
    padding: 18px 20px 32px;
  }
}
</style>
