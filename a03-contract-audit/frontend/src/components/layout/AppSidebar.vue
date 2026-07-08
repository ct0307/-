<script setup lang="ts">
// 侧栏：品牌印章徽标 + 导航（按角色过滤）+ OpenClaw 状态 + 用户卡片 + 折叠按钮。
// collapsed 由 MainLayout 通过 provide 注入，双方共享同一个 ref。
import { computed, inject, ref, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { NAV_ITEMS } from '@/config/nav'
import { useAuthStore } from '@/stores/auth'
import OpenClawBadge from './OpenClawBadge.vue'
import UserSwitcher from './UserSwitcher.vue'

const route = useRoute()
const auth = useAuthStore()

// 折叠状态：由 MainLayout 注入；fallback 为本地 ref（防止脱离 layout 独用时报错）
const collapsed = inject<Ref<boolean>>('sidebarCollapsed', ref(false))

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

// 按真实登录角色过滤菜单（RBAC）
const menuItems = computed(() => NAV_ITEMS.filter((n) => auth.hasRole(n.roles)))
const activeIndex = computed(() => route.path)
</script>

<template>
  <aside class="sidebar" :class="{ 'is-collapsed': collapsed }">
    <!-- 品牌区 -->
    <div class="brand">
      <span class="brand-mark seal-badge">审</span>
      <div v-if="!collapsed" class="brand-txt">
        <b>合同智审</b>
        <small>CONTRACT COMPLIANCE</small>
      </div>
    </div>

    <!-- 导航菜单：collapse 模式下只显示图标，悬停 tooltip 显示标签 -->
    <el-menu
      :default-active="activeIndex"
      :collapse="collapsed"
      :collapse-transition="true"
      router
      class="nav"
    >
      <el-menu-item v-for="item in menuItems" :key="item.index" :index="item.index">
        <el-icon><component :is="item.icon" /></el-icon>
        <template #title>{{ item.label }}</template>
      </el-menu-item>
    </el-menu>

    <!-- 底部：折叠按钮 + 状态 + 用户卡片（折叠时只保留折叠按钮） -->
    <div class="sidebar-foot">
      <template v-if="!collapsed">
        <OpenClawBadge />
        <UserSwitcher />
      </template>
      <button
        class="collapse-btn"
        :title="collapsed ? '展开侧栏' : '收起侧栏'"
        :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
        @click="toggleCollapse"
      >
        <el-icon>
          <Expand v-if="collapsed" />
          <Fold v-else />
        </el-icon>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: grid;
  grid-template-rows: auto 1fr auto;
  height: 100%;
  background: var(--ink-2);
  border-right: 1px solid var(--line);
  /* 折叠动画期间不裁剪 tooltip */
  overflow: visible;
  transition: width 0.25s ease;
}

/* 品牌区 */
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 18px 16px;
  border-bottom: 1px solid var(--line);
  overflow: hidden;
  white-space: nowrap;
}
.brand-mark {
  font-size: 20px;
  flex: none;
}
.brand-txt {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.brand-txt b {
  font-family: var(--serif);
  font-size: 17px;
  color: var(--ivory);
}
.brand-txt small {
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--muted);
  font-family: var(--mono);
}

/* 导航 */
.nav {
  padding: 10px 8px;
  overflow-y: auto;
  overflow-x: hidden;
  /* 必须覆盖 el-menu 默认边框 */
  border-right: none !important;
}
.nav .el-menu-item {
  border-radius: var(--r-md);
  margin-bottom: 2px;
  height: 44px;
}

/* 折叠态：菜单居中，padding 缩小 */
.is-collapsed .nav {
  padding: 10px 4px;
}
.is-collapsed .brand {
  justify-content: center;
  padding: 20px 0 16px;
}

/* 底部区域 */
.sidebar-foot {
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

/* 折叠/展开按钮 */
.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 36px;
  background: none;
  border: none;
  border-top: 1px solid var(--line);
  color: var(--muted);
  cursor: pointer;
  transition: color 0.2s var(--ease), background 0.2s var(--ease);
  font-size: 15px;
}
.collapse-btn:hover {
  color: var(--brass);
  background: var(--ink-3);
}
</style>
