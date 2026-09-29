<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getContractsMetadata, previewReport, exportEvidenceReport, type ContractMeta, type ReportSnapshot, type ReportRisk } from '@/api/reports'
import { useAuditSessionStore } from '@/stores/audit-session'
import TrendLine from '@/components/charts/TrendLine.vue'
import RiskDonut from '@/components/charts/RiskDonut.vue'
import DeptBar from '@/components/charts/DeptBar.vue'
import TopRiskBar from '@/components/charts/TopRiskBar.vue'
import { applicabilityMeta, decisionMeta, ruleStatusMeta } from '@/utils/audit-trace'

const router = useRouter()
const session = useAuditSessionStore()
const contracts = ref<ContractMeta[]>([])
const loading = ref(false)
const loadError = ref('')
const previewError = ref('')
const previewing = ref(false)
const exporting = ref(false)
const snapshot = ref<ReportSnapshot | null>(null)
const search = ref('')
const type = ref('')
const department = ref('')
const status = ref('')
const startDate = ref('')
const endDate = ref('')
const selected = ref<number[]>([])
const range = ref<'selected' | 'filtered' | 'all'>('selected')
const pickerOpen = ref(false)
const drilldownIds = ref<number[] | null>(null)
const page = ref(1)
const pageSize = 10
const statuses: Record<string, string> = { done: '处理完成', review_required: '待人工复核', failed: '审查失败', queued: '排队中', parsing: '解析中', reviewing: '审查中', validating: '校验中', unreviewed: '未审查' }
const levelNames: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }

function drilldown(ids: number[]) {
  if (!ids.length) { ElMessage.info('当前指标没有匹配合同'); return }
  selected.value = ids.slice(0, 200)
  drilldownIds.value = [...selected.value]
  search.value = ''; type.value = ''; department.value = ''; status.value = ''; startDate.value = ''; endDate.value = ''
  page.value = 1
  range.value = 'selected'
  pickerOpen.value = true
  if (ids.length > 200) ElMessage.info('已选择前 200 份，请通过部门和时间继续缩小范围')
}
const evidenceNames: Record<string, string> = { supported: '依据支持', partially_supported: '部分支持', unsupported: '缺少支持', contradicted: '依据矛盾', unclear: '待核实' }
const types = computed(() => [...new Set(contracts.value.map(c => c.contract_type).filter(Boolean))])
const departments = computed(() => [...new Set(contracts.value.map(c => c.department).filter(Boolean))])
const filtered = computed(() => contracts.value.filter(c =>
  (!drilldownIds.value || drilldownIds.value.includes(c.id)) &&
  (!search.value || (c.filename + c.party_a + c.subject).toLowerCase().includes(search.value.toLowerCase())) &&
  (!type.value || c.contract_type === type.value) &&
  (!department.value || c.department === department.value) &&
  (!status.value || (c.job_status || 'unreviewed') === status.value) &&
  (!startDate.value || !!c.created_at && c.created_at.slice(0, 10) >= startDate.value) &&
  (!endDate.value || !!c.created_at && c.created_at.slice(0, 10) <= endDate.value),
))
const visibleRows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const scopeIds = computed(() => range.value === 'all' ? null : range.value === 'filtered' ? filtered.value.map(c => c.id).sort((a, b) => a - b) : selected.value.length ? [...selected.value].sort((a, b) => a - b) : null)
const scopeCount = computed(() => scopeIds.value?.length ?? contracts.value.length)
const scopeKey = computed(() => JSON.stringify({ range: range.value, ids: scopeIds.value }))
const invalidDates = computed(() => !!startDate.value && !!endDate.value && startDate.value > endDate.value)
const invalidScope = computed(() => !scopeCount.value || !!scopeIds.value && scopeIds.value.length > 200 || range.value === 'filtered' && invalidDates.value)
const scopeLabel = computed(() => scopeIds.value === null ? '全部可见合同' : range.value === 'filtered' ? '当前筛选结果' : '已勾选合同')
const canExport = computed(() => !!snapshot.value && !previewing.value && !loading.value && !loadError.value && !invalidScope.value && !exporting.value)
let requestVersion = 0
let disposed = false
let refreshTimer: ReturnType<typeof setTimeout> | undefined
watch([search, type, department, status, startDate, endDate], () => { page.value = 1 })
function scheduleRefresh() {
  if (disposed) return
  clearTimeout(refreshTimer)
  requestVersion++
  drawerOpen.value = false
  evidenceRows.value = []
  previewError.value = ''
  previewing.value = !invalidScope.value && !loading.value && !loadError.value
  if (!previewing.value) {
    snapshot.value = null
    return
  }
  // 合并连续勾选；范围变化时立即使旧请求和导出失效。
  refreshTimer = setTimeout(generate, 250)
}
watch([scopeKey, invalidScope], scheduleRefresh, { flush: 'sync' })

