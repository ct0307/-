<script setup lang="ts">
// 主布局：侧栏（支持折叠 + 移动端 overlay）+ 顶栏 + 主区 router-view。
// collapsed 通过 provide 传给 AppSidebar，双方通过同一个 ref 驱动宽度和菜单状态。
// mobileOpen 用于 ≤768px 时侧栏 overlay 的显隐。
import { ref, provide, computed, onMounted, onUnmounted, watch } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'

const collapsed = ref(false)
provide('sidebarCollapsed', collapsed)

// 移动端 overlay 开关
const mobileOpen = ref(false)
provide('mobileSidebarOpen', mobileOpen)

// 判断移动端（≤768px）
const isMobile = ref(false)
function checkMobile() {
  isMobile.value = window.innerWidth <= 768
  if (!isMobile.value) mobileOpen.value = false
}
onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = '' // 确保组件卸载时恢复滚动
})

function toggleMobile() {
  mobileOpen.value = !mobileOpen.value
  // 打开后的焦点迁移由 AppSidebar 在设完 roving tabindex 后统一处理，避免跨组件时序竞争
}

// Escape 关闭侧栏
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && mobileOpen.value) mobileOpen.value = false
}

// 侧栏打开时锁定背景滚动，关闭时恢复
watch(mobileOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

// 折叠态 64px（仅图标），展开态 264px；移动端不参与 grid 列计算
const sidebarWidth = computed(() => {
  if (isMobile.value) return '0px'
  return collapsed.value ? '64px' : '264px'
})
</script>

<template>
  <div class="app-shell">
    <!-- 移动端遮罩：点击关闭侧栏 -->
    <Transition name="backdrop-fade">
      <div
        v-if="isMobile && mobileOpen"
        class="mobile-backdrop"
        @click="mobileOpen = false"
      />
    </Transition>

    <!-- inert：移动端侧栏关闭时整体设为不可交互，一行覆盖所有后代元素（包括 UserSwitcher 等固定 tabindex 的元素） -->
    <AppSidebar
      id="app-sidebar"
      class="shell-side"
      :class="{ 'mobile-open': isMobile && mobileOpen, 'mobile-mode': isMobile }"
      :inert="(isMobile && !mobileOpen) ? true : undefined"
    />

    <div class="shell-main">
      <AppHeader>
        <!-- 移动端汉堡按钮，注入到 header actions 插槽 -->
        <button
          v-if="isMobile"
          class="hamburger-btn"
          :aria-label="mobileOpen ? '关闭导航菜单' : '打开导航菜单'"
          :aria-expanded="mobileOpen"
          aria-controls="app-sidebar"
          @click="toggleMobile"
        >
          <el-icon :size="20"><Menu /></el-icon>
        </button>
      </AppHeader>
      <main class="shell-content">
        <div class="content-inner">
          <router-view v-slot="{ Component }">
            <component :is="Component" />
          </router-view>
        </div>
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

/* 超宽屏内容区 max-width，防止 2560px 下留白过大 */
.content-inner {
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

/* ── 移动端 overlay 模式 ── */
/* 侧栏固定定位，默认左移隐藏 */
.shell-side.mobile-mode {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  width: 264px !important;
  z-index: 100;
  transform: translateX(-100%);
  transition: transform 0.25s var(--ease);
  box-shadow: none;
}
.shell-side.mobile-mode.mobile-open {
  transform: translateX(0);
  box-shadow: 4px 0 20px rgba(0, 0, 0, 0.18);
}

/* 遮罩层 */
.mobile-backdrop {
  position: fixed;
  inset: 0;
  z-index: 99;
  background: rgba(0, 0, 0, 0.35);
}
.backdrop-fade-enter-active,
.backdrop-fade-leave-active {
  transition: opacity 0.2s ease;
}
.backdrop-fade-enter-from,
.backdrop-fade-leave-to {
  opacity: 0;
}

/* 汉堡按钮 */
.hamburger-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px 8px;
  background: none;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  color: var(--ivory);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.hamburger-btn:hover {
  background: var(--brass-soft);
  color: var(--brass);
}

/* 响应式：≤1180px 侧栏转顶部横向条（非移动端中间断点） */
@media (max-width: 1180px) and (min-width: 769px) {
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

/* 移动端（≤768px） */
@media (max-width: 768px) {
  .app-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    height: auto;
    min-height: 100vh;
    overflow: visible;
  }
  .shell-content {
    padding: 14px 16px 28px;
  }
}
</style>
