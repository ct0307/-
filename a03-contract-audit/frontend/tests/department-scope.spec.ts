import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'


const typeSource = readFileSync(
  fileURLToPath(new URL('../src/api/types.ts', import.meta.url)),
  'utf8',
)
const authSource = readFileSync(
  fileURLToPath(new URL('../src/stores/auth.ts', import.meta.url)),
  'utf8',
)
const adminApiSource = readFileSync(
  fileURLToPath(new URL('../src/api/admin.ts', import.meta.url)),
  'utf8',
)


test('keeps authorized departments in the login context', () => {
  expect(typeSource).toContain('authorized_departments: string[]')
  expect(authSource).toContain('const authorizedDepartments = ref<string[]>')
  expect(authSource).toContain("localStorage.setItem('authorized_departments'")
  expect(authSource).toContain('authorizedDepartments,')
})


test('defines the minimal department scope admin api', () => {
  expect(adminApiSource).toContain('export interface DepartmentScopeUser')
  expect(adminApiSource).toContain('export function getDepartmentScopeUsers')
  expect(adminApiSource).toContain('export function updateUserDepartments')
})
