<script setup lang="ts">
// 审查历史记录：el-table + 分页 + 搜索 + 风险等级筛选 + 点击行查看风险详情。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getHistory } from '@/api/history'
import { getAuditStatus, getRisks } from '@/api/contract'
import type { HistoryRow } from '@/mock/history'
import type { RiskOut } from '@/api/types'
import DemoBadge from '@/components/common/DemoBadge.vue'
import AnnotationModal from '@/components/audit/AnnotationModal.vue'
import { useAuthStore } from '@/stores/auth'
import { riskEvidenceMeta } from '@/utils/risk-evidence'
import { historyAuditCoverage, historyRiskCountLabel, isHistoryAuditAssessmentComplete, normalizeHistoryAssessment, type HistoryAuditSnapshot } from '@/utils/history-assessment'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const canReadDocument = computed(() => auth.hasRole(['legal', 'finance']))

const rows = ref<HistoryRow[]>([])
const loading = ref(false)
const keyword = ref(typeof route.query.contract === 'string' ? route.query.contract : '')
const levelFilter = ref('全部')
const statusFilter = ref('全部')
const page = ref(1)
const pageSize = 8

async function load() {
  loading.value = true
  try {
    rows.value = (await getHistory()).map(normalizeHistoryAssessment)
  } catch {
    ElMessage.error('历史记录加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return rows.value.filter((r) => {
    const kwOk = !kw || r.name.includes(kw) || r.id.includes(kw)
    const lvOk = levelFilter.value === '全部' || r.level === levelFilter.value
    const statusOk = statusFilter.value === '全部' || r.status === statusFilter.value
    return kwOk && lvOk && statusOk
  })
})
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

const levelType: Record<string, 'danger' | 'warning' | 'info'> = {
  高风险: 'danger',
  中风险: 'warning',
  低风险: 'info',
  尚无法判断: 'warning',
  未发现风险: 'info',
}
const statusType: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
  合规: 'success',
  待整改: 'warning',
  已整改: 'info',
  待人工复核: 'danger',
  解析失败: 'danger',
  未审查: 'info',
  审查中: 'warning',
  审查失败: 'danger',
  未发现风险: 'info',
}

// ── 点击行查看风险详情 ──
const drawerOpen = ref(false)
const drawerTitle = ref('')
const drawerRisks = ref<RiskOut[]>([])
const drawerLoading = ref(false)
const selectedRow = ref<HistoryRow | null>(null)
const selectedContractId = ref<number | null>(null)
const selectedAudit = ref<HistoryAuditSnapshot | null>(null)
const drawerError = ref('')
const annotationOpen = ref(false)
let requestVersion = 0
let statusController: AbortController | null = null
const drawerComplete = computed(() => isHistoryAuditAssessmentComplete(selectedAudit.value))
const coverageLabel = computed(() => {
  const coverage = historyAuditCoverage(selectedAudit.value)
  return coverage ? `已完成 ${coverage.completed} / ${coverage.planned} 项计划检查。` : '缺少完整覆盖率证据。'
})

function cancelDetails() {
  requestVersion++
  statusController?.abort()
  statusController = null
}
watch(drawerOpen, open => { if (!open) cancelDetails() })
onBeforeUnmount(cancelDetails)

const riskLevelType: Record<string, 'danger' | 'warning' | 'info'> = {
  high: 'danger', medium: 'warning', low: 'info',
}
const riskLevelLabel: Record<string, string> = {
  high: '高风险', medium: '中风险', low: '低风险',
}
const reviewStatusLabel: Record<string, string> = {
  pending: '待复核', confirmed: '已确认', ignored: '已忽略', to_modify: '待修改',
}

async function onRowClick(row: HistoryRow) {
  // id 格式 C0001 → 数字 1
  const cid = parseInt(row.id.replace(/\D/g, ''))
  if (!cid) return
  cancelDetails()
  annotationOpen.value = false
  selectedRow.value = row
  selectedContractId.value = cid
  drawerTitle.value = row.name
  drawerOpen.value = true
  await loadDetails()
}

