# 契鉴多主题切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为契鉴增加默认卷宗、企业明亮、深灰审阅和跟随系统四种外观模式，并在浏览器本地持久化用户选择。

**Architecture:** 使用独立的 `theme.ts` 单例模块维护模式、实际主题、系统偏好监听和根元素属性；业务组件只通过 `useTheme()` 读取和切换。全局 `tokens.scss` 根据 `data-theme` 提供三套语义令牌，顶栏组件不直接访问 DOM 或存储。

**Tech Stack:** Vue 3 Composition API、TypeScript、SCSS、Element Plus、Playwright

---

## 文件结构

- Create: `frontend/src/theme/theme.ts`：主题类型、纯解析函数、持久化、系统监听和 DOM 应用。
- Create: `frontend/src/components/layout/ThemeSwitcher.vue`：顶栏外观模式菜单。
- Create: `frontend/tests/theme-mode.spec.ts`：主题模式纯逻辑测试。
- Create: `frontend/tests/theme-switching-e2e.spec.ts`：默认值、切换、刷新保持、系统跟随与移动端测试。
- Modify: `frontend/src/styles/tokens.scss`：共享结构令牌及卷宗、明亮、深灰三套色彩令牌。
- Modify: `frontend/src/main.ts`：Vue 挂载前初始化主题。
- Modify: `frontend/src/components/layout/AppHeader.vue`：挂载主题切换入口。
- Modify: `frontend/src/styles/index.scss`、`element-overrides.scss`：滚动条和表格悬浮色改用主题令牌。
- Modify: `frontend/src/views/LoginView.vue`、`frontend/src/components/audit/AnnotationModal.vue`：移除固定卷宗色。
- Modify: `frontend/src/components/charts/BaseChart.vue`、`TrendLine.vue`、`RiskDonut.vue`、`DeptBar.vue`、`TopRiskBar.vue`：切换主题时重新取色和重绘。

### Task 1: 主题模式核心逻辑

**Files:**
- Create: `frontend/src/theme/theme.ts`
- Create: `frontend/tests/theme-mode.spec.ts`

- [ ] **Step 1: 编写失败的纯逻辑测试**

```ts
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
  expect(isThemeMode('system')).toBe(true)
  expect(isThemeMode('unknown')).toBe(false)

  expect(readThemeMode({ getItem: () => 'dark' })).toBe('dark')
  expect(readThemeMode({ getItem: () => 'unknown' })).toBe('dossier')
  expect(readThemeMode({ getItem: () => { throw new Error('blocked') } })).toBe('dossier')
})

test('system mode resolves from the operating-system preference', () => {
  expect(resolveTheme('dossier', true)).toBe('dossier')
  expect(resolveTheme('light', true)).toBe('light')
  expect(resolveTheme('dark', false)).toBe('dark')
  expect(resolveTheme('system', true)).toBe('dark')
  expect(resolveTheme('system', false)).toBe('light')
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend; npx playwright test tests/theme-mode.spec.ts`

Expected: FAIL，提示无法解析 `../src/theme/theme`。

- [ ] **Step 3: 实现主题状态模块**

```ts
import { computed, readonly, ref } from 'vue'

export type ThemeMode = 'dossier' | 'light' | 'dark' | 'system'
export type EffectiveTheme = Exclude<ThemeMode, 'system'>

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

export function useTheme() {
  return {
    mode: readonly(mode),
    effectiveTheme: readonly(effectiveTheme),
    setThemeMode,
  }
}
```

- [ ] **Step 4: 运行纯逻辑测试确认通过**

Run: `cd frontend; npx playwright test tests/theme-mode.spec.ts`

Expected: `2 passed`。

- [ ] **Step 5: 提交检查点（仅在用户明确要求提交时执行）**

```powershell
git add frontend/src/theme/theme.ts frontend/tests/theme-mode.spec.ts
git commit -m "feat: add theme mode state"
```

### Task 2: 三套语义化设计令牌

**Files:**
- Modify: `frontend/src/styles/tokens.scss`

- [ ] **Step 1: 将结构令牌保留在根作用域**

保留字体、圆角、缓动和 Element Plus 语义映射，三套主题共享以下结构值：

