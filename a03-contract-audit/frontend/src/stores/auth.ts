import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login as loginApi } from '@/api/contract'
import { useAuditSessionStore } from '@/stores/audit-session'
import { useBatchStore } from '@/stores/batch'
import { useImportInboxStore } from '@/stores/import-inbox'
import { clearSessionStorage, SESSION_KEYS } from '@/utils/session'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(SESSION_KEYS.token) || '')
  const role = ref<string>(localStorage.getItem(SESSION_KEYS.role) || '')
  const username = ref<string>(localStorage.getItem(SESSION_KEYS.username) || '')
  const department = ref<string>(localStorage.getItem(SESSION_KEYS.department) || '')
  const authorizedDepartments = ref<string[]>(
    JSON.parse(localStorage.getItem(SESSION_KEYS.authorizedDepartments) || '[]'),
  )

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
    localStorage.setItem(SESSION_KEYS.token, res.access_token)
    localStorage.setItem(SESSION_KEYS.role, res.role)
    localStorage.setItem(SESSION_KEYS.username, res.username)
    localStorage.setItem(SESSION_KEYS.department, res.department || '')
    localStorage.setItem(SESSION_KEYS.authorizedDepartments, JSON.stringify(authorizedDepartments.value))
  }

  function logout() {
    resetUserWork()
    token.value = ''
    role.value = ''
    username.value = ''
    department.value = ''
    authorizedDepartments.value = []
    clearSessionStorage()
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