async function loadDetails() {
  cancelDetails()
  const version = requestVersion
  const cid = selectedContractId.value
  if (!cid) return
  const controller = new AbortController()
  statusController = controller
  drawerRisks.value = []
  selectedAudit.value = null
  drawerError.value = ''
  drawerLoading.value = true
  try {
    const audit = await getAuditStatus(cid, undefined, controller.signal)
    if (version !== requestVersion) return
    if (audit.contract_id !== cid) throw new Error('审查任务合同不匹配')
    selectedAudit.value = audit
    // 未形成任务的合同不读取跨任务候选，原文入口仍可使用。
    if (audit.job_id) {
      const risks = await getRisks(cid, audit.job_id)
      if (version !== requestVersion) return
      drawerRisks.value = risks
    }
  } catch {
    if (version === requestVersion && !controller.signal.aborted) {
      drawerError.value = '详情加载失败，结果尚无法判断。可重试或查看合同原文。'
    }
  } finally {
    if (version === requestVersion) {
      drawerLoading.value = false
      statusController = null
    }
  }
}

function goAudit() {
  if (!selectedRow.value || !selectedContractId.value) return
  const audit = selectedAudit.value
  if (audit?.batch_id && !['done', 'review_required'].includes(audit.status)) {
    router.push({ path: '/audit', query: { batch: String(audit.batch_id) } })
    return
  }
  router.push({ path: '/audit', query: {
    contractId: String(selectedContractId.value), filename: selectedRow.value.name,
    ...(audit?.job_id ? { jobId: String(audit.job_id) } : {}),
  } })
}
</script>

<template>
  <div v-loading="loading" class="history-page">
    <div class="toolbar">
      <div class="filters">
        <el-input v-model="keyword" placeholder="搜索合同名称 / 编号" :prefix-icon="'Search'" style="width: 240px" clearable @input="page = 1" />
        <el-select v-model="levelFilter" style="width: 140px" @change="page = 1">
          <el-option label="全部风险等级" value="全部" />
          <el-option label="高风险" value="高风险" />
          <el-option label="中风险" value="中风险" />
          <el-option label="低风险" value="低风险" />
          <el-option label="尚无法判断" value="尚无法判断" />
          <el-option label="未发现风险" value="未发现风险" />
        </el-select>
        <el-select v-model="statusFilter" style="width: 140px" @change="page = 1">
          <el-option label="全部合规状态" value="全部" />
          <el-option label="未审查" value="未审查" />
          <el-option label="审查中" value="审查中" />
          <el-option label="审查失败" value="审查失败" />
          <el-option label="待人工复核" value="待人工复核" />
          <el-option label="解析失败" value="解析失败" />
          <el-option label="待整改" value="待整改" />
          <el-option label="已整改" value="已整改" />
          <el-option label="合规" value="合规" />
          <el-option label="未发现风险" value="未发现风险" />
        </el-select>
      </div>
      <DemoBadge module="history" />
    </div>

    <el-card shadow="never" class="history-card">
      <div class="history-table-scroll">
        <el-table
          :data="paged"
          style="width: 100%; cursor: pointer"
          empty-text="无匹配记录"
          @row-click="onRowClick"
        >
          <el-table-column prop="id" label="编号" width="120">
            <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
          </el-table-column>
          <el-table-column prop="name" label="合同名称" min-width="200">
            <template #default="{ row }">
              <button type="button" class="contract-name" @click.stop="onRowClick(row)">{{ row.name }}</button>
            </template>
          </el-table-column>
          <el-table-column label="合规状态" width="110">
            <template #default="{ row }"><el-tag :type="statusType[row.status]" size="small" effect="plain">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column label="风险等级" width="110">
            <template #default="{ row }"><el-tag :type="levelType[row.level]" size="small">{{ row.level }}</el-tag></template>
          </el-table-column>
          <el-table-column label="风险候选" width="112" align="center">
            <template #default="{ row }"><span class="mono">{{ historyRiskCountLabel(row) }}</span></template>
          </el-table-column>
          <el-table-column prop="type" label="类型" width="150" />
          <el-table-column prop="submitter" label="提交人" width="90" />
          <el-table-column prop="time" label="导入时间" width="170">
            <template #default="{ row }"><span class="mono">{{ new Date(row.time).toLocaleString('zh-CN', { hour12: false }) }}</span></template>
          </el-table-column>
          <el-table-column width="44" align="center">
            <template #default>
              <el-icon class="row-arrow"><ArrowRight /></el-icon>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="table-footer">
        <span class="count mono">共 {{ filtered.length }} 条记录</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="filtered.length"
          layout="prev, pager, next"
          background
        />
      </div>
    </el-card>

    <!-- 风险详情抽屉 -->
    <el-drawer
      v-model="drawerOpen"
      :title="`风险详情 · ${drawerTitle}`"
      size="min(520px, 100vw)"
      direction="rtl"
    >
      <div v-loading="drawerLoading" style="min-height: 120px">
        <template v-if="!drawerLoading">
          <el-alert v-if="drawerError" :title="drawerError" type="error" :closable="false" show-icon />
          <el-alert v-else-if="!drawerComplete" title="结果不完整，尚无法判断整体风险" :description="`${coverageLabel} 已检出候选仅供人工核对，不能据此认定合同低风险或合规。`" type="warning" :closable="false" show-icon />
          <el-empty v-if="drawerComplete && !drawerError && !drawerRisks.length" description="本次完整审查未发现风险候选，仍需人工核对合同。" />
          <el-button v-if="drawerError" class="retry-button" @click="loadDetails">重试加载详情</el-button>
        </template>
        <article v-for="r in drawerRisks" :key="r.id" class="risk-item">
          <div class="risk-head">
            <el-tag :type="riskLevelType[r.level]" size="small">{{ riskLevelLabel[r.level] }}</el-tag>
            <el-tag size="small" effect="plain" type="info">{{ r.agent === 'legal' ? '法务' : r.agent === 'finance' ? '财务' : '系统' }}</el-tag>
            <b class="risk-cat">{{ r.category }}</b>
            <span class="conf mono">{{ riskEvidenceMeta(r).label }}</span>
          </div>
          <p class="risk-text">{{ r.original_text }}</p>
          <p class="risk-basis">依据：{{ r.basis }}</p>
          <p class="risk-suggest">建议：{{ r.suggestion }}</p>
          <div class="risk-footer">
            <el-tag
              size="small"
              :type="r.review_status === 'confirmed' ? 'success' : r.review_status === 'ignored' ? 'info' : 'warning'"
              effect="plain"
            >{{ reviewStatusLabel[r.review_status] ?? r.review_status }}</el-tag>
          </div>
        </article>
      </div>
      <!-- H2：底部跳转到审查页进行复核 -->
      <template #footer>
        <div class="detail-actions">
          <el-button v-if="canReadDocument" @click="annotationOpen = true">查看合同原文与批注</el-button>
          <el-button type="primary" :disabled="drawerLoading" @click="goAudit">前往审查页复核</el-button>
        </div>
      </template>
    </el-drawer>
    <AnnotationModal v-model="annotationOpen" :risks="drawerRisks" :filename="drawerTitle" :contract-id="selectedContractId" />
  </div>
