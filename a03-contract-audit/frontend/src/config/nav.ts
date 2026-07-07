// 侧栏 8 导航配置 · 迁移自 a03-demo 的 8 个视图
// icon 用全局注册的 Element Plus 图标组件名；roles 为空表示所有登录角色可见。
export interface NavItem {
  index: string // 路由 path，用作 el-menu 的 index
  name: string // 路由 name
  label: string
  icon: string
  roles?: string[] // 限定可见角色（RBAC）；缺省 = 全部
}

export const NAV_ITEMS: NavItem[] = [
  { index: '/dashboard', name: 'dashboard', label: '工作台', icon: 'Odometer' },
  { index: '/audit', name: 'audit', label: '合同审查', icon: 'DocumentChecked' },
  { index: '/rectify', name: 'rectify', label: '整改跟踪', icon: 'SetUp' },
  { index: '/reports', name: 'reports', label: '多维报表', icon: 'DataAnalysis' },
  { index: '/knowledge', name: 'knowledge', label: '法规知识库', icon: 'Collection' },
  { index: '/rules', name: 'rules', label: '规则与模板', icon: 'Files', roles: ['admin'] },
  { index: '/history', name: 'history', label: '审查记录', icon: 'Clock' },
  { index: '/admin', name: 'admin', label: '权限与审计', icon: 'Lock', roles: ['admin'] },
]
