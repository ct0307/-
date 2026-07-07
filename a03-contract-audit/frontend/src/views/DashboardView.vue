<script setup lang="ts">
// 工作台首页：KPI 卡（真实 summary + store 派生）+ 待办（随演示视角变）+ 快捷入口 + 近期动态。
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useRectifyStore } from '@/stores/rectify'
import { useAuditSessionStore } from '@/stores/audit-session'
import { useDemoStore, type ViewRole } from '@/stores/demo'
import { getDashboardSummary } from '@/api/dashboard'
import type { DashboardSummary } from '@/mock/dashboard'
import DemoBadge from '@/components/common/DemoBadge.vue'

const router = useRouter()
const rectify = useRectifyStore()
const session = useAuditSessionStore()
const demo = useDemoStore()

// 后端看板聚合：总量/复核状态分布等
const summary = ref<DashboardSummary | null>(null)
const loading = ref(true)
const error = ref('')

async function loadSummary() {
  loading.value = true
  error.value = ''
  try {
    summary.value = await getDashboardSummary()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '看板数据加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(loadSummary)

// 合规通过率：已确认 / 总复核数（近似），无数据回退 0
const passRate = computed(() => {
  const rs = summary.value?.review_status
  if (!rs) return '—'
  const total = Object.values(rs).reduce((a, b) => a + b, 0)
  if (!total) return '0'
  const passed = (rs['已确认'] ?? 0) + (rs['已忽略'] ?? 0)
  return String(Math.round((passed / total) * 1000) / 10)
})

// KPI：审查合同/检出风险来自真实 summary，待整改项从 store 实时派生（体现联动）
const kpis = computed(() => [
  { label: '累计审查合同', value: String(summary.value?.total_contracts ?? '—'), unit: '份', trend: '累计', up: true },
  { label: '待整改项', value: String(rectify.openCount), unit: '项', trend: '实时', up: false },
  { label: '累计检出风险', value: String(summary.value?.total_risks ?? '—'), unit: '条', trend: '累计', up: false },
  { label: '合规通过率', value: passRate.value, unit: '%', trend: '复核派生', up: true },
])

// 待办随演示视角切换
const todoByRole: Record<ViewRole, { title: string; level: string; time: string }[]> = {
  legal: [
    { title: '复核「软件开发外包合同」高风险条款', level: 'high', time: '今天 14:00' },
    { title: '确认争议解决条款整改结果', level: 'medium', time: '今天 16:30' },
    { title: '审阅采购合同违约责任补充', level: 'medium', time: '明天 10:00' },
    { title: '归档已闭环整改台账', level: 'low', time: '本周内' },
  ],
  finance: [
    { title: '对账「采购合同」付款节点', level: 'high', time: '今天 15:00' },
    { title: '核查合同金额币种标注', level: 'medium', time: '今天 17:00' },
    { title: '汇总本月涉及金额报表', level: 'low', time: '明天' },
    { title: '预算偏差项复核', level: 'medium', time: '本周内' },
  ],
  admin: [
    { title: '审批新增审查规则申请', level: 'medium', time: '今天' },
    { title: '巡检操作审计日志异常', level: 'high', time: '今天' },
    { title: '维护角色权限矩阵', level: 'low', time: '本周内' },
    { title: '导出系统运行月报', level: 'low', time: '月底' },
  ],
}
const todos = computed(() => todoByRole[demo.viewRole])

const levelColor: Record<string, string> = {
  high: 'var(--seal)',
  medium: 'var(--amber)',
  low: 'var(--sage)',
}

const quick = [
  { label: '合同审查', to: '/audit', icon: 'DocumentChecked' },
  { label: '多维报表', to: '/reports', icon: 'DataAnalysis' },
  { label: '知识库', to: '/knowledge', icon: 'Collection' },
  { label: '审查记录', to: '/history', icon: 'Clock' },
]

const activity = [
  { text: '完成「技术服务合同」审查，检出 3 条风险', time: '10 分钟前' },
  { text: '曾庆豪确认 1 项高风险并生成整改项', time: '1 小时前' },
  { text: '知识库新增《民法典》合同编条款 12 条', time: '3 小时前' },
  { text: 'OpenClaw 一体机完成批量审查 26 份', time: '今天 09:20' },
]
</script>

<template>
  <div class="dash">
    <div class="dash-note"><DemoBadge module="dashboard" /></div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      class="dash-error"
    >
      <el-button size="small" text @click="loadSummary">重试</el-button>
    </el-alert>

    <section v-if="loading" class="kpi-row">
      <el-skeleton v-for="i in 4" :key="i" :rows="2" animated class="kpi-card" />
    </section>
    <section v-else class="kpi-row">
      <article v-for="k in kpis" :key="k.label" class="kpi-card">
        <span class="kpi-label">{{ k.label }}</span>
        <strong class="kpi-value mono">{{ k.value }}<i>{{ k.unit }}</i></strong>
        <em class="kpi-trend mono" :class="{ up: k.up }">{{ k.trend }}</em>
      </article>
    </section>

    <section class="dash-grid">
      <el-card shadow="never" class="todo-panel">
        <template #header>
          <div class="panel-head">
            <span>我的待办</span>
            <span class="role-badge">{{ demo.profile.viewLabel }}</span>
          </div>
        </template>
        <div v-for="(t, i) in todos" :key="i" class="todo-item">
          <span class="todo-bar" :style="{ background: levelColor[t.level] }" />
          <span class="todo-title">{{ t.title }}</span>
          <span class="todo-time mono">{{ t.time }}</span>
        </div>
      </el-card>

      <el-card shadow="never" class="side-panel">
        <template #header>快捷入口</template>
        <div class="quick-grid">
          <button v-for="q in quick" :key="q.to" class="quick-item" @click="router.push(q.to)">
            <el-icon :size="22"><component :is="q.icon" /></el-icon>
            <span>{{ q.label }}</span>
          </button>
        </div>
        <div class="activity-head">近期动态</div>
        <ul class="activity-list">
          <li v-for="(a, i) in activity" :key="i">
            <span class="dot" />
            <div><p>{{ a.text }}</p><small class="mono">{{ a.time }}</small></div>
          </li>
        </ul>
      </el-card>
    </section>
  </div>
</template>

<style scoped>
.dash-note {
  margin-bottom: 14px;
}
.dash-error {
  margin-bottom: 16px;
}
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.kpi-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  padding: 18px 20px;
  box-shadow: var(--shadow-sm);
}
.kpi-label {
  font-size: 13px;
  color: var(--ivory-dim);
}
.kpi-value {
  display: block;
  font-size: 30px;
  color: var(--ivory);
  margin: 6px 0 4px;
}
.kpi-value i {
  font-size: 14px;
  color: var(--muted);
  font-style: normal;
  margin-left: 3px;
}
.kpi-trend {
  font-size: 12px;
  color: var(--ivory-dim);
}
.kpi-trend.up {
  color: var(--sage);
}
.dash-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 20px;
  align-items: start;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.role-badge {
  font-size: 12px;
  color: var(--brass);
  background: var(--brass-soft);
  padding: 2px 10px;
  border-radius: 20px;
}
.todo-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 4px;
  border-bottom: 1px solid var(--line);
}
.todo-item:last-child {
  border-bottom: none;
}
.todo-bar {
  width: 3px;
  height: 28px;
  border-radius: 2px;
  flex: none;
}
.todo-title {
  flex: 1;
  font-size: 14px;
  color: var(--ivory);
}
.todo-time {
  font-size: 12px;
  color: var(--muted);
}
.quick-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 18px;
}
.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--ink-3);
  color: var(--ivory);
  cursor: pointer;
  transition: all 0.2s var(--ease);
}
.quick-item:hover {
  border-color: var(--brass);
  color: var(--brass);
}
.activity-head {
  font-family: var(--serif);
  font-weight: 600;
  color: var(--ivory);
  margin-bottom: 10px;
}
.activity-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.activity-list li {
  display: flex;
  gap: 10px;
  padding: 8px 0;
}
.activity-list .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brass);
  margin-top: 6px;
  flex: none;
}
.activity-list p {
  margin: 0;
  font-size: 13px;
  color: var(--ivory);
  line-height: 1.5;
}
.activity-list small {
  color: var(--muted);
  font-size: 11px;
}
@media (max-width: 1180px) {
  .kpi-row {
    grid-template-columns: 1fr 1fr;
  }
  .dash-grid {
    grid-template-columns: 1fr;
  }
}
</style>
