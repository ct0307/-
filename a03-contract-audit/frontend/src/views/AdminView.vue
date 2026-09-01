<script setup lang="ts">
// 权限与审计（仅 admin）：角色权限矩阵 + 操作审计日志 + LLM 调用记录。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAccessMatrix, getAuditLogs, getLlmCalls, getLookups, createLookup, deleteLookup } from '@/api/admin'
import type { AccessRole, AuditLogRow, LlmCallRow, Perm } from '@/mock/admin'
import type { LookupItem } from '@/api/admin'
import DemoBadge from '@/components/common/DemoBadge.vue'

const modules = ref<string[]>([])
const roles = ref<AccessRole[]>([])
const logs = ref<AuditLogRow[]>([])
const llmCalls = ref<LlmCallRow[]>([])
const loading = ref(false)
const loadError = ref('')
const activeTab = ref('matrix')
const keyword = ref('')
const logDateRange = ref<[Date, Date] | null>(null)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [matrix, logRows, callRows] = await Promise.all([
      getAccessMatrix(),
      getAuditLogs(),
      getLlmCalls(),
    ])
    modules.value = matrix.modules
    roles.value = matrix.roles
    logs.value = logRows
    llmCalls.value = callRows
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '权限与审计数据加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(() => { load(); loadLookups() })

const filteredLogs = computed(() => {
  const kw = keyword.value.trim()
  const [from, to] = logDateRange.value ?? [null, null]
  return logs.value.filter((l) => {
    const kwOk = !kw || l.action.includes(kw) || l.user.includes(kw)
    const dateOk = !from || !to || (l.time >= from.toISOString().slice(0, 10) && l.time <= to.toISOString().slice(0, 10))
    return kwOk && dateOk
  })
})
const logPage = ref(1)
const logPageSize = 20

const permMeta: Record<Perm, { color: string; bg: string }> = {
  读写: { color: 'var(--sage)', bg: 'var(--sage-soft)' },
  只读: { color: 'var(--amber)', bg: 'var(--amber-soft)' },
  无: { color: 'var(--muted)', bg: 'var(--ink-3)' },
}

// provider 样式：openclaw 金色（快速算力）、deepseek 蓝色、qwen 绿色
const providerMeta: Record<string, { label: string; color: string }> = {
  openclaw: { label: 'OpenClaw', color: 'var(--brass)' },
  deepseek: { label: 'DeepSeek', color: '#4C9EEB' },
  qwen:     { label: 'Qwen',     color: 'var(--sage)' },
}
function providerStyle(p: string) {
  const m = providerMeta[p] ?? { label: p, color: 'var(--muted)' }
  return { color: m.color, label: m.label }
}

// 延迟分级着色：openclaw < 2s绿、5s 内黄、超过5s 橙红
function latencyColor(ms: number): string {
  if (ms < 2000) return 'var(--sage)'
  if (ms < 5000) return 'var(--amber)'
  return 'var(--seal)'
}

// agent 标签
const agentLabel: Record<string, string> = { legal: '法务', finance: '财务' }

// LLM 调用统计（竞赛可解释性核心）
const llmStats = computed(() => {
  const calls = llmCalls.value.filter((c) => c.mode === 'llm')
  if (!calls.length) return null
  const byProvider: Record<string, { count: number; totalLatency: number; totalTokens: number }> = {}
  for (const c of calls) {
    if (!byProvider[c.provider]) byProvider[c.provider] = { count: 0, totalLatency: 0, totalTokens: 0 }
    byProvider[c.provider].count++
    byProvider[c.provider].totalLatency += c.latency_ms
    byProvider[c.provider].totalTokens += c.prompt_tokens + c.completion_tokens
  }
  return Object.entries(byProvider).map(([p, v]) => ({
    provider: p,
    count: v.count,
    avgLatency: Math.round(v.totalLatency / v.count),
    avgTokens: Math.round(v.totalTokens / v.count),
  }))
})

