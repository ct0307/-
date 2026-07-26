import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

// 演示视角角色：仅驱动 mock 页（工作台 KPI / 待办 / 权限矩阵展示），
// 不影响真实登录角色 auth.role 与后端 RBAC 鉴权。
export type ViewRole = 'legal' | 'finance' | 'admin'

export interface RoleProfile {
  key: ViewRole
  name: string
  title: string
  avatar: string
  eyebrow: string
  viewLabel: string
  dotColor: string
}

// 迁移自 a03-demo：三角色画像
export const ROLE_PROFILES: Record<ViewRole, RoleProfile> = {
  legal: {
    key: 'legal',
    name: '曾庆豪',
    title: '法务主管',
    avatar: '曾',
    eyebrow: 'LEGAL WORKBENCH',
    viewLabel: '法务视角',
    dotColor: 'var(--brass)',
  },
  finance: {
    key: 'finance',
    name: '陈嘉禾',
    title: '财务主管',
    avatar: '陈',
    eyebrow: 'FINANCE WORKBENCH',
    viewLabel: '财务视角',
    dotColor: 'var(--sage)',
  },
  admin: {
    key: 'admin',
    name: '王督政',
    title: '系统管理员',
    avatar: '王',
    eyebrow: 'ADMIN CONSOLE',
    viewLabel: '全域视角',
    dotColor: 'var(--seal)',
  },
}

export const useDemoStore = defineStore('demo', () => {
  const viewRole = ref<ViewRole>('legal')

  const profile = computed(() => ROLE_PROFILES[viewRole.value])

  function setViewRole(role: ViewRole) {
    viewRole.value = role
  }

  return { viewRole, profile, setViewRole }
})
