import { computed, readonly, ref } from 'vue'

export type ThemeMode = 'dossier' | 'light' | 'dark' | 'system'
export type EffectiveTheme = Exclude<ThemeMode, 'system'>

export type ThemePalette = {
  surface: string
  text: string
  textSecondary: string
  muted: string
  line: string
  lineStrong: string
  brass: string
  seal: string
  amber: string
  sage: string
}

export const THEME_STORAGE_KEY = 'qijian-theme-mode'
export const DEFAULT_THEME_MODE: ThemeMode = 'dossier'
export const THEME_MODES: readonly ThemeMode[] = ['dossier', 'light', 'dark', 'system']

type ReadableStorage = Pick<Storage, 'getItem'>

export function isThemeMode(value: unknown): value is ThemeMode {
  return typeof value === 'string' && THEME_MODES.includes(value as ThemeMode)
}

export function readThemeMode(storage: ReadableStorage): ThemeMode {
  try {
    const value = storage.getItem(THEME_STORAGE_KEY)
    return isThemeMode(value) ? value : DEFAULT_THEME_MODE
  } catch {
    return DEFAULT_THEME_MODE
  }
}

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): EffectiveTheme {
  return mode === 'system' ? (prefersDark ? 'dark' : 'light') : mode
}

const mode = ref<ThemeMode>(DEFAULT_THEME_MODE)
const prefersDark = ref(false)
const effectiveTheme = computed(() => resolveTheme(mode.value, prefersDark.value))
let mediaQuery: MediaQueryList | null = null
let initialized = false

function applyTheme() {
  document.documentElement.dataset.theme = effectiveTheme.value
  document.documentElement.style.colorScheme = effectiveTheme.value === 'dark' ? 'dark' : 'light'
}

function onSystemThemeChange(event: MediaQueryListEvent) {
  prefersDark.value = event.matches
  if (mode.value === 'system') applyTheme()
}

export function setThemeMode(nextMode: ThemeMode) {
  mode.value = nextMode
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, nextMode)
  } catch {
    // 存储不可用时仍保留当前会话的主题。
  }
  applyTheme()
}

export function initTheme() {
  if (initialized || typeof window === 'undefined') return
  initialized = true

  try {
    mode.value = readThemeMode(window.localStorage)
  } catch {
    mode.value = DEFAULT_THEME_MODE
  }

  mediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)') ?? null
  prefersDark.value = mediaQuery?.matches ?? false
  mediaQuery?.addEventListener?.('change', onSystemThemeChange)
  applyTheme()
}

export function readThemePalette(): ThemePalette {
  const styles = getComputedStyle(document.documentElement)
  const read = (name: string) => styles.getPropertyValue(name).trim()
  return {
    surface: read('--ink-2'),
    text: read('--ivory'),
    textSecondary: read('--ivory-dim'),
    muted: read('--muted'),
    line: read('--line'),
    lineStrong: read('--line-strong'),
    brass: read('--brass'),
    seal: read('--seal'),
    amber: read('--amber'),
    sage: read('--sage'),
  }
}

export function useTheme() {
  return {
    mode: readonly(mode),
    effectiveTheme: readonly(effectiveTheme),
    setThemeMode,
  }
}