function toggle(id: number, checked: boolean) {
  if (checked && selected.value.length >= 200) {
    ElMessage.warning('单次勾选最多200份，请缩小范围或查看全部可见合同')
    return
  }
  selected.value = checked ? [...new Set([...selected.value, id])] : selected.value.filter(value => value !== id)
  range.value = 'selected'
}
function clearSelection() {
  selected.value = []
  range.value = 'selected'
}
function selectFiltered() {
  if (new Set([...selected.value, ...filtered.value.map(c => c.id)]).size > 200) {
    ElMessage.warning('单次勾选最多200份，请缩小筛选范围或使用全部可见合同')
    return
  }
  selected.value = [...new Set([...selected.value, ...filtered.value.map(c => c.id)])]
  range.value = 'selected'
}
async function load() {
  clearTimeout(refreshTimer)
  loading.value = true
  loadError.value = ''
  snapshot.value = null
  previewError.value = ''
  previewing.value = false
  drawerOpen.value = false
  requestVersion++
  try {
    contracts.value = await getContractsMetadata()
    selected.value = selected.value.filter(id => contracts.value.some(c => c.id === id))
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '合同列表加载失败，请重试'
  } finally {
    loading.value = false
    scheduleRefresh()
  }
}
async function generate() {
  clearTimeout(refreshTimer)
  if (invalidScope.value || loading.value || loadError.value) return
  const version = ++requestVersion
  const ids = scopeIds.value ? [...scopeIds.value] : null
  drawerOpen.value = false
  previewError.value = ''
  previewing.value = true
  try {
    const result = await previewReport(ids)
    if (version === requestVersion) snapshot.value = result
  } catch (error) {
    if (version === requestVersion) {
      snapshot.value = null
      previewError.value = error instanceof Error ? error.message : '看板加载失败，请重试'
    }
  } finally {
    if (version === requestVersion) previewing.value = false
  }
}
async function download(format: 'xlsx' | 'docx') {
  if (!canExport.value || !snapshot.value) return
  const version = requestVersion
  exporting.value = true
  try {
    await exportEvidenceReport(snapshot.value, format, scopeIds.value === null)
    ElMessage.success('报告已导出')
  } catch (error) {
    if (version === requestVersion) {
      snapshot.value = null
      previewError.value = error instanceof Error ? error.message : '导出失败，请刷新看板后重试'
    }
  } finally { exporting.value = false }
}
async function openCollaboration(contract: ContractMeta) {
  if (!contract.job_id) return
  try {
    await session.loadCompletedAudit(contract.id, contract.filename, contract.job_id)
    await router.push('/collaboration')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '无法读取审查结果') }
}
const donut = computed(() => ['high', 'medium', 'low'].map(level => ({ name: levelNames[level]!, value: snapshot.value?.risks.filter(r => r.level === level).length ?? 0 })))
const deptData = computed(() => {
  const counts = new Map<string, number>()
  snapshot.value?.contracts.forEach(c => counts.set(c.department || '未分类', (counts.get(c.department || '未分类') || 0) + c.risk_total))
  return [...counts].map(([name, risk]) => ({ name, risk, money: '—' }))
})
const tops = computed(() => {
  const counts = new Map<string, number>()
  snapshot.value?.risks.filter(r => r.level === 'high').forEach(r => counts.set(r.category, (counts.get(r.category) || 0) + 1))
  return [...counts].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value).slice(0, 5)
})
const trend = computed(() => {
  const rows = snapshot.value?.contracts || []
  const labels = [...new Set(rows.flatMap(c => c.created_at ? [c.created_at.slice(0, 10)] : []))].sort()
  return {
    labels,
    total: labels.map(day => rows.filter(c => c.created_at && c.created_at.slice(0, 10) <= day).length),
    pass: labels.map(day => rows.filter(c => c.created_at && c.created_at.slice(0, 10) <= day && c.job_status === 'done').length),
    risk: labels.map(day => rows.filter(c => c.created_at && c.created_at.slice(0, 10) <= day && c.risk_high > 0).length),
  }
})
const drawerOpen = ref(false)
const evidenceRows = ref<ReportRisk[]>([])
function showEvidence(contractId?: number, category?: string) {
  if (previewing.value || !snapshot.value) return
  evidenceRows.value = (snapshot.value?.risks || []).filter(r => (!contractId || r.contract_id === contractId) && (!category || r.category === category))
  drawerOpen.value = true
}
function location(risk: ReportRisk) {
  return risk.contract_evidence.map(e => {
    const pages = [...new Set((e.anchors || []).map(a => a.page ?? a.page_number).filter(p => p != null))]
    return (e.clause_id || '条款未编号') + (pages.length ? ' · 第' + pages.join('、') + '页' : '') + (e.match_type === 'exact_quote' ? '（精确引文）' : '（近似定位，需核对）')
  }).join('；') || '尚无可靠原文定位'
}
onMounted(load)
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(refreshTimer)
  requestVersion++
})
</script>

