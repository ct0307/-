<script setup lang="ts">
// 工作台首页：KPI + 真实整改待办 + 近期审查动态（全部接真实数据，去掉演示假数据）
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useRectifyStore } from '@/stores/rectify'
import { getDashboardSummary } from '@/api/dashboard'
import { getHistory } from '@/api/history'
import type { DashboardSummary } from '@/mock/dashboard'
import type { HistoryRow } from '@/mock/history'
import DemoBadge from '@/components/common/DemoBadge.vue'

const router = useRouter()
const rectify = useRectifyStore()

// —— 看板聚合 ——
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

// —— 近期审查记录（动态来源）——
const recentContracts = ref<HistoryRow[]>([])

async function loadRecentContracts() {
  try {
    const data = await getHistory()
    recentContracts.value = data.slice(0, 5)
  } catch {
    // 非核心功能，静默失败
  }
}

onMounted(() => {
  loadSummary()
  rectify.load()
  loadRecentContracts()
})

// —— KPI ——
const passRate = computed(() => {
  const rs = summary.value?.review_status
  if (!rs) return '—'
  const total = Object.values(rs).reduce((a, b) => a + b, 0)
  if (!total) return '0'
  const passed = (rs['已确认'] ?? 0) + (rs['已忽略'] ?? 0)
  return String(Math.round((passed / total) * 1000) / 10)
})

const kpis = computed(() => [
  { label: '累计审查合同', value: String(summary.value?.total_contracts ?? '—'), unit: '份', hint: '系统上线至今累计处理的合同总份数', up: true },
  { label: '待整改项', value: String(rectify.openCount), unit: '项', hint: '当前"待处理"状态的整改项，需尽快跟进', up: false },
  { label: '累计检出风险', value: String(summary.value?.total_risks ?? '—'), unit: '条', hint: '所有合同审查中 AI 检出的风险条款总数', up: false },
  { label: '合规通过率', value: passRate.value, unit: '%', hint: '已确认 + 已忽略的风险数 ÷ 总风险数（复核完成口径）', up: true },
])

// —— 待办：取真实"待处理"整改项，最多展示 5 条 ——
const pendingTodos = computed(() =>
  rectify.items.filter((r) => r.status === '待处理').slice(0, 5),
)

const levelColor: Record<string, string> = {
  high: 'var(--seal)',
  medium: 'var(--amber)',
  low: 'var(--sage)',
}