```scss
:root {
  --serif: "Noto Serif SC", "Songti SC", "SimSun", serif;
  --sans: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --mono: "JetBrains Mono", "Cascadia Code", ui-monospace, monospace;
  --r-lg: 8px;
  --r-md: 6px;
  --r-sm: 4px;
  --r-xs: 3px;
  --r-pill: 999px;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);

  --el-color-primary: var(--brass);
  --el-color-danger: var(--seal);
  --el-color-warning: var(--amber);
  --el-color-success: var(--sage);
  --el-bg-color: var(--ink-2);
  --el-bg-color-page: var(--ink);
  --el-bg-color-overlay: var(--ink-2);
  --el-fill-color-blank: var(--ink-2);
  --el-fill-color-light: var(--ink-3);
  --el-text-color-primary: var(--ivory);
  --el-text-color-regular: var(--ivory-dim);
  --el-text-color-secondary: var(--muted);
  --el-text-color-placeholder: var(--muted);
  --el-border-color: var(--line);
  --el-border-color-light: var(--line);
  --el-border-color-lighter: var(--line);
  --el-border-color-hover: var(--line-strong);
}
```

- [ ] **Step 2: 定义默认卷宗主题**

```scss
:root,
:root[data-theme='dossier'] {
  --ink: #f4f1e8;
  --ink-2: #fdfcf8;
  --ink-3: #f5f0e4;
  --line: rgba(58, 50, 34, 0.14);
  --line-strong: rgba(58, 50, 34, 0.26);
  --ivory: #2a3248;
  --ivory-dim: #565e70;
  --muted: #8c8574;
  --seal: #b23a2c;
  --seal-soft: rgba(178, 58, 44, 0.12);
  --brass: #8a6a1c;
  --brass-lite: #b8912f;
  --brass-soft: rgba(138, 106, 28, 0.12);
  --amber: #b0741a;
  --amber-soft: rgba(176, 116, 26, 0.14);
  --sage: #3e7a5c;
  --sage-soft: rgba(62, 122, 92, 0.14);
  --info: #315b72;
  --info-soft: rgba(49, 91, 114, 0.1);
  --shadow: 0 2px 12px rgba(53, 44, 28, 0.09);
  --shadow-sm: 0 1px 6px rgba(53, 44, 28, 0.07);
}
```

- [ ] **Step 3: 定义企业明亮与深灰审阅主题**

```scss
:root[data-theme='light'] {
  --ink: #f2f4f7;
  --ink-2: #ffffff;
  --ink-3: #f7f8fa;
  --line: rgba(32, 40, 56, 0.12);
  --line-strong: rgba(32, 40, 56, 0.24);
  --ivory: #202838;
  --ivory-dim: #475467;
  --muted: #667085;
  --seal: #b42318;
  --seal-soft: rgba(180, 35, 24, 0.09);
  --brass: #8a6a1c;
  --brass-lite: #725716;
  --brass-soft: rgba(138, 106, 28, 0.08);
  --amber: #b54708;
  --amber-soft: rgba(181, 71, 8, 0.09);
  --sage: #137a54;
  --sage-soft: rgba(19, 122, 84, 0.09);
  --info: #315b72;
  --info-soft: rgba(49, 91, 114, 0.09);
  --shadow: 0 12px 32px rgba(16, 24, 40, 0.12);
  --shadow-sm: 0 1px 2px rgba(16, 24, 40, 0.05);
}

:root[data-theme='dark'] {
  --ink: #16181c;
  --ink-2: #202328;
  --ink-3: #282c32;
  --line: rgba(235, 238, 244, 0.12);
  --line-strong: rgba(235, 238, 244, 0.24);
  --ivory: #f2f4f7;
  --ivory-dim: #c2c8d0;
  --muted: #939ba7;
  --seal: #ff756a;
  --seal-soft: rgba(255, 117, 106, 0.12);
  --brass: #c6a75d;
  --brass-lite: #d2b66f;
  --brass-soft: rgba(198, 167, 93, 0.14);
  --amber: #f0a85a;
  --amber-soft: rgba(240, 168, 90, 0.13);
  --sage: #58c799;
  --sage-soft: rgba(88, 199, 153, 0.12);
  --info: #78a7bd;
  --info-soft: rgba(120, 167, 189, 0.12);
  --shadow: 0 16px 36px rgba(0, 0, 0, 0.28);
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.24);
}
```

