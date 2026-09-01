<script setup lang="ts">
// 多维报表：明细驱动 + 多维钻取 + 4 KPI + 4 ECharts + 合同要素汇总。
// 数据分两层：① 明细层 contractsMeta（真实、参与钻取，驱动 KPI + 风险分布环形图）；
// ② 全局聚合层 report_summary（趋势/部门/TOP5，条款级，标注「全局视图」不随钻取变）。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getReportData, exportRiskLedger, getContractsMetadata, type ContractMeta } from '@/api/reports'
import type { ReportData } from '@/mock/reports'
import DemoBadge from '@/components/common/DemoBadge.vue'
import TrendLine from '@/components/charts/TrendLine.vue'
import RiskDonut from '@/components/charts/RiskDonut.vue'
import DeptBar from '@/components/charts/DeptBar.vue'
import TopRiskBar from '@/components/charts/TopRiskBar.vue'

const raw = ref<ReportData | null>(null)
const loading = ref(false)
const errored = ref(false)

// 多维钻取（对明细做真实过滤，联动 KPI + 环形图）
const drillType = ref('全部')
const drillLevel = ref('全部')

const contractsMeta = ref<ContractMeta[]>([])

async function load() {
  loading.value = true
  errored.value = false
  try {
    const [reportData, meta] = await Promise.all([
      getReportData('month'), // 趋势已改全局累计，range 不再影响数据，固定传参
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

// 钻取「合同类型」选项：从真实明细 distinct，避免出现库中不存在的类型
const typeOptions = computed(() => {
  const set = new Set(contractsMeta.value.map((c) => c.contract_type).filter((t) => t && t !== '—'))
  return Array.from(set)
})

// 明细钻取：合同类型 + 风险等级（高=有高风险 / 中=无高有中低 / 低=无风险）
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
  return list
})
const drilling = computed(() => drillType.value !== '全部' || drillLevel.value !== '全部')
const drillHint = computed(
  () => `已按条件筛选 · 命中 ${filteredMeta.value.length} / ${contractsMeta.value.length} 份`,
)

// KPI 基于钻取后的明细实时重算（口径：合规通过率 = 无高风险合同占比）
const kpiCards = computed(() => {
  const list = filteredMeta.value
  const total = list.length
  const passed = list.filter((c) => c.risk_high === 0).length
  const passRate = total ? Math.round((passed / total) * 1000) / 10 : 0
  const highClauses = list.reduce((s, c) => s + c.risk_high, 0)
  const totalClauses = list.reduce((s, c) => s + c.risk_total, 0)
  return [
    { label: '审查合同数', value: total.toLocaleString(), tip: drilling.value ? '当前钻取条件下的合同数' : '' },
    {
      label: '合规通过率',
      value: `${passRate}%`,
      tip: '无「高风险」条款的合同数 ÷ 合同总数，反映本期合规水平',
    },
    { label: '高风险条款', value: String(highClauses), tip: '当前范围内所有高风险条款累计' },
    { label: '风险条款总数', value: String(totalClauses), tip: '高 + 中 + 低风险条款累计' },
  ]
})

// 风险等级分布环形图：基于钻取后明细重算（纯条款等级分布，量纲统一）
const donutData = computed(() => {
  const list = filteredMeta.value
  return [
    { name: '高风险', value: list.reduce((s, c) => s + c.risk_high, 0) },
    { name: '中风险', value: list.reduce((s, c) => s + c.risk_medium, 0) },
    { name: '低风险', value: list.reduce((s, c) => s + c.risk_low, 0) },
  ]
})

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
  drillLevel.value = '全部'
}
</script>

<template>
  <div>
    <div class="toolbar">
      <span class="toolbar-title">合同合规多维报表</span>
      <div class="toolbar-right">
        <el-button :icon="'Download'" :loading="exporting" @click="doExport">导出台账</el-button>
        <DemoBadge module="reports" />
      </div>
    </div>

    <!-- 多维钻取：联动 KPI + 风险等级分布 -->
    <section class="drill-bar">
      <span class="drill-label"><el-icon><Search /></el-icon>多维钻取</span>
      <el-select v-model="drillType" size="default" style="width: 180px">
        <el-option label="全部类型" value="全部" />
        <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
      </el-select>
      <el-select v-model="drillLevel" size="default" style="width: 130px">
        <el-option label="全部等级" value="全部" />
        <el-option label="高风险" value="高风险" />
        <el-option label="中风险" value="中风险" />
        <el-option label="低风险" value="低风险" />
      </el-select>
      <el-button v-if="drilling" link type="primary" @click="resetDrill">重置钻取</el-button>
      <span v-if="drilling" class="drill-hint mono">{{ drillHint }}</span>
      <span class="drill-scope">钻取联动 KPI 与风险等级分布 · 趋势/部门/TOP5 为全局视图</span>
    </section>

    <div v-loading="loading" class="report-body">
      <el-result v-if="errored" icon="error" title="加载失败" sub-title="请重试或检查后端连接">
        <template #extra><el-button type="primary" @click="load">重新加载</el-button></template>
      </el-result>

      <template v-else-if="raw">
        <section class="kpi-row">
          <article v-for="k in kpiCards" :key="k.label" class="kpi-card">
            <span class="kpi-label">
              {{ k.label }}
              <el-tooltip v-if="k.tip" :content="k.tip" placement="top" effect="dark">
                <el-icon class="tip-icon"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
            <strong class="mono">{{ k.value }}</strong>
          </article>
        </section>

        <section class="chart-grid">
          <el-card shadow="never">
            <template #header>
              <div class="panel-head">
                <span>合同审查趋势</span>
                <el-tag size="small" type="info">累计 · 全局</el-tag>
              </div>
            </template>
            <TrendLine :data="raw.trend" />
          </el-card>
          <el-card shadow="never">
            <template #header>
              <div class="panel-head">
                <span>风险等级分布</span>
                <el-tag v-if="drilling" size="small" type="warning">钻取中</el-tag>
              </div>
            </template>
            <RiskDonut :data="donutData" />
          </el-card>
          <el-card shadow="never">
            <template #header>
              <div class="panel-head">
                <span>部门风险排行</span>
                <el-tag size="small" type="info">全局</el-tag>
              </div>
            </template>
            <DeptBar :data="raw.depts" />
          </el-card>
          <el-card shadow="never">
            <template #header>
              <div class="panel-head">
                <span>高风险条款 TOP5</span>
                <el-tag size="small" type="info">全局</el-tag>
              </div>
            </template>
            <TopRiskBar :data="raw.tops" />
          </el-card>
        </section>

        <!-- 合同要素汇总：甲方 / 合同标的 / 收付款节点（随钻取过滤） -->
        <el-card shadow="never" class="meta-card">
          <template #header>
            <div class="panel-head">
              <span>合同要素汇总</span>
              <el-tag size="small" type="info">{{ filteredMeta.length }} / {{ contractsMeta.length }} 份</el-tag>
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
.toolbar-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ivory);
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
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
.drill-scope {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--muted);
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
  border-radius: var(--r-sm);
  padding: 16px 20px;
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
  margin: 6px 0 0;
}
.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
@media (max-width: 1180px) {
  .kpi-row {
    grid-template-columns: 1fr 1fr;
  }
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 720px) {
  .kpi-row {
    grid-template-columns: 1fr;
  }
  .drill-scope {
    width: 100%;
    margin-left: 0;
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
