// 会话凭证 localStorage 管理：key 清单的唯一来源。
// auth store 写入/读取、http 拦截器 401 清理都必须走这里，禁止散落字符串字面量。
export const SESSION_KEYS = {
  token: 'token',
  role: 'role',
  username: 'username',
  department: 'department',
  authorizedDepartments: 'authorized_departments',
  activeAudit: 'qijian-active-audit',
} as const

/** 清空当前用户的全部会话数据（登出 / 401 凭证失效时调用）。 */
export function clearSessionStorage(): void {
  Object.values(SESSION_KEYS).forEach((key) => localStorage.removeItem(key))
}