每个主题块同时定义对应的 `--el-color-*-light-*` 派生色，避免 Element Plus 的按钮、标签和禁用态残留其他主题颜色。

- [ ] **Step 4: 运行类型检查和生产构建**

Run: `cd frontend; npm run type-check`

Expected: exit code 0。

Run: `cd frontend; npm run build`

Expected: exit code 0，Vite 生成 `dist/`。

- [ ] **Step 5: 提交检查点（仅在用户明确要求提交时执行）**

```powershell
git add frontend/src/styles/tokens.scss
git commit -m "style: add dossier light and dark tokens"
```

### Task 3: 消除固定卷宗色并让图表响应主题

**Files:**
- Modify: `frontend/src/styles/index.scss`
- Modify: `frontend/src/styles/element-overrides.scss`
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/components/audit/AnnotationModal.vue`
- Modify: `frontend/src/components/charts/BaseChart.vue`
- Modify: `frontend/src/components/charts/TrendLine.vue`
- Modify: `frontend/src/components/charts/RiskDonut.vue`
- Modify: `frontend/src/components/charts/DeptBar.vue`
- Modify: `frontend/src/components/charts/TopRiskBar.vue`

- [ ] **Step 1: 为主题补充非业务表面令牌**

三套主题分别定义以下变量，并把对应固定色替换为变量：

```scss
--on-brass: #ffffff; // 深灰主题使用 #181a1e
--scroll-thumb: rgba(86, 94, 112, 0.28);
--scroll-thumb-hover: rgba(86, 94, 112, 0.44);
--brass-hover-soft: rgba(138, 106, 28, 0.05);
--login-glow: #f3eee0;
--seal-watermark: rgba(178, 58, 44, 0.05);
--seal-panel-soft: rgba(178, 58, 44, 0.08);
--paper-line: rgba(58, 50, 34, 0.07);
--annotation-highlight: rgba(176, 116, 26, 0.4);
```

深灰主题的 `--login-glow` 使用 `#24272d`，水印、纸张线和批注高亮使用对应的浅色透明值。`KnowledgeView.vue` 与 `RectifyView.vue` 中黄铜实底按钮文字改为 `var(--on-brass)`。

- [ ] **Step 2: 新增主题色读取函数**

在 `frontend/src/theme/theme.ts` 增加：

```ts
export type ThemePalette = {
  text: string
  textSecondary: string
  muted: string
  line: string
  brass: string
  seal: string
  amber: string
  sage: string
}

export function readThemePalette(): ThemePalette {
  const styles = getComputedStyle(document.documentElement)
  const read = (name: string) => styles.getPropertyValue(name).trim()
  return {
    text: read('--ivory'),
    textSecondary: read('--ivory-dim'),
    muted: read('--muted'),
    line: read('--line-strong'),
    brass: read('--brass'),
    seal: read('--seal'),
    amber: read('--amber'),
    sage: read('--sage'),
  }
}
```

- [ ] **Step 3: 让基础图表在主题变化时重建**

`BaseChart.vue` 导入 `nextTick`、`useTheme`，把固定 `juanzong` 主题初始化改为无固定主题初始化：

```ts
const { effectiveTheme } = useTheme()

function initChart() {
  chart?.dispose()
  chart = echarts.init(el.value!)
  chart.setOption(props.option, true)
}

watch(effectiveTheme, async () => {
  await nextTick()
  initChart()
}, { flush: 'post' })
```

保留现有尺寸监听和 option 监听；删除固定 `echarts.registerTheme('juanzong', ...)` 及 `echarts.init(el.value, 'juanzong')`。

- [ ] **Step 4: 让四个报表 option 重新读取主题色**

四个图表组件均改为 `computed<EChartsCoreOption>`，在 computed 内读取 `effectiveTheme.value` 建立响应依赖，再调用 `readThemePalette()`。轴线、分隔线、图例、标签和系列颜色分别使用 `palette.line`、`palette.muted`、`palette.textSecondary`、`palette.brass`、`palette.seal`、`palette.amber`、`palette.sage`；删除文件中的固定十六进制卷宗色。

