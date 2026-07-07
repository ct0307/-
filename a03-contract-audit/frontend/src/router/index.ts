import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '工作台', eyebrow: 'LEGAL WORKBENCH' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/AuditView.vue'),
        meta: { title: '合同合规审查', eyebrow: 'AI-POWERED CONTRACT REVIEW' },
      },
      {
        path: 'collaboration',
        name: 'collaboration',
        component: () => import('@/views/CollaborationView.vue'),
        meta: { title: '双 Agent 协作', eyebrow: 'MULTI-AGENT COLLABORATION' },
      },
      {
        path: 'rectify',
        name: 'rectify',
        component: () => import('@/views/RectifyView.vue'),
        meta: { title: '整改项跟踪', eyebrow: 'RECTIFICATION TRACKING' },
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/ReportsView.vue'),
        meta: { title: '多维数据报表', eyebrow: 'MULTI-DIMENSIONAL ANALYTICS' },
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/views/KnowledgeView.vue'),
        meta: { title: '法规知识库', eyebrow: 'RAG-POWERED KNOWLEDGE BASE' },
      },
      {
        path: 'rules',
        name: 'rules',
        component: () => import('@/views/RulesView.vue'),
        meta: { title: '规则与模板管理', eyebrow: 'RULES & TEMPLATES', roles: ['admin'] },
      },
      {
        path: 'history',
        name: 'history',
        component: () => import('@/views/HistoryView.vue'),
        meta: { title: '审查历史记录', eyebrow: 'AUDIT TRAIL & HISTORY' },
      },
      {
        path: 'admin',
        name: 'admin',
        component: () => import('@/views/AdminView.vue'),
        meta: { title: '权限与审计日志', eyebrow: 'ACCESS CONTROL & AUDIT LOG', roles: ['admin'] },
      },
    ],
  },
  // 兜底：未知路由回工作台
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 导航守卫：以 auth store 为单一数据源，叠加 RBAC 角色校验。
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    return auth.isAuthenticated() ? { name: 'dashboard' } : true
  }
  if (!auth.isAuthenticated()) {
    return { name: 'login' }
  }
  const roles = to.meta.roles as string[] | undefined
  if (roles && !auth.hasRole(roles)) {
    return { name: 'dashboard' } // 越权回首页
  }
})

export default router
