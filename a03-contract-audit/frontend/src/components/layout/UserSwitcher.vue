<script setup lang="ts">
// 用户卡片 + 演示视角切换。
// 真实登录角色由 auth.role 决定（不可改）；这里切换的是 demo.viewRole（仅驱动 mock 展示）。
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ROLE_PROFILES, useDemoStore, type ViewRole } from '@/stores/demo'

const router = useRouter()
const auth = useAuthStore()
const demo = useDemoStore()

const roleList = Object.values(ROLE_PROFILES)

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
    return
  }
  demo.setViewRole(cmd as ViewRole)
  ElMessage.success(`已切换到${ROLE_PROFILES[cmd as ViewRole].viewLabel}（演示视角）`)
}
</script>

<template>
  <el-dropdown trigger="click" placement="top-start" @command="onCommand">
    <div class="user-card" role="button" tabindex="0" aria-label="切换演示视角或退出登录">
      <span class="avatar seal-badge">{{ demo.profile.avatar }}</span>
      <div class="info">
        <b>{{ demo.profile.name }}</b>
        <small>{{ demo.profile.title }}</small>
      </div>
      <span class="view-dot" :style="{ background: demo.profile.dotColor }" />
    </div>
    <template #dropdown>
      <el-dropdown-menu>
        <div class="dd-title">演示视角切换</div>
        <el-dropdown-item
          v-for="r in roleList"
          :key="r.key"
          :command="r.key"
          :class="{ active: r.key === demo.viewRole }"
        >
          <span class="dd-dot" :style="{ background: r.dotColor }" />
          {{ r.name }} · {{ r.viewLabel }}
        </el-dropdown-item>
        <el-dropdown-item command="logout" divided>
          <el-icon><SwitchButton /></el-icon>退出登录
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin: 8px 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--ink-2);
  cursor: pointer;
  transition: border-color 0.2s var(--ease);
}
.user-card:hover {
  border-color: var(--brass);
}
.avatar {
  flex: none;
}
.info {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  flex: 1;
  min-width: 0;
}
.info b {
  font-size: 13px;
  color: var(--ivory);
}
.info small {
  font-size: 11px;
  color: var(--ivory-dim);
}
.view-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.dd-title {
  padding: 6px 16px;
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.05em;
}
.dd-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 8px;
}
:deep(.el-dropdown-menu__item.active) {
  color: var(--brass);
  font-weight: 600;
}
</style>
