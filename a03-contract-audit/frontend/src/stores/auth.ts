import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login as loginApi } from '@/api/contract'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const role = ref<string>(localStorage.getItem('role') || '')

  async function login(username: string, password: string) {
    const res = await loginApi(username, password)
    token.value = res.access_token
    role.value = res.role
    localStorage.setItem('token', res.access_token)
    localStorage.setItem('role', res.role)
  }

  function logout() {
    token.value = ''
    role.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('role')
  }

  function isAuthenticated() {
    return !!token.value
  }

  // RBAC：admin 通配所有角色；未限定角色的资源默认放行。
  // 与后端 deps.require_roles 语义一致。
  function hasRole(roles?: string[]) {
    if (!roles || roles.length === 0) return true
    if (role.value === 'admin') return true
    return roles.includes(role.value)
  }

  return { token, role, login, logout, isAuthenticated, hasRole }
})
