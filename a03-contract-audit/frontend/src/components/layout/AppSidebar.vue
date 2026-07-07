<script setup lang="ts">
// 侧栏：品牌印章徽标 + 8 导航（按角色过滤）+ OpenClaw 状态 + 用户卡片
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NAV_ITEMS } from '@/config/nav'
import { useAuthStore } from '@/stores/auth'
import OpenClawBadge from './OpenClawBadge.vue'
import UserSwitcher from './UserSwitcher.vue'

const route = useRoute()
const auth = useAuthStore()

// 按真实登录角色过滤菜单（RBAC）
const menuItems = computed(() => NAV_ITEMS.filter((n) => auth.hasRole(n.roles)))
const activeIndex = computed(() => route.path)
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark seal-badge">审</span>
      <div class="brand-txt">
        <b>合同智审</b>
        <small>CONTRACT COMPLIANCE</small>
      </div>
    </div>

    <el-menu :default-active="activeIndex" router class="nav">
      <el-menu-item v-for="item in menuItems" :key="item.index" :index="item.index">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </el-menu-item>
    </el-menu>

    <div class="sidebar-foot">
      <OpenClawBadge />
      <UserSwitcher />
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
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 18px 16px;
  border-bottom: 1px solid var(--line);
}
.brand-mark {
  font-size: 20px;
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
.nav {
  padding: 10px 8px;
  overflow-y: auto;
}
.nav .el-menu-item {
  border-radius: var(--r-md);
  margin-bottom: 2px;
  height: 44px;
}
.sidebar-foot {
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
</style>
