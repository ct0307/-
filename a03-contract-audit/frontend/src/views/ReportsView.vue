<script setup lang="ts">
// 多维报表：时间分段(月/季/年) + 多维钻取 + 4 KPI + 4 ECharts。
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getReportData, exportRiskLedger, getContractsMetadata, type ContractMeta } from '@/api/reports'
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

const contractsMeta = ref<ContractMeta[]>([])

async function load() {
  loading.value = true
  errored.value = false
  try {
    const [reportData, meta] = await Promise.all([
      getReportData(range.value),
      getContractsMetadata(),
    ])
    raw.value = reportData
    contractsMeta.value = meta
  } catch {
    errored.value = true
    ElMessage.error('报表数据加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(range, load)

// 多维钻取：对 contractsMeta 做真实本地过滤（charts/KPI 反映全局，不参与钻取）
const filteredMeta = computed(() => {
  let list = contractsMeta.value
  if (drillType.value !== '全部')
    list = list.filter((c) => c.contract_type === drillType.value)
  if (drillLevel.value === '高风险')
    list = list.filter((c) => c.risk_high > 0)
  else if (drillLevel.value === '中风险')
    list = list.filter((c) => c.risk_high === 0 && c.risk_total > 0)
  else if (drillLevel.value === '低风险')
    list = list.filter((c) => c.risk_total === 0)
  // 金额范围：amount 字段为自然语言字符串，格式不统一，暂不做过滤
  return list
})
const drilling = computed(() =>
  drillType.value !== '全部' || drillLevel.value !== '全部',
)
const drillHint = computed(() =>
  `已按条件筛选 · 命中 ${filteredMeta.value.length} / ${contractsMeta.value.length} 份`,
)

const data = computed<ReportData | null>(() => raw.value)

const exporting = ref(false)
async function doExport() {
  exporting.value = true
  try {
    await exportRiskLedger()
    ElMessage.success('风险台账已导出')
  } catch {
    ElMessage.error('导出失败，请重试')
  } finally {
    exporting.value = false
  }
}

function resetDrill() {
  drillType.value = '全部'
  drillAmount.value = '全部'
  drillLevel.value = '全部'
}

const kpiCards = computed(() => {
  if (!data.value) return []
  const d = data.value
  return [
    { label: '审查合同总数', value: d.kpi.total.toLocaleString(), trend: d.kpiTrend.total, up: true, tip: '' },
    { label: '合规通过率',   value: `${d.kpi.pass}%`,            trend: d.kpiTrend.pass,  up: true,
      tip: '已确认 + 已忽略风险条款 ÷ 总复核数，反映本期合规水平' },
    { label: '高风险条款',   value: String(d.kpi.risk),           trend: d.kpiTrend.risk,  up: false, tip: '' },
    { label: '平均审查耗时', value: d.kpi.time,                   trend: d.kpiTrend.time,  up: true,
      tip: '从合同上传到审查结果返回的平均时长（不含人工复核等待时间）' },
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
      <div class="toolbar-right">
        <el-button :icon="'Download'" :loading="exporting" @click="doExport">导出台账</el-button>
        <DemoBadge module="reports" />
      </div>
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
      <span v-if="drilling" class="drill-hint mono">{{ drillHint }}</span>
    </section>

    <div v-loading="loading" class="report-body">
      <el-result v-if="errored" icon="error" title="加载失败" sub-title="请重试或检查后端连接">
        <template #extra><el-button type="primary" @click="load">重新加载</el-button></template>
      </el-result>

      <template v-else-if="data">
        <section class="kpi-row">
          <article v-for="k in kpiCards" :key="k.label" class="kpi-card">
            <span class="kpi-label">
              {{ k.label }}
              <el-tooltip v-if="k.tip" :content="k.tip" placement="top" effect="dark">
                <el-icon class="tip-icon"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
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

        <!-- 合同要素汇总：甲方 / 合同标的 / 收付款节点 -->
        <el-card shadow="never" class="meta-card">
          <template #header>
            <div class="panel-head">
              <span>合同要素汇总</span>
              <el-tag size="small" type="info">{{ contractsMeta.length }} 份</el-tag>
            </div>
          </template>
          <el-empty v-if="!filteredMeta.length" description="暂无合同要素数据，上传并解析合同后自动提取" />
          <el-table v-else :data="filteredMeta" style="width: 100%" size="small" :max-height="360">
            <el-table-column prop="filename" label="合同名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="party_a" label="甲方" width="140" show-overflow-tooltip />
            <el-table-column prop="subject" label="合同标的" min-width="160" show-overflow-tooltip />
            <el-table-column prop="payment_terms" label="收付款节点" min-width="180" show-overflow-tooltip />
            <el-table-column prop="amount" label="合同金额" width="110" show-overflow-tooltip />
            <el-table-column label="风险" width="80" align="center">
              <template #default="{ row }">
                <span :class="row.risk_high > 0 ? 'risk-high' : 'risk-ok'">
                  {{ row.risk_high > 0 ? `⚠ ${row.risk_high}高` : `${row.risk_total}条` }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
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
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
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
.kpi-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--ivory-dim);
}
.tip-icon {
  font-size: 13px;
  color: var(--muted);
  cursor: help;
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
.meta-card {
  margin-top: 20px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.risk-high {
  color: var(--seal);
  font-weight: 600;
  font-size: 12px;
}
.risk-ok {
  color: var(--ivory-dim);
  font-size: 12px;
}
</style>
