<script setup lang="ts">
// 用户卡片 + 退出登录。
// 演示视角切换仅在开发模式（import.meta.env.DEV）可见；生产构建不暴露 demo 操作。
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ROLE_PROFILES, useDemoStore, type ViewRole } from '@/stores/demo'

const router = useRouter()
const auth = useAuthStore()
const demo = useDemoStore()

const roleList = Object.values(ROLE_PROFILES)

// 仅开发环境显示演示切换
const isDev = import.meta.env.DEV

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
    return
  }
  // 仅 dev 模式才执行演示视角切换
  if (isDev) {
    demo.setViewRole(cmd as ViewRole)
    ElMessage.success(`已切换到${ROLE_PROFILES[cmd as ViewRole].viewLabel}（演示视角）`)
  }
}
</script>

<template>
  <el-dropdown trigger="click" placement="top-start" @command="onCommand">
    <div class="user-card" role="button" tabindex="0" :aria-label="isDev ? '切换演示视角或退出登录' : '用户菜单'">
      <span class="avatar seal-badge">{{ demo.profile.avatar }}</span>
      <div class="info">
        <b>{{ demo.profile.name }}</b>
        <small>{{ demo.profile.title }}</small>
      </div>
      <span v-if="isDev" class="view-dot" :style="{ background: demo.profile.dotColor }" />
    </div>
    <template #dropdown>
      <el-dropdown-menu>
        <!-- 演示视角切换：仅开发模式可见 -->
        <template v-if="isDev">
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
        </template>
        <template v-else>
          <el-dropdown-item command="logout">
            <el-icon><SwitchButton /></el-icon>退出登录
          </el-dropdown-item>
        </template>
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
