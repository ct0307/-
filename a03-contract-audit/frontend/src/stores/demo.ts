import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAuthStore } from './auth'

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

// 沿用早期交互原型中的三角色画像，仅作为演示视角数据。
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

  const auth = useAuthStore()
  const profile = computed(() => {
    const role = auth.role
    const base = ROLE_PROFILES[role as ViewRole] || ROLE_PROFILES.legal
    const title = ({ legal: '法务人员', finance: '财务人员', admin: '系统管理员', business: '业务人员' } as Record<string, string>)[role] || '当前用户'
    return { ...base, name: auth.username || '未登录', avatar: (auth.username || '?').slice(0, 1),
      title: `${title}${auth.department ? ' · ' + auth.department : ''}`,
      viewLabel: `${title}工作台`, eyebrow: role === 'business' ? 'BUSINESS WORKBENCH' : base.eyebrow }
  })

  function setViewRole(role: ViewRole) {
    viewRole.value = role
  }

  return { viewRole, profile, setViewRole }
})
