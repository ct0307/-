import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login as loginApi } from '@/api/contract'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const role = ref<string>(localStorage.getItem('role') || '')
  const username = ref<string>(localStorage.getItem('username') || '')

  async function login(user: string, password: string) {
    const res = await loginApi(user, password)
    token.value = res.access_token
    role.value = res.role
    username.value = res.username
    localStorage.setItem('token', res.access_token)
    localStorage.setItem('role', res.role)
    localStorage.setItem('username', res.username)
  }

  function logout() {
    token.value = ''
    role.value = ''
    username.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('role')
    localStorage.removeItem('username')
  }

  function isAuthenticated() {
    return !!token.value
  }

  function hasRole(roles?: string[]) {
    if (!roles || roles.length === 0) return true
    if (role.value === 'admin') return true
    return roles.includes(role.value)
  }

  return { token, role, username, login, logout, isAuthenticated, hasRole }
})