</template>

<style scoped>
.history-page,
.history-card {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
.history-page {
  overflow-x: hidden;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.history-table-scroll {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
}
:deep(.history-card .el-card__body) {
  min-width: 0;
  overflow: hidden;
}
.table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}
.count {
  font-size: 12px;
  color: var(--muted);
}
.row-arrow {
  color: var(--muted);
  font-size: 13px;
  transition: color 0.15s ease;
}
.contract-name {
  border: 0;
  padding: 2px 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  overflow-wrap: anywhere;
  cursor: pointer;
}
.contract-name:hover { color: var(--brass); }
.contract-name:focus-visible {
  outline: 2px solid var(--brass);
  outline-offset: 3px;
  border-radius: 2px;
}
.detail-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.detail-actions .el-button + .el-button { margin-left: 0; }
.retry-button { margin-top: 12px; }
:deep(tr:hover) .row-arrow {
  color: var(--brass);
}
/* 风险详情抽屉 */
.risk-item {
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}
.risk-item:last-child { border-bottom: none; }
.risk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.risk-cat {
  font-size: 14px;
  color: var(--ivory);
}
.conf {
  font-size: 11px;
  color: var(--muted);
  margin-left: auto;
}
.risk-text {
  font-size: 12px;
  color: var(--ivory-dim);
  margin: 4px 0;
  line-height: 1.6;
  padding: 6px 8px;
  background: var(--ink-3);
  border-radius: var(--r-xs);
}
.risk-basis,
.risk-suggest {
  font-size: 12px;
  color: var(--ivory-dim);
  margin: 4px 0;
  line-height: 1.5;
}
.risk-footer {
  margin-top: 8px;
}</style>
