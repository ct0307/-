<script setup lang="ts">
// 多维报表：时间分段(月/季/年) + 多维钻取 + 4 KPI + 4 ECharts。
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getReportData } from '@/api/reports'
import type { ReportData, RangeKey } from '@/mock/reports'
import DemoBadge from '@/components/common/DemoBadge.vue'
import TrendLine from '@/components/charts/TrendLine.vue'
import RiskDonut from '@/components/charts/RiskDonut.vue'
import DeptBar from '@/components/charts/DeptBar.vue'
import TopRiskBar from '@/components/charts/TopRiskBar.vue'

const range = ref<RangeKey>('month')
const raw = ref<ReportData | null>(null)
const loading = ref(false)
const errored = ref(false)

// 多维钻取（确定性系数缩放，模拟子集统计）
const drillType = ref('全部')
const drillAmount = ref('全部')
const drillLevel = ref('全部')

async function load() {
  loading.value = true
  errored.value = false
  try {
    raw.value = await getReportData(range.value)
  } catch {
    errored.value = true
    ElMessage.error('报表数据加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(range, load)

// 钻取缩放系数（演示：非全选时按确定性比例缩小）
const drillFactor = computed(() => {
  let f = 1
  if (drillType.value !== '全部') f *= 0.42
  if (drillAmount.value !== '全部') f *= 0.55
  if (drillLevel.value !== '全部') f *= 0.6
  return f
})
const drilling = computed(() => drillFactor.value < 1)

const data = computed<ReportData | null>(() => {
  if (!raw.value) return null
  if (!drilling.value) return raw.value
  const f = drillFactor.value
  const scale = (n: number) => Math.round(n * f)
  return {
    ...raw.value,
    kpi: {
      ...raw.value.kpi,
      total: scale(raw.value.kpi.total),
      risk: scale(raw.value.kpi.risk),
    },
    trend: {
      labels: raw.value.trend.labels,
      total: raw.value.trend.total.map(scale),
      pass: raw.value.trend.pass.map(scale),
      risk: raw.value.trend.risk.map(scale),
    },
    donut: raw.value.donut.map((d) => ({ ...d, value: scale(d.value) })),
    depts: raw.value.depts.map((d) => ({ ...d, risk: scale(d.risk) })),
    tops: raw.value.tops.map((d) => ({ ...d, value: scale(d.value) })),
  }
})

function resetDrill() {
  drillType.value = '全部'
  drillAmount.value = '全部'
  drillLevel.value = '全部'
}

const kpiCards = computed(() => {
  if (!data.value) return []
  const d = data.value
  return [
    { label: '审查合同总数', value: d.kpi.total.toLocaleString(), trend: d.kpiTrend.total, up: true },
    { label: '合规通过率', value: `${d.kpi.pass}%`, trend: d.kpiTrend.pass, up: true },
    { label: '高风险条款', value: String(d.kpi.risk), trend: d.kpiTrend.risk, up: false },
    { label: '平均审查耗时', value: d.kpi.time, trend: d.kpiTrend.time, up: true },
  ]
})

const rangeSegs: { key: RangeKey; label: string }[] = [
  { key: 'month', label: '本月' },
  { key: 'quarter', label: '本季度' },
  { key: 'year', label: '本年' },
]
</script>

<template>
  <div>
    <div class="toolbar">
      <div class="seg">
        <button v-for="s in rangeSegs" :key="s.key" :class="{ active: range === s.key }" @click="range = s.key">
          {{ s.label }}
        </button>
      </div>
      <DemoBadge module="reports" />
    </div>

    <!-- 多维钻取 -->
    <section class="drill-bar">
      <span class="drill-label"><el-icon><Search /></el-icon>多维钻取</span>
      <el-select v-model="drillType" size="default" style="width: 160px">
        <el-option label="全部类型" value="全部" />
        <el-option label="软件开发外包合同" value="软件开发外包合同" />
        <el-option label="采购合同" value="采购合同" />
        <el-option label="技术服务合同" value="技术服务合同" />
      </el-select>
      <el-select v-model="drillAmount" size="default" style="width: 150px">
        <el-option label="不限金额" value="全部" />
        <el-option label="50 万以下" value="low" />
        <el-option label="50 万 - 200 万" value="mid" />
        <el-option label="200 万以上" value="high" />
      </el-select>
      <el-select v-model="drillLevel" size="default" style="width: 130px">
        <el-option label="全部等级" value="全部" />
        <el-option label="高风险" value="高风险" />
        <el-option label="中风险" value="中风险" />
        <el-option label="低风险" value="低风险" />
      </el-select>
      <el-button v-if="drilling" link type="primary" @click="resetDrill">重置钻取</el-button>
      <span v-if="drilling" class="drill-hint mono">已按条件钻取 · 命中约 {{ Math.round(drillFactor * 100) }}%</span>
    </section>

    <div v-loading="loading" class="report-body">
      <el-result v-if="errored" icon="error" title="加载失败" sub-title="请重试或检查后端连接">
        <template #extra><el-button type="primary" @click="load">重新加载</el-button></template>
      </el-result>

      <template v-else-if="data">
        <section class="kpi-row">
          <article v-for="k in kpiCards" :key="k.label" class="kpi-card">
            <span>{{ k.label }}</span>
            <strong class="mono">{{ k.value }}</strong>
            <em class="mono" :class="{ up: k.up, down: !k.up }">{{ k.trend }}</em>
          </article>
        </section>

        <section class="chart-grid">
          <el-card shadow="never" class="wide">
            <template #header>合同审查趋势</template>
            <TrendLine :data="data.trend" />
          </el-card>
          <el-card shadow="never">
            <template #header>风险等级分布</template>
            <RiskDonut :data="data.donut" :pass="data.kpi.pass" />
          </el-card>
          <el-card shadow="never">
            <template #header>部门风险排行</template>
            <DeptBar :data="data.depts" />
          </el-card>
          <el-card shadow="never">
            <template #header>高风险条款 TOP5</template>
            <TopRiskBar :data="data.tops" />
          </el-card>
        </section>
      </template>
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
.seg {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--ink-2);
}
.seg button {
  padding: 7px 16px;
  border: none;
  background: transparent;
  color: var(--ivory-dim);
  cursor: pointer;
  font-size: 13px;
}
.seg button.active {
  background: var(--brass);
  color: #fff;
}
.drill-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  margin-bottom: 20px;
}
.drill-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--brass);
  font-weight: 600;
}
.drill-hint {
  font-size: 12px;
  color: var(--sage);
}
.report-body {
  min-height: 200px;
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
  padding: 16px 20px;
  box-shadow: var(--shadow-sm);
}
.kpi-card span {
  font-size: 13px;
  color: var(--ivory-dim);
}
.kpi-card strong {
  display: block;
  font-size: 28px;
  color: var(--ivory);
  margin: 6px 0 4px;
}
.kpi-card em {
  font-size: 12px;
  font-style: normal;
}
.kpi-card em.up {
  color: var(--sage);
}
.kpi-card em.down {
  color: var(--seal);
}
.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.chart-grid .wide {
  grid-column: 1 / -1;
}
@media (max-width: 1180px) {
  .kpi-row {
    grid-template-columns: 1fr 1fr;
  }
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