// ── 基础配置：部门 & 合同类型增删 ──
const depts = ref<LookupItem[]>([])
const ctypes = ref<LookupItem[]>([])
const newDept = ref('')
const newCtype = ref('')
const lookupLoading = ref(false)

async function loadLookups() {
  lookupLoading.value = true
  try {
    const [d, c] = await Promise.all([getLookups('department'), getLookups('contract_type')])
    depts.value = d
    ctypes.value = c
  } finally {
    lookupLoading.value = false
  }
}

async function addLookup(category: 'department' | 'contract_type') {
  const val = category === 'department' ? newDept.value.trim() : newCtype.value.trim()
  if (!val) return
  try {
    const item = await createLookup(category, val)
    if (category === 'department') { depts.value.push(item); newDept.value = '' }
    else { ctypes.value.push(item); newCtype.value = '' }
    ElMessage.success('已添加')
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(msg ?? '添加失败')
  }
}

async function removeLookup(category: 'department' | 'contract_type', id: number, value: string) {
  await ElMessageBox.confirm(`确认删除「${value}」？`, '删除确认', {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
  })
  try {
    await deleteLookup(id)
    if (category === 'department') depts.value = depts.value.filter((i) => i.id !== id)
    else ctypes.value = ctypes.value.filter((i) => i.id !== id)
    ElMessage.success('已删除')
  } catch {
    ElMessage.error('删除失败')
  }
}

