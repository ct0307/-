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
    <button class="theme-trigger" type="button" aria-label="切换外观">
      <el-tooltip content="切换外观" placement="bottom">
        <el-icon><component :is="current.icon" /></el-icon>
      </el-tooltip>
    </button>
    <template #dropdown>
      <el-dropdown-menu class="theme-menu">
        <el-dropdown-item
          v-for="item in options"
          :key="item.value"
          :command="item.value"
          :class="{ 'is-current': mode === item.value }"
        >
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
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--ink-2);
  color: var(--ivory-dim);
  font-size: 17px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
}
.theme-trigger:hover,
.theme-trigger:focus-visible {
  color: var(--brass);
  border-color: var(--line-strong);
  background: var(--ink-3);
}
.theme-check {
  margin-left: auto;
  color: var(--brass);
}
:global(.theme-menu .el-dropdown-menu__item) {
  min-width: 168px;
  gap: 9px;
}
:global(.theme-menu .el-dropdown-menu__item.is-current) {
  color: var(--brass);
  background: var(--brass-soft);
}
</style>