示例结构：

```ts
const { effectiveTheme } = useTheme()
const option = computed<EChartsCoreOption>(() => {
  effectiveTheme.value
  const palette = readThemePalette()
  return {
    textStyle: { color: palette.textSecondary },
    color: [palette.brass, palette.sage, palette.seal],
  }
})
```

`RiskDonut.vue` 的高、中、低风险数据项依次使用 `palette.seal`、`palette.amber`、`palette.sage`。

- [ ] **Step 5: 检查固定色残留并构建**

Run: `rg -n "#8a6a1c|#b23a2c|#b0741a|#3e7a5c|#565e70|#8c8574|rgba\(58,50,34" frontend/src/components/charts`

Expected: 无输出。

Run: `cd frontend; npm run build`

Expected: exit code 0。

- [ ] **Step 6: 提交检查点（仅在用户明确要求提交时执行）**

```powershell
git add frontend/src/theme/theme.ts frontend/src/styles frontend/src/views/LoginView.vue frontend/src/views/KnowledgeView.vue frontend/src/views/RectifyView.vue frontend/src/components/audit/AnnotationModal.vue frontend/src/components/charts
git commit -m "fix: make themed surfaces and charts adaptive"
```

### Task 4: 顶栏主题选择器

**Files:**
- Create: `frontend/src/components/layout/ThemeSwitcher.vue`
- Modify: `frontend/src/components/layout/AppHeader.vue`

- [ ] **Step 1: 创建主题选择组件**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { Check, Monitor, Moon, Sunny, Tickets } from '@element-plus/icons-vue'
import { useTheme, type ThemeMode } from '@/theme/theme'

const { mode, setThemeMode } = useTheme()
const options = [
  { value: 'dossier' as const, label: '卷宗主题', icon: Tickets },
  { value: 'light' as const, label: '企业明亮', icon: Sunny },
  { value: 'dark' as const, label: '深灰审阅', icon: Moon },
  { value: 'system' as const, label: '跟随系统', icon: Monitor },
]
const current = computed(() => options.find((item) => item.value === mode.value) ?? options[0])

function selectTheme(value: ThemeMode) {
  setThemeMode(value)
}
</script>

<template>
  <el-dropdown trigger="click" placement="bottom-end" @command="selectTheme">
    <el-tooltip content="切换外观" placement="bottom">
      <button class="theme-trigger" type="button" aria-label="切换外观">
        <el-icon><component :is="current.icon" /></el-icon>
      </button>
    </el-tooltip>
    <template #dropdown>
      <el-dropdown-menu class="theme-menu">
        <el-dropdown-item v-for="item in options" :key="item.value" :command="item.value">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <el-icon v-if="mode === item.value" class="theme-check"><Check /></el-icon>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.theme-trigger {
  width: 38px;
  height: 38px;
  display: inline-grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--ink-2);
  color: var(--ivory-dim);
  cursor: pointer;
}
.theme-trigger:hover {
  color: var(--brass);
  border-color: var(--line-strong);
  background: var(--ink-3);
}
.theme-check {
  margin-left: auto;
  color: var(--brass);
}
</style>
```

- [ ] **Step 2: 在顶栏通知按钮前挂载入口**

```vue
<script setup lang="ts">
import ThemeSwitcher from './ThemeSwitcher.vue'
</script>

<div class="topbar-actions">
  <slot />
  <ThemeSwitcher />
  <NotifyBell />
</div>
```

- [ ] **Step 3: 运行类型检查**

Run: `cd frontend; npm run type-check`

Expected: exit code 0；`Check`、`Monitor`、`Moon`、`Sunny`、`Tickets` 已通过当前依赖导出检查。

- [ ] **Step 4: 提交检查点（仅在用户明确要求提交时执行）**

```powershell
git add frontend/src/components/layout/ThemeSwitcher.vue frontend/src/components/layout/AppHeader.vue
git commit -m "feat: add theme switcher to app header"
```

### Task 5: 启动初始化与浏览器回归测试

**Files:**
- Modify: `frontend/src/main.ts`
- Create: `frontend/tests/theme-switching-e2e.spec.ts`

- [ ] **Step 1: 在应用挂载前初始化主题**

```ts
import { initTheme } from './theme/theme'