// 导出审计日志 CSV
function exportCsv() {
  const header = ['编号', '用户', '角色', '操作', '对象', '时间', 'IP']
  const lines = filteredLogs.value.map((l) =>
    [l.id, l.user, l.role, l.action, l.target, l.time, l.ip].join(','),
  )
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
      <DemoBadge module="admin" />
      <el-button
        v-if="activeTab === 'logs'"
        :icon="'Download'"
        @click="exportCsv"
      >导出审计日志</el-button>
    </div>

    <!-- 加载失败内联错误块（统一 el-result 风格） -->
    <el-result
      v-if="loadError"
      icon="error"
      title="加载失败"
      :sub-title="loadError"
    >
      <template #extra>
        <el-button type="primary" @click="load">重新加载</el-button>
      </template>
    </el-result>

    <el-tabs v-else v-model="activeTab" class="admin-tabs">
      <!-- ── Tab 1：角色权限配置 ── -->
      <el-tab-pane label="角色权限配置" name="matrix">
        <el-card shadow="never">
          <template #header>
            <div class="panel-head">
              <span>RBAC 权限矩阵</span>
              <el-tag size="small" type="info">{{ roles.length }} 个角色 × {{ modules.length }} 个模块</el-tag>
            </div>
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
                  <span
                    class="perm"
                    :style="{ color: permMeta[r.perms[i] as Perm]?.color, background: permMeta[r.perms[i] as Perm]?.bg }"
                  >{{ r.perms[i] }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </el-card>
      </el-tab-pane>

      <!-- ── Tab 2：操作审计日志 ── -->
      <el-tab-pane label="操作审计日志" name="logs">
        <el-card shadow="never">
          <template #header>
            <div class="panel-head">
              <span>操作审计日志</span>
              <div class="log-filters">
                <!-- AD1：时间范围筛选 -->
                <el-date-picker
                  v-model="logDateRange"
                  type="daterange"
                  range-separator="至"
                  start-placeholder="开始日期"
                  end-placeholder="结束日期"
                  size="small"
                  style="width: 240px"
                  clearable
                  @change="logPage = 1"
                />
                <el-input
                  v-model="keyword"
                  placeholder="搜索操作 / 用户"
                  :prefix-icon="'Search'"
                  size="small"
                  style="width: 180px"
                  clearable
                  @input="logPage = 1"
                />
              </div>
            </div>
          </template>
          <el-table :data="filteredLogs.slice((logPage - 1) * logPageSize, logPage * logPageSize)" style="width: 100%" empty-text="无匹配日志" size="small">
            <el-table-column prop="time" label="时间" width="150">
              <template #default="{ row }"><span class="mono">{{ row.time }}</span></template>
            </el-table-column>
            <el-table-column label="用户" width="130">
              <template #default="{ row }">
                {{ row.user }}<small class="role-sm">{{ row.role }}</small>
              </template>
            </el-table-column>
            <el-table-column prop="action" label="操作" min-width="160" />
            <el-table-column prop="target" label="对象" width="130">
              <template #default="{ row }"><span class="mono">{{ row.target }}</span></template>
            </el-table-column>
            <el-table-column prop="ip" label="IP" width="120">
              <template #default="{ row }"><span class="mono">{{ row.ip }}</span></template>
            </el-table-column>
          </el-table>
          <!-- AD2：分页 -->
          <div v-if="filteredLogs.length > logPageSize" class="log-pagination">
            <el-pagination
              v-model:current-page="logPage"
              :page-size="logPageSize"
              :total="filteredLogs.length"
              layout="prev, pager, next, total"
              background
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ── Tab 3：LLM 调用记录 ── -->
      <el-tab-pane name="llm">
        <template #label>
          <span>LLM 调用记录</span>
          <el-badge v-if="llmCalls.length" :value="llmCalls.length" class="tab-badge" />
        </template>
        <!-- 算力对比统计卡 -->
        <div v-if="llmStats && llmStats.length" class="llm-stats">
          <article v-for="s in llmStats" :key="s.provider" class="stat-card">
            <span class="stat-provider" :style="{ color: providerStyle(s.provider).color }">
              {{ providerStyle(s.provider).label }}
            </span>
            <div class="stat-row">
              <span class="stat-item">
                <em>{{ s.count }}</em> 次调用
              </span>
              <span class="stat-item">
                均延迟 <em :style="{ color: latencyColor(s.avgLatency) }">{{ (s.avgLatency / 1000).toFixed(1) }}s</em>
              </span>
              <span class="stat-item">
                均 Token <em>{{ s.avgTokens.toLocaleString() }}</em>
              </span>
            </div>
          </article>
        </div>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header>
            <div class="panel-head">
              <span>调用明细</span>
              <span class="count mono">{{ llmCalls.length }} 条</span>
            </div>
          </template>
          <el-empty v-if="!llmCalls.length" description="暂无调用记录，触发合同审查后自动写入" />
          <el-table v-else :data="llmCalls" style="width: 100%" size="small">
            <el-table-column prop="time" label="时间" width="145">
              <template #default="{ row }"><span class="mono">{{ row.time }}</span></template>
            </el-table-column>
            <el-table-column label="Agent" width="80">
              <template #default="{ row }">
                <el-tag :type="row.agent === 'legal' ? 'warning' : 'success'" size="small" effect="plain">
                  {{ agentLabel[row.agent] ?? row.agent }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="模型" min-width="140">
              <template #default="{ row }">
                <span class="provider-tag" :style="{ color: providerStyle(row.provider).color }">
                  {{ providerStyle(row.provider).label }}
                </span>
                <span class="mono model-name">{{ row.model }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Token 用量" width="130" align="right">
              <template #default="{ row }">
                <span class="mono">{{ row.prompt_tokens }}<small class="dim">+</small>{{ row.completion_tokens }}</span>
              </template>
            </el-table-column>
            <el-table-column label="延迟" width="90" align="right">
              <template #default="{ row }">
                <span class="mono" :style="{ color: latencyColor(row.latency_ms) }">
                  {{ (row.latency_ms / 1000).toFixed(1) }}s
                </span>
              </template>
            </el-table-column>
            <el-table-column label="合同" width="90" align="center">
              <template #default="{ row }">
                <span v-if="row.contract_id" class="mono dim">C{{ String(row.contract_id).padStart(4, '0') }}</span>
                <span v-else class="dim">—</span>
              </template>
            </el-table-column>
            <el-table-column label="模式" width="70" align="center">
              <template #default="{ row }">
                <el-tag :type="row.mode === 'llm' ? 'primary' : 'info'" size="small" effect="plain">
                  {{ row.mode }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
      <!-- ── Tab 4：基础配置 ── -->
      <el-tab-pane label="基础配置" name="config">
        <div class="config-grid" v-loading="lookupLoading">
          <!-- 业务部门 -->
          <el-card shadow="never">
            <template #header>
              <div class="panel-head">
                <span>业务部门</span>
                <el-tag size="small" type="info">{{ depts.length }} 项</el-tag>
              </div>
            </template>
            <div class="lookup-add">
              <el-input v-model="newDept" placeholder="输入部门名称" clearable @keyup.enter="addLookup('department')" />
              <el-button type="primary" :icon="'Plus'" @click="addLookup('department')">添加</el-button>
            </div>
            <el-empty v-if="!depts.length" description="暂无部门，点击添加" />
            <ul v-else class="lookup-list">
              <li v-for="item in depts" :key="item.id" class="lookup-item">
                <span>{{ item.value }}</span>
                <el-button
                  type="danger" size="small" :icon="'Delete'" circle plain
                  @click="removeLookup('department', item.id, item.value)"
                />
              </li>
            </ul>
          </el-card>

          <!-- 合同类型 -->
          <el-card shadow="never">
            <template #header>
              <div class="panel-head">
                <span>合同类型</span>
                <el-tag size="small" type="info">{{ ctypes.length }} 项</el-tag>
              </div>
            </template>
            <div class="lookup-add">
              <el-input v-model="newCtype" placeholder="输入合同类型" clearable @keyup.enter="addLookup('contract_type')" />
              <el-button type="primary" :icon="'Plus'" @click="addLookup('contract_type')">添加</el-button>
            </div>
            <el-empty v-if="!ctypes.length" description="暂无类型，点击添加" />
            <ul v-else class="lookup-list">
              <li v-for="item in ctypes" :key="item.id" class="lookup-item">
                <span>{{ item.value }}</span>
                <el-button
                  type="danger" size="small" :icon="'Delete'" circle plain
                  @click="removeLookup('contract_type', item.id, item.value)"
                />
              </li>
            </ul>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.admin-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.count { font-size: 12px; color: var(--muted); }
.tab-badge { margin-left: 6px; }
/* 权限矩阵 */
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
  border-radius: var(--r-xs);
  font-size: 12px;
  font-family: var(--mono);
}
/* 审计日志 */
.role-sm {
  display: block;
  font-size: 11px;
  color: var(--muted);
}
/* LLM 调用统计 */
.llm-stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 4px;
}
.stat-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: 14px 18px;
}
.stat-provider {
  font-size: 15px;
  font-weight: 600;
  font-family: var(--mono);
}
.stat-row {
  display: flex;
  gap: 12px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.stat-item {
  font-size: 12px;
  color: var(--ivory-dim);
}
.stat-item em {
  font-style: normal;
  font-weight: 600;
  color: var(--ivory);
}
/* 调用明细表 */
.provider-tag {
  font-size: 11px;
  font-family: var(--mono);
  font-weight: 600;
  margin-right: 6px;
}
.model-name {
  font-size: 11px;
  color: var(--muted);
}
.dim { color: var(--muted); font-size: 11px; }
.log-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.log-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
/* 基础配置 */
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.lookup-add {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}
.lookup-add .el-input { flex: 1; }
.lookup-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lookup-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  background: var(--ink-3);
  border-radius: var(--r-sm);
  font-size: 13px;
  color: var(--ivory);
}
@media (max-width: 1180px) {
  .llm-stats { grid-template-columns: 1fr 1fr; }
  .config-grid { grid-template-columns: 1fr; }
}
</style>