// —— 近期动态：从真实审查记录推导 ——
function formatRelativeTime(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d} 天前`
  return new Date(isoStr).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

const activity = computed(() =>
  recentContracts.value.map((c) => ({
    text: `完成「${c.name}」审查，检出 ${c.riskCount} 条风险`,
    time: formatRelativeTime(c.time),
    high: c.level === '高风险',
  })),
)
</script>

<template>
  <div class="dash">
    <div class="dash-note"><DemoBadge module="dashboard" /></div>

    <!-- 加载失败内联错误块（统一 el-result 风格） -->
    <el-result
      v-if="error"
      icon="error"
      title="看板加载失败"
      :sub-title="error"
    >
      <template #extra>
        <el-button type="primary" @click="loadSummary">重新加载</el-button>
      </template>
    </el-result>

    <template v-else>
    <!-- KPI 行 -->
    <section v-if="loading" class="kpi-row">
      <el-skeleton v-for="i in 4" :key="i" :rows="2" animated class="kpi-card" />
    </section>
    <section v-else class="kpi-row">
      <article v-for="k in kpis" :key="k.label" class="kpi-card">
        <div class="kpi-label-row">
          <span class="kpi-label">{{ k.label }}</span>
          <el-tooltip :content="k.hint" placement="bottom">
            <el-icon class="kpi-hint"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
        <strong class="kpi-value mono">{{ k.value }}<i>{{ k.unit }}</i></strong>
      </article>
    </section>

    <section class="dash-grid">
      <!-- 左：整改待办（真实数据） -->
      <el-card shadow="never" class="todo-panel">
        <template #header>
          <div class="panel-head">
            <span>待处理整改</span>
            <span v-if="rectify.countByStatus.待处理" class="count-badge">
              {{ rectify.countByStatus.待处理 }} 项<template v-if="rectify.countByStatus.待处理 > 5"> · 仅显示前 5</template>
            </span>
          </div>
        </template>

        <!-- 空状态 -->
        <div v-if="rectify.loading" class="todo-loading">
          <el-skeleton :rows="3" animated />
        </div>
        <div v-else-if="pendingTodos.length === 0" class="todo-empty">
          <el-icon :size="28"><CircleCheck /></el-icon>
          <span>暂无待处理整改项</span>
        </div>
        <div v-else>
          <div
            v-for="t in pendingTodos"
            :key="t.id"
            class="todo-item"
            @click="router.push('/rectify')"
          >
            <span class="todo-bar" :style="{ background: levelColor[t.level] }" />
            <div class="todo-body">
              <span class="todo-contract">{{ t.contract }}</span>
              <span class="todo-risk">{{ t.risk }}</span>
            </div>
            <span class="todo-due mono">{{ t.due }}</span>
            <el-icon class="todo-go"><ArrowRight /></el-icon>
          </div>
        </div>
      </el-card>

      <!-- 右：近期审查动态（真实数据） -->
      <el-card shadow="never" class="activity-panel">
        <template #header>近期审查动态</template>
        <div v-if="recentContracts.length === 0" class="activity-empty">
          暂无审查记录
        </div>
        <ul v-else class="activity-list">
          <li v-for="(a, i) in activity" :key="i">
            <span class="dot" :class="{ alert: a.high }" />
            <div>
              <p>{{ a.text }}</p>
              <small class="mono">{{ a.time }}</small>
            </div>
          </li>
        </ul>
        <el-button
          link
          type="primary"
          class="history-link"
          @click="router.push('/history')"
        >
          查看全部审查记录 →
        </el-button>
      </el-card>
    </section>
    </template>
  </div>
</template>

<style scoped>
.dash-note {
  margin-bottom: 14px;
}
.dash-error {
  margin-bottom: 16px;
}

/* KPI */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.kpi-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: 18px 20px;
}
.kpi-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}
.kpi-label {
  font-size: 13px;
  color: var(--ivory-dim);
}
.kpi-hint {
  font-size: 13px;
  color: var(--muted);
  cursor: help;
  flex: none;
}
.kpi-hint:hover {
  color: var(--brass);
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

/* 两栏网格 */
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
.count-badge {
  font-size: 12px;
  color: var(--seal);
  background: var(--seal-soft);
  padding: 2px 10px;
  border-radius: var(--r-pill);
}

/* 待办列表 */
.todo-loading {
  padding: 8px 0;
}
.todo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 0;
  color: var(--sage);
  font-size: 13px;
}
.todo-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 6px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  border-radius: var(--r-sm);
  transition: background-color 0.15s ease;
}
.todo-item:last-child {
  border-bottom: none;
}
.todo-item:hover {
  background: var(--ink-3);
}
.todo-bar {
  width: 3px;
  height: 32px;
  border-radius: 2px;
  flex: none;
}
.todo-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.todo-contract {
  font-size: 13px;
  color: var(--ivory);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.todo-risk {
  font-size: 12px;
  color: var(--muted);
}
.todo-due {
  font-size: 11px;
  color: var(--ivory-dim);
  white-space: nowrap;
}
.todo-go {
  color: var(--muted);
  font-size: 14px;
}

/* 近期动态 */
.activity-empty {
  padding: 20px 0;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
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
  border-bottom: 1px solid var(--line);
}
.activity-list li:last-child {
  border-bottom: none;
}
.activity-list .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brass);
  margin-top: 6px;
  flex: none;
}
.activity-list .dot.alert {
  background: var(--seal);
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
.history-link {
  margin-top: 10px;
  font-size: 12px;
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
