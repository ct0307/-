<script setup lang="ts">
// 权限与审计（仅 admin）：角色权限矩阵 + 操作审计日志 + 导出 CSV。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAccessMatrix, getAuditLogs } from '@/api/admin'
import type { AccessRole, AuditLogRow, Perm } from '@/mock/admin'
import DemoBadge from '@/components/common/DemoBadge.vue'

const modules = ref<string[]>([])
const roles = ref<AccessRole[]>([])
const logs = ref<AuditLogRow[]>([])
const loading = ref(false)
const keyword = ref('')

async function load() {
  loading.value = true
  try {
    const [matrix, logRows] = await Promise.all([getAccessMatrix(), getAuditLogs()])
    modules.value = matrix.modules
    roles.value = matrix.roles
    logs.value = logRows
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const filteredLogs = computed(() => {
  const kw = keyword.value.trim()
  return logs.value.filter((l) => !kw || l.action.includes(kw) || l.user.includes(kw))
})

const permMeta: Record<Perm, { color: string; bg: string }> = {
  读写: { color: 'var(--sage)', bg: 'var(--sage-soft)' },
  只读: { color: 'var(--amber)', bg: 'var(--amber-soft)' },
  无: { color: 'var(--muted)', bg: 'var(--ink-3)' },
}

// 导出 CSV（前端 Blob 下载）
function exportCsv() {
  const header = ['编号', '用户', '角色', '操作', '对象', '时间', 'IP']
  const lines = filteredLogs.value.map((l) => [l.id, l.user, l.role, l.action, l.target, l.time, l.ip].join(','))
  const csv = '﻿' + [header.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `审计日志_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出 CSV')
}
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <DemoBadge />
      <el-button :icon="'Download'" @click="exportCsv">导出审计日志</el-button>
    </div>

    <div class="admin-grid">
      <el-card shadow="never">
        <template #header>
          <div class="panel-head"><span>角色权限配置</span><el-tag size="small">RBAC</el-tag></div>
        </template>
        <table class="access-table">
          <thead>
            <tr>
              <th>模块 / 角色</th>
              <th v-for="r in roles" :key="r.key">{{ r.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(mod, i) in modules" :key="mod">
              <td class="mod-name">{{ mod }}</td>
              <td v-for="r in roles" :key="r.key">
                <span class="perm" :style="{ color: permMeta[r.perms[i]].color, background: permMeta[r.perms[i]].bg }">
                  {{ r.perms[i] }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="panel-head">
            <span>操作审计日志</span>
            <el-input v-model="keyword" placeholder="搜索操作 / 用户" :prefix-icon="'Search'" size="small" style="width: 180px" clearable />
          </div>
        </template>
        <el-table :data="filteredLogs" style="width: 100%" empty-text="无匹配日志" size="small">
          <el-table-column prop="time" label="时间" width="150">
            <template #default="{ row }"><span class="mono">{{ row.time }}</span></template>
          </el-table-column>
          <el-table-column label="用户" width="130">
            <template #default="{ row }">{{ row.user }}<small class="role-sm">{{ row.role }}</small></template>
          </el-table-column>
          <el-table-column prop="action" label="操作" min-width="140" />
          <el-table-column prop="target" label="对象" width="120">
            <template #default="{ row }"><span class="mono">{{ row.target }}</span></template>
          </el-table-column>
          <el-table-column prop="ip" label="IP" width="120">
            <template #default="{ row }"><span class="mono">{{ row.ip }}</span></template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.admin-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.access-table {
  width: 100%;
  border-collapse: collapse;
}
.access-table th,
.access-table td {
  padding: 10px 14px;
  text-align: center;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
}
.access-table th {
  color: var(--ivory);
  font-family: var(--serif);
  background: var(--ink-3);
}
.access-table th:first-child,
.mod-name {
  text-align: left;
  color: var(--ivory-dim);
}
.perm {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--mono);
}
.role-sm {
  display: block;
  font-size: 11px;
  color: var(--muted);
}
</style>