<template>
  <div class="reports">
    <header class="report-heading">
      <div><p class="eyebrow">实时联动 · 证据分析</p><h2>可视化看板</h2><p class="muted">默认展示全部合同；勾选即联动，清空勾选恢复全量。图表、证据与导出使用同一范围。</p></div>
      <el-button @click="load" :loading="loading">刷新合同列表</el-button>
    </header>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <section v-else class="selection-panel" v-loading="loading">
      <div class="section-heading"><h3>看板与导出范围 <span class="muted">已勾选 {{ selected.length }} 份 · 跨页保留</span></h3><el-button :aria-expanded="pickerOpen" aria-controls="contract-selection" @click="pickerOpen = !pickerOpen">{{ pickerOpen ? '收起合同列表' : '选择合同' }}</el-button></div>
      <div class="scope-bar">
        <fieldset><legend class="sr-only">看板与导出范围</legend><label><input v-model="range" type="radio" value="selected">跟随勾选</label><label><input v-model="range" type="radio" value="filtered">当前筛选结果</label><label><input v-model="range" type="radio" value="all">全部可见合同</label></fieldset>
        <span class="scope-count" role="status">{{ scopeLabel }} · {{ scopeCount }} 份</span>
        <el-button :disabled="invalidScope || loading" :loading="previewing" @click="generate">刷新看板</el-button>
      </div>
      <p v-if="range === 'filtered'" class="scope-hint">正在跟随筛选条件；勾选任一合同即可切回勾选范围。</p>
      <p v-if="scopeIds && scopeIds.length > 200" class="risk-high">单次指定最多200份，请缩小筛选范围。</p>
      <p v-if="invalidDates" class="risk-high">导入起日不能晚于止日。</p>
      <el-empty v-if="!contracts.length && !loading" description="暂无合同，请先导入真实测试合同"><el-button type="primary" @click="router.push('/audit')">导入合同</el-button></el-empty>
      <div id="contract-selection" v-show="pickerOpen">
      <p v-if="drilldownIds" class="scope-hint">当前仅展示指标下钻合同（{{ drilldownIds.length }} 份）。<el-button link @click="drilldownIds = null">返回全部候选合同</el-button></p>
      <div class="filters">
        <label class="search-label">搜索合同<el-input v-model="search" aria-label="搜索合同" placeholder="合同名称、甲方或标的" clearable /></label>
        <label>合同类型<select v-model="type" aria-label="合同类型"><option value="">全部类型</option><option v-for="value in types" :key="value">{{ value }}</option></select></label>
        <label>负责部门<select v-model="department" aria-label="负责部门"><option value="">全部部门</option><option v-for="value in departments" :key="value">{{ value }}</option></select></label>
        <label>审查状态<select v-model="status" aria-label="审查状态"><option value="">全部状态</option><option v-for="(label, key) in statuses" :key="key" :value="key">{{ label }}</option></select></label>
        <label>导入起日<input v-model="startDate" type="date" aria-label="导入起日"></label>
        <label>导入止日<input v-model="endDate" type="date" aria-label="导入止日"></label>
      </div>
      <div class="selection-actions"><el-button link @click="selectFiltered" :disabled="!filtered.length">勾选筛选结果</el-button><el-button link @click="clearSelection" :disabled="!selected.length">清空勾选</el-button><span class="muted">筛选命中 {{ filtered.length }} / {{ contracts.length }} 份</span></div>
      <el-empty v-if="contracts.length && !filtered.length && !loading" description="没有符合条件的合同，请调整筛选条件" />
      <el-table v-else-if="contracts.length" :data="visibleRows" row-key="id" class="contract-picker" max-height="260">
        <el-table-column label="勾选" width="58" fixed><template #default="{ row }"><input type="checkbox" :data-contract-id="row.id" :aria-label="'选择 ' + row.filename" :checked="selected.includes(row.id)" :disabled="!selected.includes(row.id) && selected.length >= 200" @change="toggle(row.id, ($event.target as HTMLInputElement).checked)"></template></el-table-column>
        <el-table-column prop="id" label="编号" width="70" />
        <el-table-column prop="filename" label="合同名称" min-width="210" show-overflow-tooltip />
        <el-table-column prop="department" label="部门" width="105" />
        <el-table-column label="导入日期" width="108"><template #default="{ row }">{{ row.created_at?.slice(0, 10) || '暂无记录' }}</template></el-table-column>
        <el-table-column prop="party_a" label="甲方" min-width="150" show-overflow-tooltip />
        <el-table-column label="审查质量" width="118"><template #default="{ row }"><el-tag :type="row.job_status === 'failed' ? 'danger' : row.job_status === 'review_required' ? 'warning' : 'info'">{{ statuses[row.job_status || 'unreviewed'] || '处理中' }}</el-tag></template></el-table-column>
        <el-table-column label="风险条数" width="92"><template #default="{ row }"><span :class="{ 'risk-high': row.risk_high > 0 }">{{ row.risk_total }} · 高 {{ row.risk_high }}</span></template></el-table-column>
        <el-table-column label="结果" width="96"><template #default="{ row }"><el-button link :disabled="!row.job_id || !['done', 'review_required'].includes(row.job_status)" @click="openCollaboration(row)">查看协作</el-button></template></el-table-column>
      </el-table>
      <div class="pager"><el-button size="small" aria-label="上一页" :disabled="page <= 1" @click="page--">上一页</el-button><span>{{ page }} / {{ Math.max(1, Math.ceil(filtered.length / pageSize)) }}</span><el-button size="small" aria-label="下一页" :disabled="page * pageSize >= filtered.length" @click="page++">下一页</el-button></div>
      </div>
    </section>

    <div class="export-bar"><span class="muted" role="status">{{ previewing ? '正在更新看板，完成后即可导出；图表暂为上次结果。' : snapshot ? '看板已同步，可直接导出当前范围的证据报告。' : '当前暂无可导出的看板数据。' }}</span><div><el-button :disabled="!canExport" :loading="exporting" @click="download('xlsx')">导出 Excel</el-button><el-button :disabled="!canExport" @click="download('docx')">导出 Word</el-button></div></div>
    <el-alert v-if="previewError" :title="previewError" type="error" :closable="false" show-icon />
    <div class="report-body" v-loading="previewing" :aria-busy="previewing" element-loading-text="正在同步当前合同范围…">
      <template v-if="snapshot">
        <div class="snapshot-heading"><h3>{{ snapshot.summary.total === 1 ? '单合同诊断' : '合同组合分析' }}</h3><span class="muted">生成于 {{ new Date(snapshot.generated_at).toLocaleString('zh-CN') }} · 编号 {{ snapshot.report_id.slice(0, 12) }}</span></div>
        <section class="kpi-row">
          <article><span>所选合同</span><strong data-testid="preview-total">{{ snapshot.summary.total }}</strong><small>完成 {{ snapshot.summary.completed }} · 未审查 {{ snapshot.summary.unreviewed }}</small></article>
          <article><span>高风险条款</span><strong class="risk-high">{{ snapshot.summary.high }}</strong><small>全部风险 {{ snapshot.summary.risks }} 条</small></article>
          <article><span>待人工复核合同</span><strong>{{ snapshot.summary.review_required }}</strong><small>失败 {{ snapshot.summary.failed }} · 进行中 {{ snapshot.summary.running }}</small></article>
          <article><span>原文与依据已核验</span><strong>{{ snapshot.summary.supported }}<em> / {{ snapshot.summary.risks }}</em></strong><small>原文定位与依据支持同时满足</small></article>
        </section>
        <section v-if="snapshot.operations" class="evidence-panel">
          <h3>当前风险与整改</h3>
          <p class="muted">统计日 {{ snapshot.operations.as_of_date }} · {{ snapshot.operations.metric_version }} · 历史数据不足，暂不显示环比。</p>
          <div class="selection-actions">
            <el-button @click="drilldown(snapshot.contracts.filter(c => c.risk_high > 0).map(c => c.id))">高风险合同 {{ snapshot.operations.high_risk_contracts }} 份</el-button>
            <el-button @click="router.push('/rectify')">逾期整改 {{ snapshot.operations.overdue_count }} 项</el-button>
            <span>待复核风险 {{ snapshot.operations.pending_risk_count }} 条 · 日期待确认 {{ snapshot.operations.unknown_due_count }} 项</span>
          </div>
          <p class="muted">{{ snapshot.operations.amount_note }}</p>
          <p class="muted">{{ snapshot.operations.risk_count_basis }}</p>
          <el-table :data="snapshot.operations.departments">
            <el-table-column prop="department" label="部门" min-width="100" />
            <el-table-column prop="contract_count" label="合同数" width="90" />
            <el-table-column label="高风险合同占比" min-width="145"><template #default="{ row }">{{ row.high_risk_contracts }} / {{ row.contract_count }}（{{ (row.high_risk_rate * 100).toFixed(1) }}%）</template></el-table-column>
            <el-table-column label="下钻" width="100"><template #default="{ row }"><el-button link @click="drilldown(row.contract_ids)">查看合同</el-button></template></el-table-column>
          </el-table>
        </section>
        <section class="chart-grid">
          <el-card shadow="never"><template #header>导入日期分布（累计）</template><TrendLine :data="trend" :labels="['导入合同', '当前已完成', '含高风险合同']" /><p class="muted">按导入日期分组展示当前状态，不表示历史审查效果。</p></el-card>
          <el-card shadow="never"><template #header>风险等级分布</template><RiskDonut :data="donut" /></el-card>
          <el-card shadow="never"><template #header>部门风险分布</template><DeptBar :data="deptData" /></el-card>
          <el-card shadow="never"><template #header>高风险类别 TOP5</template><TopRiskBar :data="tops" /></el-card>
        </section>
        <p class="quality-note">统计采用各合同最新审查任务；无高风险或零风险不等于合规确认，失败任务不以旧结果替代。</p>

        <section class="evidence-panel">
          <div class="section-heading"><div><h3>合同 × 风险类别</h3><p class="muted">点击有风险的单元格，查看对应证据链。</p></div><el-button @click="showEvidence()">查看证据</el-button></div>
          <div v-if="snapshot.matrix.categories.length" class="matrix-scroll"><table class="risk-matrix"><thead><tr><th>合同</th><th v-for="category in snapshot.matrix.categories" :key="category">{{ category }}</th></tr></thead><tbody><tr v-for="row in snapshot.matrix.rows" :key="row.contract_id"><th>{{ row.filename }}</th><td v-for="(count, index) in row.counts" :key="index"><button v-if="count" class="matrix-count" :aria-label="row.filename + ' ' + snapshot.matrix.categories[index] + ' ' + count + '条'" @click="showEvidence(row.contract_id, snapshot.matrix.categories[index])">{{ count }}</button><span v-else class="muted">—</span></td></tr></tbody></table></div>
          <el-empty v-else description="当前范围暂无可展示风险，请结合审查质量判断" />
        </section>

        <section class="evidence-panel"><h3>合同要素与付款联动</h3>
          <el-collapse>
            <el-collapse-item v-for="contract in snapshot.contracts" :key="contract.id" :name="contract.id" :title="contract.filename + ' · ' + (statuses[contract.job_status || 'unreviewed'] || '处理中')">
              <dl class="elements"><div><dt>甲方</dt><dd>{{ contract.party_a }}</dd></div><div><dt>合同标的</dt><dd>{{ contract.subject }}</dd></div><div><dt>金额（原文）</dt><dd>{{ contract.amount }}</dd></div><div><dt>收付款节点</dt><dd>{{ contract.payment_terms }}</dd></div><div><dt>审查覆盖</dt><dd>{{ contract.coverage ? (contract.coverage.completed ?? '未知') + ' / ' + (contract.coverage.planned ?? '未知') + ' 个窗口' : '暂无覆盖信息' }}</dd></div><div v-if="contract.review_reason"><dt>质量说明</dt><dd>{{ contract.review_reason }}</dd></div></dl>
              <template v-if="contract.payment_analysis"><p class="calculation">{{ contract.payment_analysis.calculation }}</p><ol class="payment-events"><li v-for="(event, index) in contract.payment_analysis.events" :key="index"><strong>{{ event.condition }} · {{ event.percentage === null ? '比例待确认' : event.percentage + '%' }}</strong><p>{{ event.quote }}</p><small>{{ event.clause_id }} · {{ event.base }}</small></li></ol><article v-for="(issue, index) in contract.payment_analysis.issues" :key="index" class="payment-issue"><strong>{{ issue.message }}</strong><blockquote v-for="(quote, i) in issue.quotes" :key="i">{{ quote }}</blockquote></article></template>
            </el-collapse-item>
          </el-collapse>
        </section>
        <section class="evidence-panel"><h3>整改跟踪</h3><el-table v-if="snapshot.rectifications.length" :data="snapshot.rectifications"><el-table-column prop="risk" label="问题" min-width="180" /><el-table-column prop="owner" label="负责人" /><el-table-column prop="due" label="截止日" /><el-table-column prop="status" label="状态" /></el-table><p v-else class="muted">当前范围暂无已关联的整改任务。复核风险后可分派责任人和截止日期。</p></section>
        <details class="report-notes"><summary>查看报告范围与统计口径</summary><p v-for="note in snapshot.notes" :key="note">{{ note }}</p></details>
      </template>
      <el-empty v-else-if="contracts.length && !loading && !loadError && !previewing && !previewError" :description="invalidScope ? '当前范围无法展示，请调整筛选条件或合同数量' : '暂无看板数据，请刷新看板重试'" />
    </div>
    <el-drawer v-model="drawerOpen" title="风险证据链" size="min(720px, 100vw)">
      <el-empty v-if="!evidenceRows.length" description="当前范围暂无风险证据" />
      <article v-for="risk in evidenceRows" :key="risk.id" class="risk-evidence">
        <div class="section-heading"><h3>R{{ risk.id }} · {{ risk.category }}</h3><el-tag :type="risk.level === 'high' ? 'danger' : 'warning'">{{ levelNames[risk.level] || risk.level }}</el-tag></div>
        <p class="muted">{{ risk.filename }} · {{ risk.agent === 'finance' ? '财务会计' : risk.agent === 'legal' ? '法务专家' : '规则校验' }}</p>
        <p>{{ location(risk) }}</p><blockquote>{{ risk.original_text }}</blockquote>
        <dl><dt>风险原因</dt><dd>{{ risk.risk_reason || '未提供' }}</dd><dt>依据</dt><dd>{{ risk.basis || '未提供' }}</dd><dt>核验状态</dt><dd>{{ evidenceNames[risk.evidence_status || 'unclear'] || '待核实' }} · 原文{{ risk.original_text_verified ? '已核验' : '未核验' }}</dd><dt>法规适用性</dt><dd><el-tag size="small" :type="applicabilityMeta(risk.applicability_status).type">{{ applicabilityMeta(risk.applicability_status).label }}</el-tag><span v-if="risk.applicability_reason_codes?.length"> · {{ risk.applicability_reason_codes.join('、') }}</span></dd><dt>规则核验</dt><dd><template v-if="risk.rule_executions?.length"><span v-for="(rule, index) in risk.rule_executions" :key="index"><el-tag size="small" :type="ruleStatusMeta(rule.status).type">{{ ruleStatusMeta(rule.status).label }}</el-tag><span v-if="rule.rule_id"> {{ rule.rule_id }}</span><span v-if="index < risk.rule_executions.length - 1">；</span></span></template><span v-else>待核验</span></dd><dt>决策结果</dt><dd><el-tag size="small" :type="decisionMeta(risk.decision_trace?.status).type">{{ decisionMeta(risk.decision_trace?.status).label }}</el-tag><span v-if="risk.decision_trace?.reason_codes?.length"> · {{ risk.decision_trace.reason_codes.join('、') }}</span></dd><dt>检索来源</dt><dd><p v-for="(source, index) in risk.rag_sources" :key="index">{{ source.source || source.title || '来源待核实' }}：{{ source.content || source.quote || '正文待核实' }}</p><span v-if="!risk.rag_sources.length">尚无可回读的检索来源</span></dd><dt>修改建议</dt><dd>{{ risk.suggestion }}</dd></dl>
      </article>
    </el-drawer>
  </div>