initTheme()
const app = createApp(App)
```

`initTheme()` 必须位于 `createApp(App)` 和 `app.mount('#app')` 之前。

- [ ] **Step 2: 编写端到端测试**

```ts
import { expect, test } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL
test.skip(!baseUrl, '需要显式启动 backend 和 frontend 后设置 E2E_BASE_URL')

async function login(page: import('@playwright/test').Page) {
  await page.goto(`${baseUrl}/login`)
  await page.locator('input[name="username"]').fill('admin')
  await page.locator('input[name="password"]').fill('admin123')
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
}

async function chooseTheme(page: import('@playwright/test').Page, label: string) {
  await page.getByRole('button', { name: '切换外观' }).click()
  await page.getByRole('menuitem', { name: new RegExp(label) }).click()
}

test('defaults to dossier and persists a manual theme', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('qijian-theme-mode'))
  await login(page)
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dossier')

  await chooseTheme(page, '深灰审阅')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect.poll(() => page.evaluate(() => localStorage.getItem('qijian-theme-mode'))).toBe('dark')

  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('system mode follows color scheme without horizontal overflow', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await login(page)
  await chooseTheme(page, '跟随系统')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '切换外观' }).click()
  await expect(page.getByRole('menuitem', { name: /卷宗主题/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})
```

- [ ] **Step 3: 运行主题专项测试**

Run: `$env:E2E_BASE_URL='http://127.0.0.1:5173'; npx playwright test tests/theme-mode.spec.ts tests/theme-switching-e2e.spec.ts`

Expected: `4 passed`。

- [ ] **Step 4: 提交检查点（仅在用户明确要求提交时执行）**

```powershell
git add frontend/src/main.ts frontend/tests/theme-switching-e2e.spec.ts
git commit -m "test: cover theme switching workflows"
```

### Task 6: 完整验证与视觉验收

**Files:**
- Verify: `frontend/src/styles/tokens.scss`
- Verify: `frontend/src/components/layout/ThemeSwitcher.vue`
- Verify: `frontend/src/theme/theme.ts`

- [ ] **Step 1: 运行静态验证**

Run: `cd frontend; npm run type-check`

Expected: exit code 0。

Run: `cd frontend; npm run build`

Expected: exit code 0。

- [ ] **Step 2: 运行完整测试套件**

Run: `$env:E2E_BASE_URL='http://127.0.0.1:5173'; npm test`

Expected: 原 15 条及新增 4 条测试全部通过。

- [ ] **Step 3: 应用内浏览器验证三套主题**

在 `http://127.0.0.1:5173/audit` 和 `/knowledge` 依次验证：

- 1440x900：卷宗、企业明亮、深灰审阅各切换一次，页面身份与主内容正确。
- 1920x1080：审查工作台无异常留白、重叠和横向溢出。
- 390x844：主题入口可见、菜单不超出视口、侧栏和风险抽屉不重叠。
- 全新标签页 Console 无相关 warning/error。
- 风险红、预警琥珀、合规绿在三套主题中含义一致且文字可读。

- [ ] **Step 4: 检查工作区差异**

Run: `git diff --check`

Expected: exit code 0，仅允许 Windows 行尾提示。

Run: `git status --short`

Expected: 只出现本功能与此前已确认的前端改动；`outputs/` 保持未跟踪且不处理。

- [ ] **Step 5: 提交最终结果（仅在用户明确要求提交时执行）**

```powershell
git add frontend/src/theme frontend/src/components/layout/ThemeSwitcher.vue frontend/src/components/layout/AppHeader.vue frontend/src/styles/tokens.scss frontend/src/main.ts frontend/tests/theme-mode.spec.ts frontend/tests/theme-switching-e2e.spec.ts docs/superpowers/specs/2026-07-31-theme-switching-design.md docs/superpowers/plans/2026-07-31-theme-switching.md
git commit -m "feat: add persistent multi-theme appearance modes"
```
