import { expect, test } from '@playwright/test'
import {
  DEFAULT_THEME_MODE,
  isThemeMode,
  readThemeMode,
  resolveTheme,
} from '../src/theme/theme'

test('theme mode defaults to dossier and validates persisted values', () => {
  expect(DEFAULT_THEME_MODE).toBe('dossier')
  expect(isThemeMode('dossier')).toBe(true)
  expect(isThemeMode('light')).toBe(true)
  expect(isThemeMode('dark')).toBe(true)
  expect(isThemeMode('system')).toBe(true)
  expect(isThemeMode('unknown')).toBe(false)

  expect(readThemeMode({ getItem: () => 'dark' })).toBe('dark')
  expect(readThemeMode({ getItem: () => 'unknown' })).toBe('dossier')
  expect(readThemeMode({ getItem: () => null })).toBe('dossier')
  expect(readThemeMode({ getItem: () => { throw new Error('blocked') } })).toBe('dossier')
})

test('system mode resolves from the operating-system preference', () => {
  expect(resolveTheme('dossier', true)).toBe('dossier')
  expect(resolveTheme('light', true)).toBe('light')
  expect(resolveTheme('dark', false)).toBe('dark')
  expect(resolveTheme('system', true)).toBe('dark')
  expect(resolveTheme('system', false)).toBe('light')
})