</template>

<style scoped>
.reports { min-width: 0; }
.report-heading,.section-heading,.snapshot-heading,.export-bar,.selection-actions,.pager,.scope-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.report-heading { margin-bottom: 14px; }
.report-heading p { margin: 4px 0; }
h2 { font-size: 23px; font-weight: 600; margin: 8px 0; letter-spacing: .02em; }
h3 { margin: 0 0 8px; font-size: 15px; }
p { line-height: 1.7; }
.eyebrow { color: var(--brass); font-size: 12px; letter-spacing: .12em; margin: 0; }
.muted,small { color: var(--muted); font-size: 12px; }
.selection-panel,.evidence-panel { background: var(--ink-2); border: 1px solid var(--line); border-radius: var(--r-md); padding: 20px; margin-bottom: 18px; min-width: 0; }
.selection-panel { padding: 14px; margin-bottom: 12px; }
.selection-panel .section-heading h3 { margin: 0; }
.selection-panel .section-heading h3 span { display: inline-block; margin-left: 12px; font-weight: 400; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.filters label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--ivory-dim); flex: 1 1 130px; min-width: 0; }
.filters .search-label { flex: 2 1 220px; }
select,input[type=date] { color: var(--ivory); background: var(--ink-2); border: 1px solid var(--line); border-radius: 4px; padding: 7px 10px; height: 33px; min-width: 0; width: 100%; box-sizing: border-box; font: inherit; }
input[type=checkbox],input[type=radio] { accent-color: var(--brass); width: 16px; height: 16px; cursor: pointer; vertical-align: middle; }
.selection-actions { justify-content: flex-start; margin: 15px 0; }
.pager { justify-content: flex-end; font-size: 12px; margin: 14px 0; }
.scope-bar { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 12px; }
.scope-hint { color: var(--muted); font-size: 12px; margin: 10px 0 0; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
fieldset { border: 0; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; }
legend { color: var(--muted); font-size: 12px; margin-bottom: 8px; }
.scope-count { color: var(--brass); margin-left: auto; }
.export-bar { padding: 0 0 8px; }
.report-body { min-height: 120px; }
.snapshot-heading { margin: 10px 0; }
.kpi-row { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; }
.kpi-row article { padding: 12px; border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--ink-2); }
.kpi-row span { font-size: 12px; color: var(--ivory-dim); }
.kpi-row strong { display: block; font-size: 28px; margin: 6px 0; font-family: 'JetBrains Mono', monospace; }
.kpi-row em { font-size: 16px; font-style: normal; color: var(--muted); }
.risk-high { color: var(--seal); }
.quality-note { border-left: 3px solid var(--brass); padding-left: 12px; color: var(--ivory-dim); font-size: 12px; margin: 18px 0; }
.chart-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; margin: 16px 0 20px; }
.chart-grid :deep(.el-card) { min-width: 0; }
.matrix-scroll { overflow: auto; max-height: 420px; }
.risk-matrix { width: 100%; border-collapse: collapse; font-size: 12px; }
.risk-matrix th,.risk-matrix td { padding: 12px; border-bottom: 1px solid var(--line); text-align: center; min-width: 100px; }
.risk-matrix th:first-child { text-align: left; min-width: 220px; max-width: 320px; overflow-wrap: anywhere; }
.risk-matrix thead th { position: sticky; top: 0; background: var(--ink-2); z-index: 1; color: var(--muted); font-weight: 500; }
.matrix-count { background: color-mix(in srgb, var(--seal) 14%, transparent); color: var(--seal); border: 1px solid color-mix(in srgb,var(--seal) 35%,transparent); padding: 7px 20px; border-radius: 4px; cursor: pointer; font-weight: 600; }
.matrix-count:hover { background: color-mix(in srgb,var(--seal) 26%,transparent); }
.elements { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
dt { font-size: 12px; color: var(--muted); margin-top: 12px; }
dd { margin: 7px 0 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
.calculation { color: var(--brass); border-block: 1px solid var(--line); padding: 12px 0; }
.payment-events { padding-left: 24px; }
.payment-events li { padding: 7px 0 10px 8px; }
.payment-events p { margin: 5px 0; }
.payment-issue { border-left: 3px solid var(--seal); padding: 8px 14px; margin: 15px 0; }
blockquote { margin: 12px 0; padding: 14px; background: var(--ink-2); border-left: 2px solid var(--brass); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.risk-evidence { padding: 5px 0 24px; margin-bottom: 20px; border-bottom: 1px solid var(--line); }
.report-notes { font-size: 12px; color: var(--muted); margin: 22px 0; }
.report-notes summary { cursor: pointer; }
@media (max-width: 1100px) { .kpi-row { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 720px) { .chart-grid,.elements { grid-template-columns: minmax(0,1fr); } .selection-panel,.evidence-panel { padding: 14px; } h2 { font-size: 20px; } .scope-count { margin-left: 0; } .report-heading { align-items: flex-start; } .export-bar { align-items: flex-start; } .kpi-row article { padding: 12px; } }
</style>
