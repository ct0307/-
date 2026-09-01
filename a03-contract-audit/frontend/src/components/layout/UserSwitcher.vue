<script setup lang="ts">
// 用户卡片 + 退出登录。
// 演示视角切换仅在开发模式（import.meta.env.DEV）可见；生产构建不暴露 demo 操作。
// 切换时执行真实登录，替换 JWT Token，确保 RBAC/数据过滤真正生效。
import { ref } from 'vue'
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

// 演示角色 → 真实登录凭据（对应 seed_demo.py 初始化账号）
const DEMO_CREDENTIALS: Record<ViewRole, { username: string; password: string }> = {
  legal:   { username: 'legal',   password: 'legal123' },
  finance: { username: 'finance', password: 'finance123' },
  admin:   { username: 'admin',   password: 'admin123' },
}

const switching = ref(false)

async function onCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
    return
  }
  // 仅 dev 模式才执行演示视角切换
  if (!isDev || switching.value) return

  const target = cmd as ViewRole
  // 已经是当前角色，跳过
  if (target === demo.viewRole && auth.role === target) return

  const creds = DEMO_CREDENTIALS[target]
  if (!creds) return

  switching.value = true
  try {
    // 用真实账号登录，替换 JWT Token 和 auth.role
    await auth.login(creds.username, creds.password)
    // 同步演示显示名/头像
    demo.setViewRole(target)
    ElMessage.success(`已切换到${ROLE_PROFILES[target].viewLabel}`)
    // 跳转工作台，触发各视图重新拉取数据
    await router.replace('/dashboard')
  } catch {
    ElMessage.error('切换失败，请检查后端连接')
  } finally {
    switching.value = false
  }
}
</script>

<template>
  <el-dropdown trigger="click" placement="top-start" @command="onCommand">
    <div class="user-card" role="button" tabindex="0"
         :aria-label="isDev ? '切换演示视角或退出登录' : '用户菜单'"
         :class="{ 'is-switching': switching }">
      <span class="avatar seal-badge">{{ demo.profile.avatar }}</span>
      <div class="info">
        <b>{{ demo.profile.name }}</b>
        <small>{{ switching ? '切换中…' : demo.profile.title }}</small>
      </div>
      <el-icon v-if="switching" class="spin"><Loading /></el-icon>
      <span v-else-if="isDev" class="view-dot" :style="{ background: demo.profile.dotColor }" />
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
  padding: 8px 12px;
  margin: 4px 8px 8px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: transparent;
  cursor: pointer;
  transition: border-color 0.2s var(--ease);
}
.user-card:hover {
  border-color: var(--line);
  background: var(--ink-3);
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
.is-switching {
  opacity: 0.7;
  cursor: wait;
}
.spin {
  flex: none;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
