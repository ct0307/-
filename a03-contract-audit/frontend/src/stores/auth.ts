import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login as loginApi } from '@/api/contract'
import { useAuditSessionStore } from '@/stores/audit-session'
import { useBatchStore } from '@/stores/batch'
import { useImportInboxStore } from '@/stores/import-inbox'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const role = ref<string>(localStorage.getItem('role') || '')
  const username = ref<string>(localStorage.getItem('username') || '')
  const department = ref<string>(localStorage.getItem('department') || '')
  const authorizedDepartments = ref<string[]>(JSON.parse(localStorage.getItem('authorized_departments') || '[]'))

  function resetUserWork() {
    useAuditSessionStore().reset()
    useImportInboxStore().reset()
    useBatchStore().reset()
  }

  async function login(user: string, password: string) {
    const res = await loginApi(user, password)
    resetUserWork()
    token.value = res.access_token
    role.value = res.role
    username.value = res.username
    department.value = res.department || ''
    authorizedDepartments.value = res.authorized_departments || [res.department].filter(Boolean)
    localStorage.setItem('token', res.access_token)
    localStorage.setItem('role', res.role)
    localStorage.setItem('username', res.username)
    localStorage.setItem('department', res.department || '')
    localStorage.setItem('authorized_departments', JSON.stringify(authorizedDepartments.value))
  }

  function logout() {
    resetUserWork()
    token.value = ''
    role.value = ''
    username.value = ''
    department.value = ''
    authorizedDepartments.value = []
    localStorage.removeItem('token')
    localStorage.removeItem('role')
    localStorage.removeItem('username')
    localStorage.removeItem('department')
    localStorage.removeItem('authorized_departments')
  }

  function isAuthenticated() {
    return !!token.value
  }

  function hasRole(roles?: string[]) {
    if (!roles || roles.length === 0) return true
    if (role.value === 'admin') return true
    return roles.includes(role.value)
  }

  return {
    token,
    role,
    username,
    department,
    authorizedDepartments,
    login,
    logout,
    isAuthenticated,
    hasRole,
  }
})
