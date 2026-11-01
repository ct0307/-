<script setup lang="ts">
// 合同合规审查（真实接口核心闭环）：上传→解析→审查→复核→生成整改。
// 闭环逻辑迁移自 WorkbenchView，数据落 audit-session store。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, RefreshRight, View, WarningFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getLookups } from '@/api/admin'
import { getAuditStatus } from '@/api/contract'

import type { RiskOut } from '@/api/types'
import type { Handoff } from '@/api/handoffs'
import type { AuditBatchItem } from '@/api/batches'
import { useAuditSessionStore } from '@/stores/audit-session'
import { useRectifyStore } from '@/stores/rectify'
import { useNotifyStore } from '@/stores/notify'
import { useAuthStore } from '@/stores/auth'
import { useBatchStore } from '@/stores/batch'
import { useImportInboxStore } from '@/stores/import-inbox'
import ContractInbox from '@/components/audit/ContractInbox.vue'
import HandoffQueue from '@/components/audit/HandoffQueue.vue'
import RiskReviewDrawer from '@/components/audit/RiskReviewDrawer.vue'
import AnnotationModal from '@/components/audit/AnnotationModal.vue'
import {
  auditProgressDisplay,
  batchItemProgressDisplay,
  type AuditUiState,
} from '@/utils/audit-progress'
import { formatOcrConfidence, reviewStatusLabel } from '@/utils/ocr-quality'
import { riskEvidenceMeta, isEvidenceVerified } from '@/utils/risk-evidence'
import { batchTimingSummary, reviewReasonSummary } from '@/utils/professional-review'

const session = useAuditSessionStore()
const rectify = useRectifyStore()
const notify = useNotifyStore()
const auth = useAuthStore()
const batchStore = useBatchStore()
const auditSetup = ref<HTMLElement | null>(null)
const auditResults = ref<HTMLElement | null>(null)

async function focusAuditSection(target: 'setup' | 'results') {
  await nextTick()
  const element = target === 'setup' ? auditSetup.value : auditResults.value
  element?.focus({ preventScroll: true })
  element?.scrollIntoView({
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    block: 'start',
  })
}
const inbox = useImportInboxStore()
const route = useRoute()
const router = useRouter()

function isPollingCancellation(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const candidate = error as { name?: unknown; code?: unknown }
  return candidate.name === 'AbortError'
    || candidate.name === 'CanceledError'
    || candidate.code === 'ERR_CANCELED'
}

// 降级默认值（接口失败时兜底）
const _DEFAULT_DEPTS = ['采购中心', '销售部', '研发部', '法务部', '财务部', '人力资源部', '行政部', '运营部']
const _DEFAULT_CTYPES = ['软件开发外包合同', '技术服务合同', '采购合同', '销售合同', '劳动合同', '租赁合同', '保密协议', '合作协议']

const departmentOptions = ref<string[]>(_DEFAULT_DEPTS)
const contractTypeOptions = ref<string[]>(_DEFAULT_CTYPES)

const canChangeDepartment = computed(() => ['legal', 'finance', 'admin'].includes(auth.role))
const availableDepartments = computed(() => {
  const scoped = auth.role === 'admin'
    ? departmentOptions.value
    : canChangeDepartment.value
      ? auth.authorizedDepartments
      : [auth.department]
  return [...new Set([...scoped, ...inbox.batch?.items.map((item) => item.department) ?? []])]
    .filter(Boolean)
})

// mount 时从后端拉取管理员维护的选项列表；失败时静默降级到内置默认值
onMounted(async () => {
  try {
    const [depts, ctypes] = await Promise.all([
      getLookups('department'),
      getLookups('contract_type'),
    ])
    if (depts.length) departmentOptions.value = depts.map((d) => d.value)
    if (ctypes.length) contractTypeOptions.value = ctypes.map((c) => c.value)
  } catch {
    // 静默降级：保持内置默认值，不打断用户流程
  }
})

onMounted(async () => {
  if (route.query.contractId && !session.hasActiveAudit) return
  if (!session.hasActiveAudit) {
    try { await session.restoreCompletedAudit() }
    catch { ElMessage.error('上次审查结果恢复失败，请从审查历史重新选择') }
    return
  }
  try {
    const result = await session.resumeActiveAudit()
    if (!result) return
    ElMessage.success(`已恢复审查结果，检出 ${session.riskCount} 条风险`)
  } catch (error: unknown) {
    if (isPollingCancellation(error)) return
    ElMessage.error(error instanceof Error ? error.message : '审查任务恢复失败，请稍后重试')
  }
})

onMounted(async () => {
  const requestedImportId = Number(route.query.import)
  const importId = Number.isInteger(requestedImportId) && requestedImportId > 0
    ? requestedImportId
    : inbox.batch?.id
  if (!importId) return
  try {
    await inbox.resume(importId)
  } catch {
    ElMessage.error(inbox.error || '收件箱恢复失败')
  }
})

let batchRouteInitialized = false

watch(
  () => route.query.batch,
  async (value) => {
    const isInitialRoute = !batchRouteInitialized
    batchRouteInitialized = true
    const requestedBatchId = Number(value)
    const hasRequestedBatch = Number.isInteger(requestedBatchId) && requestedBatchId > 0
    if (!hasRequestedBatch && !isInitialRoute) {
      if (route.name === 'audit') batchStore.reset()
      return
    }
    const batchId = hasRequestedBatch ? requestedBatchId : batchStore.batch?.id
    if (!batchId) return
    try {
      await batchStore.resume(batchId)
    } catch {
      const currentRequestedBatchId = Number(route.query.batch)
      const currentBatchId = Number.isInteger(currentRequestedBatchId) && currentRequestedBatchId > 0
        ? currentRequestedBatchId
        : batchStore.batch?.id
      if (currentBatchId === batchId) {
        ElMessage.error(batchStore.error || '审查批次恢复失败')
      }
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  session.cancelCompletedAuditLoad()
  inbox.stopPolling()
  batchStore.stopPolling()
})

// 审查维度：勾选项传给后端，LLM 按维度聚焦输出
const dimensions = ref([
  { key: 'legal', label: '法律条款合规性', on: true },
  { key: 'risk', label: '风险条款识别', on: true },
  { key: 'payment', label: '金额与付款条款', on: true },
  { key: 'breach', label: '违约责任分析', on: true },
  { key: 'ip', label: '知识产权条款', on: true },
  { key: 'confidentiality', label: '保密条款审查', on: true },
  { key: 'termination', label: '终止与解除条款', on: true },
  { key: 'dispute', label: '争议解决条款', on: true },
])

async function uploadFiles(files: File[]) {
  try {
    const created = await inbox.create(files, auth.department)
    await router.replace({ query: { ...route.query, import: String(created.id) } })
    if (inbox.lastAddedCount > 0) {
      ElMessage.success(`已接收 ${inbox.lastAddedCount} 份合同`)
    } else {
      ElMessage.info('合同已在收件箱中，无需重复添加')
    }
  } catch {
    ElMessage.error(inbox.error || '合同导入失败，请稍后重试')
  }
}

async function confirmImportItem(itemId: number, contractType: string, department: string) {
  try {
    await inbox.confirm(itemId, contractType, department)
    ElMessage.success('合同信息已确认')
  } catch {
    ElMessage.error(inbox.error || '合同信息确认失败')
  }
}

async function retryImportItem(itemId: number) {
  try {
    await inbox.retry(itemId)
    ElMessage.success('已重新提交解析')
  } catch {
    ElMessage.error(inbox.error || '重新解析失败')
  }
}

async function removeImportRecord(itemId: number) {
  try {
    await inbox.removeRecord(itemId)
  } catch {
    ElMessage.error(inbox.error || '移出记录失败')
  }
}

async function deleteImportDraft(itemId: number) {
  try {
    await inbox.deleteDraft(itemId)
    ElMessage.success('合同草稿已移入回收站')
  } catch {
    ElMessage.error(inbox.error || '删除合同草稿失败')
  }
}

async function auditReadyItems() {
  if (!['legal', 'finance', 'admin'].includes(auth.role)) {
    ElMessage.warning('当前角色无权发起审查')
    return
  }
  const targetIds = [...inbox.auditTargetIds]
  if (!targetIds.length) return
  try {
    const created = await batchStore.createFromImport(
      targetIds,
      dimensions.value.filter((item) => item.on).map((item) => item.key),
    )
    await router.replace({ query: { ...route.query, batch: String(created.id) } })
    ElMessage.success(`已提交 ${created.total} 份合同`)
    await focusAuditSection('results')
    await inbox.startPolling()
  } catch {
    ElMessage.error(batchStore.error || '审查批次提交失败')
  }
}

async function reviewHandoff(row: Handoff) {
  if (session.busy || session.hasActiveAudit) {
    ElMessage.warning('请先完成当前审查任务')
    return
  }
  try {
    if (row.audit_job_id) {
      await session.loadCompletedAudit(row.contract_id, row.filename, row.audit_job_id)
    } else {
      session.reset()
      session.contractId = row.contract_id
      session.filename = row.filename
      await session.runAudit(row.contract_type, dimensions.value.filter(item => item.on).map(item => item.key))
    }
    ElMessage.success('已打开交接合同的审查结果')
    await nextTick()
    document.querySelector<HTMLElement>('[data-audit-detail]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '审查结果加载失败')
  }
}

const batchStatusLabel = {
  queued: '等待审查',
  running: '审查中',
  done: '已完成',
  review_required: '需人工复核',
  partial_failed: '部分失败',
  failed: '审查失败',
} as const

const batchItemStatusLabel = {
  queued: '等待中',
  parsing: '解析中',
  reviewing: '审查中',
  validating: '结果校验中',
  done: '已完成',
  review_required: '需人工复核',
  failed: '失败',
} as const

const batchItemStatusType = {
  queued: 'info',
  parsing: 'info',
  reviewing: 'info',
  validating: 'info',
  done: 'success',
  review_required: 'warning',
  failed: 'danger',
} as const

const legacyRetryableCodes = new Set([
  'MODEL_TIMEOUT',
  'MODEL_UNAVAILABLE',
  'AUDIT_PERSISTENCE_UNAVAILABLE',
  'OUTPUT_TRUNCATED',
  'INVALID_MODEL_OUTPUT',
  'PAGINATION_EXHAUSTED',
  'AUDIT_DEADLINE_EXCEEDED',
])

function batchFailureMessage(item: AuditBatchItem) {
  return item.error?.trim() || (item.status === 'failed' ? item.review_reason?.trim() : '') || ''
}

function isRetryableFailure(item: AuditBatchItem) {
  if (item.status !== 'failed') return false
  if (typeof item.retryable === 'boolean') return item.retryable
  return Boolean(item.error_code && legacyRetryableCodes.has(item.error_code))
}

const hasRetryableFailures = computed(() => {
  return batchStore.batch?.items.some(isRetryableFailure) ?? false
})

const batchProgressStatus = computed(() => {
  const batch = batchStore.batch
  if (!batch) return undefined
  if (batch.status === 'failed' || batch.status === 'partial_failed' || batch.failed > 0) {
    return 'exception'
  }
  if (batch.status === 'done') return 'success'
  if (batch.status === 'review_required') return 'warning'
  return undefined
})

function batchItemProgress(item: AuditBatchItem) {
  return batchItemProgressDisplay(item.progress, item.progress_stage, item.status)
}

async function retryAuditBatch() {
  try {
    const result = await batchStore.retry(
      dimensions.value.filter((item) => item.on).map((item) => item.key),
    )
    ElMessage.success(`已重新提交 ${result?.retried ?? 0} 个失败项`)
    await focusAuditSection('results')
    await inbox.startPolling()
  } catch {
    ElMessage.error(batchStore.error || '失败项重试失败')
  }
}

const openingContractId = ref<number | null>(null)

async function openBatchResult(contractId: number, filename: string, jobId: number) {
  openingContractId.value = contractId
  try {
    await session.loadCompletedAudit(contractId, filename, jobId)
    await nextTick()
    document.querySelector<HTMLElement>('[data-audit-detail]')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    const detail = error instanceof Error ? `：${error.message}` : ''
    ElMessage.error(`审查结果加载失败${detail}`)
  } finally {
    openingContractId.value = null
  }
}

// —— 维度关键词映射：用于判断风险条目属于哪个维度 ——
const _DIM_KEYWORDS: Record<string, string[]> = {
  legal:       ['合规', '法律', '主体', '资格', '效力', '合同主体'],
  risk:        ['风险条款', '风险识别'],
  payment:     ['金额', '付款', '价款', '结算', '发票', '币种', '预付', '要素缺失'],
  breach:      ['违约', '赔偿', '条款缺失'],
  ip:          ['知识产权', '著作权', '专利', '商标', '版权'],
  nda:         ['保密'],
  termination: ['终止', '解除'],
  dispute:     ['争议', '仲裁', '诉讼', '管辖'],
}

function _riskMatchesDim(risk: { category: string; basis: string }, dimKey: string): boolean {
  const kws = _DIM_KEYWORDS[dimKey] ?? []
  const text = risk.category + risk.basis
  return kws.some(kw => text.includes(kw))
}

function _isDimFocused(r: { category: string; basis: string; review_status: string }): boolean {
  if (_DONE_STATUS.has(r.review_status)) return false
  const active = dimensions.value.filter(d => d.on)
  if (active.length === dimensions.value.length) return false // 全选时不突出
  return active.some(d => _riskMatchesDim(r, d.key))
}

// —— 风险排序：先按"是否命中勾选维度"分组，组内 high→medium→low，已处理沉底 ——
const _LEVEL_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 }
const _DONE_STATUS = new Set(['confirmed', 'ignored'])
const sortedRisks = computed(() => {
  const activeDimKeys = dimensions.value.filter(d => d.on).map(d => d.key)
  const allSelected = activeDimKeys.length === dimensions.value.length

  function score(r: typeof session.risks[0]) {
    const done = _DONE_STATUS.has(r.review_status) ? 100 : 0
    // 全选时不区分；否则命中优先
    const dimBonus = (!allSelected && activeDimKeys.some(k => _riskMatchesDim(r, k))) ? 0 : 10
    return done + dimBonus + (_LEVEL_ORDER[r.level] ?? 9)
  }

  return [...session.risks].sort((a, b) => score(a) - score(b))
})

// —— 复核抽屉 ——
const drawerOpen = ref(false)
const annotationOpen = ref(false)
const selectedContext = ref<{ id: number; filename: string; message: string } | null>(null)

watch(() => [route.query.contractId, route.query.jobId] as const, async ([rawId, rawJobId], _, onCleanup) => {
  const id = Number(rawId)
  if (!Number.isInteger(id) || id <= 0) { selectedContext.value = null; return }
  if (session.busy || session.hasActiveAudit) {
    ElMessage.warning('请先完成当前审查任务，再切换合同')
    return
  }
  const request = new AbortController()
  onCleanup(() => {
    request.abort()
    session.cancelCompletedAuditLoad()
  })
  const filename = typeof route.query.filename === 'string' ? route.query.filename : `合同 ${id}`
  selectedContext.value = { id, filename, message: '正在读取所选合同的审查状态…' }
  session.reset()
  session.contractId = id
  session.filename = filename
  const requestedJob = Number(rawJobId)
  try {
    const result = await getAuditStatus(id, Number.isInteger(requestedJob) && requestedJob > 0 ? requestedJob : undefined, request.signal)
    if (request.signal.aborted) return
    if (result.job_id && ['done', 'review_required'].includes(result.status)) {
      await session.loadCompletedAudit(id, filename, result.job_id)
      if (!request.signal.aborted) selectedContext.value = null
    } else if (result.batch_id) {
      await router.replace({ path: '/audit', query: { batch: String(result.batch_id) } })
    } else {
      selectedContext.value = { id, filename, message: '该合同尚无完整审查结果，可先核对原文。' }
    }
  } catch (error) {
    if (!request.signal.aborted) selectedContext.value = { id, filename,
      message: error instanceof Error ? `状态读取失败：${error.message}` : '状态读取失败，请从历史记录重试。' }
  }
}, { immediate: true })
const activeRisk = ref<RiskOut | null>(null)
function openReview(risk: RiskOut) {
  activeRisk.value = risk
  drawerOpen.value = true
}

async function confirmRisk(risk: RiskOut) {
  try {
    const { value: comment } = await ElMessageBox.prompt('请记录确认该风险的依据、处置判断或复核范围', '填写人工复核意见', {
      inputType: 'textarea', inputPlaceholder: '至少说明你核对了什么以及为何确认', inputValidator: value => !!value?.trim() || '复核意见不能为空',
      confirmButtonText: '提交确认', cancelButtonText: '取消',
    })
    await session.setRiskStatus(risk, 'confirmed', comment)
    // 跨模块联动：生成整改项 + 推通知
    await rectify.addFromRisk(risk, session.filename || '当前合同', auth.username)
    notify.push('rectify', '生成整改项', `已就"${risk.category}"生成整改项，进入整改跟踪。`)
    ElMessage.success('已确认并生成整改项')
    drawerOpen.value = false
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('操作失败')
  }
}

async function ignoreRisk(risk: RiskOut) {
  try {
    const { value: comment } = await ElMessageBox.prompt('请说明为何判断为误报或无需处理', '填写人工复核意见', {
      inputType: 'textarea', inputPlaceholder: '至少说明误报依据或排除理由', inputValidator: value => !!value?.trim() || '复核意见不能为空',
      confirmButtonText: '提交误报', cancelButtonText: '取消',
    })
    await session.setRiskStatus(risk, 'ignored', comment)
    ElMessage.success('已标记为误报')
    drawerOpen.value = false
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('操作失败')
  }
}

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}
const statusLabel: Record<string, string> = {
  pending: '待复核',
  confirmed: '已确认',
  ignored: '已忽略',
  to_modify: '需修改',
}
const elementLabels: Record<string, string> = {
  party_a: '甲方',
  party_b: '乙方',
  amount: '合同金额',
  sign_date: '签订日期',
  duration: '履约期限',
  subject: '合同标的',
  payment_terms: '收付款节点',
}

// 3 步引导数据
const onboardSteps = [
  { num: '1', title: '上传合同', desc: '支持 PDF / Word / TXT，文件存入当前部署环境' },
  { num: '2', title: '确认信息', desc: '逐份核对合同类型与归属部门' },
  { num: '3', title: '人工复核 / 生成整改', desc: '确认风险条款，自动生成整改跟踪项' },
]
</script>

<template>
  <div class="audit-page">
    <section ref="auditSetup" class="audit-setup" tabindex="-1" aria-label="审查设置">
      <ContractInbox
        :items="inbox.batch?.items ?? []"
        :contract-types="contractTypeOptions"
        :departments="availableDepartments"
        :selected-ids="inbox.selectedIds"
        :ready-ids="inbox.readyIds"
        :all-ready-selected="inbox.allReadySelected"
        :some-ready-selected="inbox.someReadySelected"
        :can-change-department="canChangeDepartment"
        :can-review="['legal', 'finance', 'admin'].includes(auth.role)"
        :loading="inbox.loading || batchStore.loading"
        @upload="uploadFiles"
        @confirm="confirmImportItem"
        @retry="retryImportItem"
        @remove-record="removeImportRecord"
        @delete-draft="deleteImportDraft"
        @toggle-selected="inbox.toggleSelected"
        @toggle-all-ready="inbox.toggleAllReady"
        @audit-ready="auditReadyItems"
      />
    </section>

    <!-- 既有单份审查结果继续保留，历史会话恢复后仍可复核和生成整改。 -->
    <section ref="auditResults" class="right-stack" tabindex="-1" aria-label="智能审查结果">
      <el-card shadow="never" class="result-panel">
        <template #header>
          <div class="result-panel-header">
            <span class="panel-title">智能审查结果</span>
            <el-button v-if="batchStore.batch" text @click="focusAuditSection('setup')">返回审查设置</el-button>
          </div>
        </template>
        <section
          v-if="batchStore.batch"
          class="batch-result"
          role="region"
          :aria-label="`审查批次 ${batchStore.batch.id}`"
        >
          <div class="batch-result-head">
            <div>
              <span class="eyebrow mono">批次 #{{ batchStore.batch.id }}</span>
              <h2>{{ batchStatusLabel[batchStore.batch.status] }}</h2>
            </div>
            <el-button
              v-if="hasRetryableFailures"
              :icon="RefreshRight"
              :loading="batchStore.loading"
              @click="retryAuditBatch"
            >重试失败项</el-button>
          </div>
          <p class="batch-feedback">机器处理进度（100% 不代表人工复核完成）</p>
          <el-progress
            class="batch-result-progress"
            :percentage="batchStore.progress"
            :status="batchProgressStatus"
          />
          <p class="batch-summary mono" role="status" aria-live="polite">
            机器已处理 {{ batchStore.batch.completed }} / {{ batchStore.batch.total }}，失败 {{ batchStore.batch.failed }}
          </p>
          <p class="batch-feedback">人工复核以各风险的复核记录为准。</p>
          <p v-if="['queued', 'running'].includes(batchStore.batch.status)" class="batch-feedback">
            任务已提交，进度将自动更新。可以离开页面，稍后返回查看。
          </p>
          <p v-else-if="batchStore.batch.failed > 0" class="batch-feedback">
            失败合同尚未完成有效审查，请按下方原因处理后重新提交。
          </p>
          <p v-else class="batch-feedback">请选择下方合同查看结果，并核对需人工复核的内容。</p>
          <div class="batch-result-items">
            <div
              v-for="item in batchStore.batch.items"
              :key="item.id"
              class="batch-result-item"
              :class="{ 'is-failed': item.progress_stage === 'failed' }"
            >
              <div class="batch-result-item-top">
                <div class="batch-result-item-main">
                  <strong>{{ item.filename }}</strong>
                  <template v-if="item.status === 'failed'">
                    <span class="batch-result-item-error">
                      {{ batchFailureMessage(item) || '审查未能生成完整可靠结果' }}
                    </span>
                    <span v-if="item.error_code" class="batch-result-item-code mono">
                      错误码：{{ item.error_code }}
                    </span>
                    <span v-if="item.error_action" class="batch-result-item-action-hint">
                      {{ item.error_action }}
                    </span>
                  </template>
                  <template v-else-if="item.status === 'review_required' && item.review_reason">
                    <span class="batch-result-item-review-reason">{{ reviewReasonSummary(item.review_reason) }}</span>
                    <details v-if="reviewReasonSummary(item.review_reason) !== item.review_reason" class="batch-review-details">
                      <summary>完整复核说明</summary>
                      <p>{{ item.review_reason }}</p>
                    </details>
                  </template>
                  <span v-if="batchTimingSummary(item)" class="batch-result-item-timing">{{ batchTimingSummary(item) }}</span>
                </div>
                <div class="batch-result-item-meta">
                  <el-tag :type="batchItemStatusType[item.status]" size="small">
                    {{ batchItemStatusLabel[item.status] }}
                  </el-tag>
                  <el-button
                    v-if="item.status === 'done' || item.status === 'review_required'"
                    class="batch-result-item-action"
                    type="primary"
                    plain
                    :icon="View"
                    :loading="openingContractId === item.contract_id"
                    :disabled="openingContractId !== null && openingContractId !== item.contract_id"
                    :aria-label="`查看 ${item.filename} 的审查结果`"
                    @click="openBatchResult(item.contract_id, item.filename, item.id)"
                  >
                    查看审查结果
                  </el-button>
                </div>
              </div>
              <div class="batch-result-item-progress-row">
                <el-progress
                  class="batch-result-item-progress"
                  :percentage="batchItemProgress(item).percentage ?? 0"
                  :status="item.progress_stage === 'failed'
                    ? 'exception'
                    : item.status === 'review_required'
                      ? 'warning'
                    : item.progress_stage === 'completed'
                      ? 'success'
                      : undefined"
                  :show-text="false"
                />
                <span class="batch-result-item-stage">{{ batchItemProgress(item).label }}</span>
                <span class="batch-result-item-percentage mono">{{ batchItemProgress(item).percentage }}%</span>
              </div>
            </div>
          </div>
        </section>
        <!-- 3 步引导：未上传 / 已上传未审查时显示，代替纯文字空状态 -->
        <div v-if="session.step < 2 && !batchStore.batch" class="onboard">
          <div
            v-for="(step, i) in onboardSteps"
            :key="step.num"
            class="onboard-step"
            :class="{ done: session.step > i, active: session.step === i }"
          >
            <div class="step-num">{{ step.num }}</div>
            <div class="step-body">
              <b>{{ step.title }}</b>
              <p>{{ step.desc }}</p>
            </div>
            <div v-if="i < onboardSteps.length - 1" class="step-arrow">→</div>
          </div>
        </div>

        <template v-if="session.step >= 2">
          <div class="result-head" data-audit-detail>
            <div>
              <span class="eyebrow mono">当前查看</span>
              <h2>{{ session.filename }}</h2>
            </div>
            <el-button v-if="['legal', 'finance', 'admin'].includes(auth.role)" :icon="'Document'" @click="annotationOpen = true">查看合同原文与批注</el-button>
          </div>

          <div v-if="session.requiresReview" class="ocr-review-alert" role="alert">
            <el-icon><WarningFilled /></el-icon>
            <div>
              <strong>审查结果需人工复核</strong>
              <p>
                {{ session.reviewReason || '请核对解析质量、风险依据及适用条件' }}
                <span v-if="session.ocrConfidence != null"> · OCR 置信度 {{ formatOcrConfidence(session.ocrConfidence) }}</span>
              </p>
            </div>
          </div>

          <div class="result-kpis">
            <div class="kpi-mini">
              <span>审查状态</span>
              <strong class="mono">{{ session.requiresReview ? '待人工复核' : '机器处理完成' }}</strong>
            </div>
            <div class="kpi-mini">
              <span>风险数量</span><strong class="mono">{{ session.riskCount }}</strong>
            </div>
            <div class="kpi-mini">
              <span>待复核</span><strong class="mono">{{ session.reviewingCount }}</strong>
            </div>
            <div class="kpi-mini">
              <span>高风险</span><strong class="mono seal-num">{{ session.levelCounts.high }}</strong>
            </div>
          </div>

          <div class="result-two-col" :class="{ 'single-col': !session.elements }">
            <section class="result-col">
              <div class="col-head"><h2>风险清单</h2><el-tag type="danger" size="small">{{ session.riskCount }} 条</el-tag></div>
              <div class="risk-list">
                <el-empty
                  v-if="session.risks.length === 0"
                  :image-size="72"
                  :description="session.requiresReview ? '审查结果不完整，暂不能据此判断合同无风险' : '该合同未检出风险'"
                />
                <article
                  v-for="r in sortedRisks"
                  :key="r.id"
                  class="risk-card"
                  :class="[
                    `lvl-${r.level}`,
                    { reviewed: _DONE_STATUS.has(r.review_status) },
                    { 'dim-focus': _isDimFocused(r) }
                  ]"
                  @click="openReview(r)"
                  role="button"
                  tabindex="0"
                  :aria-label="`复核风险：${r.category}`"
                  @keydown.enter.prevent="openReview(r)"
                  @keydown.space.prevent="openReview(r)"
                >
                  <div class="risk-head">
                    <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}风险</el-tag>
                    <span class="risk-cat">{{ r.category }}</span>
                    <el-tag size="small" effect="plain" class="status-tag">{{ statusLabel[r.review_status] }}</el-tag>
                  </div>
                  <p class="risk-line">{{ reviewReasonSummary(r.risk_reason || r.suggestion) }}</p>
                  <div class="risk-evidence" :class="{ 'is-missing': !isEvidenceVerified(r) }">
                    <span class="evidence-dot" />
                    <span>
                      {{ riskEvidenceMeta(r).label }}
                      <template v-if="r.rag_sources?.length">· {{ r.rag_sources.length }} 条来源</template>
                    </span>
                  </div>
                  <span class="review-cta">
                    {{ _DONE_STATUS.has(r.review_status) ? '查看详情' : '进入复核' }}
                    <el-icon><ArrowRight /></el-icon>
                  </span>
                </article>
              </div>
            </section>
            <section v-if="session.elements" class="result-col">
              <div class="col-head"><h2>合同关键要素</h2></div>
              <dl class="metadata-list">
                <template v-for="(label, key) in elementLabels" :key="key">
                  <dt>{{ label }}</dt>
                  <dd v-if="session.elements?.[key]">{{ session.elements[key] }}</dd>
                  <dd v-else class="warn">未检出</dd>
                </template>
              </dl>
            </section>
          </div>
        </template>
      </el-card>
    </section>

    <section v-if="selectedContext" class="selected-context" role="region" aria-label="所选合同">
      <div><strong>{{ selectedContext.filename }}</strong><p>{{ selectedContext.message }}</p></div>
      <el-button v-if="['legal', 'finance', 'admin'].includes(auth.role)" @click="annotationOpen = true">查看所选合同原文</el-button>
    </section>
    <HandoffQueue @review="reviewHandoff" />

    <RiskReviewDrawer
      v-model="drawerOpen"
      :risk="activeRisk"
      @confirm="confirmRisk"
      @ignore="ignoreRisk"
    />
    <AnnotationModal v-model="annotationOpen" :risks="session.risks" :filename="session.filename" :contract-id="session.contractId" />

  </div>
</template>

<style scoped>
.selected-context { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; padding: 16px; border: 1px solid var(--line); border-radius: var(--r-md); background: var(--ink-2); }
.selected-context p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.risk-card:focus-visible { outline: 2px solid var(--brass); outline-offset: 3px; }
.audit-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.left-stack {
  display: flex;
  flex-direction: column;
  gap: 0;
  position: sticky;
  top: 0;
}
.upload-panel {
  border-radius: var(--r-lg) var(--r-lg) 0 0;
  border-bottom: 0;
}
.config-panel {
  border-radius: 0 0 var(--r-lg) var(--r-lg);
}
.right-stack,
.result-panel {
  min-width: 0;
}
.result-panel {
  min-height: 0;
}
.audit-setup, .right-stack { scroll-margin-top: 20px; }
.audit-setup:focus-visible, .right-stack:focus-visible { outline: 2px solid var(--brass); outline-offset: 3px; }
.result-panel-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.batch-feedback { color: var(--muted); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.batch-result {
  margin: -4px 0 20px;
  padding: 14px 0 18px;
  border-bottom: 1px solid var(--line);
}
.batch-result-head,
.batch-result-item-top {
  display: flex;
  align-items: center;
  gap: 12px;
}
.batch-result-head {
  justify-content: space-between;
  margin-bottom: 12px;
}
.batch-result-head h2 {
  margin: 3px 0 0;
  font-size: 18px;
}
.batch-result-items {
  margin-top: 10px;
  border-top: 1px solid var(--line);
}
.batch-result-item {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.batch-result-item-top {
  justify-content: space-between;
  min-width: 0;
}
.batch-result-item-main {
  flex: 1;
  min-width: 0;
}
.batch-result-item-main strong,
.batch-result-item-error,
.batch-result-item-review-reason {
  display: block;
  overflow-wrap: anywhere;
}
.batch-result-item-code,
.batch-result-item-action-hint {
  display: block;
  margin-top: 3px;
  overflow-wrap: anywhere;
  font-size: 11px;
  line-height: 1.45;
}
.batch-result-item-code { color: var(--muted); }
.batch-result-item-action-hint { color: var(--amber); }
.batch-result-item-main strong {
  font-size: 13px;
}
.batch-result-item-error {
  margin-top: 3px;
  color: var(--seal);
  font-size: 12px;
}
.batch-result-item-review-reason {
  margin-top: 3px;
  color: var(--amber);
  font-size: 12px;
  line-height: 1.5;
}
.batch-review-details {
  margin-top: 5px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.batch-review-details summary { cursor: pointer; color: var(--brass); }
.batch-review-details p { margin: 5px 0 0; }
.batch-result-item-timing {
  display: block;
  margin-top: 5px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.batch-result-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.batch-result-item-action {
  min-width: 118px;
}
.batch-result-item-progress-row {
  display: grid;
  grid-template-columns: minmax(96px, 1fr) auto 4ch;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.batch-result-item-progress {
  min-width: 0;
}
.batch-result-item-stage,
.batch-result-item-percentage {
  font-size: 12px;
  line-height: 1.4;
}
.batch-result-item-stage {
  color: var(--muted);
  overflow-wrap: anywhere;
}
.batch-result-item-percentage {
  width: 4ch;
  color: var(--brass);
  text-align: right;
}
.batch-result-item.is-failed .batch-result-item-stage,
.batch-result-item.is-failed .batch-result-item-percentage {
  color: var(--seal);
}
.upload-panel :deep(.el-upload-dragger) {
  min-height: 156px;
  padding: 34px 16px 24px;
  border-radius: var(--r-sm);
  background: var(--ink-3);
}
.upload-panel :deep(.el-icon--upload) {
  color: var(--info);
}
.upload-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.filename {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  font-size: 12px;
  color: var(--ivory-dim);
}
.filename-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.filename-cancel { flex: none; opacity: 0.6; }
.filename-cancel:hover { opacity: 1; }
.filename .icon-ok {
  color: var(--sage);
}
.filename.pending {
  color: var(--muted);
}
.upload-records {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.upload-records-title {
  margin-bottom: 8px;
  color: var(--ivory-dim);
  font-size: 12px;
  font-weight: 600;
}
.upload-record-empty {
  color: var(--muted);
  font-size: 12px;
}
.upload-record-row {
  position: relative;
  min-width: 0;
  padding: 8px 0;
  border-top: 1px solid var(--line);
}
.upload-record-row:first-of-type {
  border-top: 0;
}
.upload-record-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}
.upload-record-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--ivory-dim);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.upload-record-error {
  margin: 6px 34px 0 0;
  color: var(--seal);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.upload-record-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}
.form-grid {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
}
.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--ivory-dim);
}
.required-mark,
.field-error {
  color: var(--seal);
}
.field-error,
.field-warning,
.field-hint {
  font-size: 12px;
  line-height: 1.4;
}
.field-warning {
  color: var(--amber);
}
.field-hint {
  color: var(--muted);
}
/* 归属部门只读展示 */
.dept-readonly {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  background: var(--ink-3);
  border-radius: var(--r-sm);
  font-size: 13px;
  color: var(--ivory);
  border: 1px solid var(--line);
}
.dept-hint {
  font-size: 11px;
  color: var(--muted);
}
/* 维度折叠区 */
.dim-collapse {
  margin-bottom: 14px;
}
.dim-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: none;
  border-top: 1px solid var(--line);
  padding: 12px 0 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--ivory-dim);
  text-align: left;
}
.dim-toggle:hover { color: var(--ivory); }
.dim-summary { font-size: 12px; color: var(--brass); }
.dim-hint {
  margin-left: auto;
  max-width: 150px;
  font-size: 11px;
  color: var(--muted);
  font-style: italic;
}
.check-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  padding: 8px 0 4px;
}
.run-btn {
  width: 100%;
}
.abort-btn {
  margin-top: 8px;
  color: var(--seal);
  border-color: var(--seal);
}
.audit-progress-wrap {
  margin-top: 12px;
}
.audit-progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
}
.audit-progress-label { color: var(--ivory-dim); font-family: var(--serif); }
.audit-progress-pct   { color: var(--brass); }
.audit-progress-track {
  height: 6px;
  background: var(--ink-3);
  border-radius: 3px;
  overflow: hidden;
}
.audit-progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.2s ease;
  background: var(--brass);
}
.audit-progress-fill.indeterminate {
  width: 36%;
  animation: audit-indeterminate 1.2s ease-in-out infinite;
}
.audit-progress-fill.done   { background: var(--sage); }
.audit-progress-fill.failed { background: var(--seal); }
@keyframes audit-indeterminate {
  from { transform: translateX(-110%); }
  to { transform: translateX(310%); }
}
@media (prefers-reduced-motion: reduce) {
  .audit-progress-fill.indeterminate {
    width: 100%;
    animation: none;
    opacity: 0.55;
  }
}
.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.result-head h2 {
  margin: 2px 0 0;
  font-size: 18px;
}
.eyebrow {
  font-size: 11px;
  color: var(--brass);
  letter-spacing: 0;
}
.result-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  margin: 0 0 20px;
  border-bottom: 1px solid var(--line);
}
.kpi-mini {
  min-width: 0;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-right: 1px solid var(--line);
}
.kpi-mini:last-child {
  border-right: 0;
}
.kpi-mini span {
  font-size: 12px;
  color: var(--ivory-dim);
}
.kpi-mini strong {
  font-size: 22px;
  color: var(--ivory);
}
.seal-num {
  color: var(--seal);
}
.result-two-col {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(260px, 1fr);
  gap: 24px;
}
.result-two-col.single-col {
  grid-template-columns: minmax(0, 1fr);
}
.result-col + .result-col {
  padding-left: 24px;
  border-left: 1px solid var(--line);
}
.col-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ivory);
  letter-spacing: 0;
  font-family: var(--serif);
}
.col-head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ivory);
}
.risk-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
/* 3 步引导 */
.onboard {
  display: flex;
  align-items: stretch;
  gap: 0;
  padding: 36px 24px;
  min-height: 220px;
  border-bottom: 1px solid var(--line);
}
.onboard-step {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex: 1;
  max-width: none;
  opacity: 0.45;
  transition: opacity 0.2s ease;
  position: relative;
  padding-right: 28px;
}
.onboard-step.active { opacity: 1; }
.onboard-step.done   { opacity: 0.7; }
.step-num {
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: var(--r-sm);
  border: 1px solid var(--brass);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: var(--brass);
  font-family: var(--mono);
}
.onboard-step.done .step-num {
  background: var(--brass);
  color: var(--ink);
}
.step-body { flex: 1; padding-top: 4px; }
.step-body b {
  display: block;
  font-size: 13px;
  color: var(--ivory);
  margin-bottom: 4px;
}
.step-body p {
  margin: 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.5;
}
.step-arrow {
  position: absolute;
  right: 12px;
  top: 8px;
  color: var(--brass);
  font-size: 16px;
  opacity: 0.5;
}
/* 已复核（confirmed/ignored）的风险卡片：透明度降低，视觉退后 */
.risk-card.reviewed {
  opacity: 0.5;
  background: var(--ink-3);
}
/* 命中用户关注维度的卡片：左侧加亮铜色竖线强调 */
.risk-card.dim-focus {
  border-color: var(--brass);
  background: var(--brass-soft);
}
.risk-card {
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: 13px 14px 12px 16px;
  cursor: pointer;
  /* 仅过渡必要属性，避免 GPU 处理所有 CSS 变化 */
  transition: border-color 0.2s var(--ease), box-shadow 0.2s var(--ease);
  position: relative;
}
.risk-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: var(--r-sm) 0 0 var(--r-sm);
}
.risk-card.lvl-high::before {
  background: var(--seal);
}
.risk-card.lvl-medium::before {
  background: var(--amber);
}
.risk-card.lvl-low::before {
  background: var(--sage);
}
.risk-card:hover {
  border-color: var(--line-strong);
  background: var(--ink-3);
}
.risk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.risk-cat {
  font-weight: 600;
  color: var(--ivory);
}
.status-tag {
  margin-left: auto;
}
.risk-line {
  margin: 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.6;
}
.risk-evidence {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
  color: var(--sage);
  font-size: 11px;
  font-weight: 600;
}
.risk-evidence.is-missing {
  color: var(--amber);
}
.evidence-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex: none;
}
.risk-confidence {
  margin-left: auto;
  color: var(--muted);
  font-weight: 500;
}
.review-cta {
  font-size: 12px;
  color: var(--brass);
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.review-cta .el-icon { font-size: 13px; }
.metadata-list {
  margin: 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0;
  font-size: 13px;
  border-top: 1px solid var(--line);
}
.metadata-list dt {
  color: var(--ivory-dim);
  padding: 9px 12px 9px 0;
  border-bottom: 1px solid var(--line);
}
.metadata-list dd {
  margin: 0;
  color: var(--ivory);
  font-family: var(--mono);
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
  overflow-wrap: anywhere;
}
.metadata-list dd.warn {
  color: var(--seal);
}
@media (max-width: 1180px) {
  .audit-grid {
    grid-template-columns: 1fr;
  }
  .left-stack { position: static; }
  .result-two-col {
    grid-template-columns: 1fr;
  }
  .result-col + .result-col {
    padding: 20px 0 0;
    border-left: 0;
    border-top: 1px solid var(--line);
  }
  .result-panel { min-height: 0; }
}
.batch-btn {
  width: 100%;
  margin-top: 10px;
}
.batch-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 280px;
  overflow-y: auto;
}
.batch-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--ink-3);
  border-radius: var(--r-sm);
  font-size: 12px;
}
.batch-name {
  flex: 1;
  color: var(--ivory-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.batch-tag { flex: none; }
.batch-error {
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ocr-review-alert {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin: 16px 0 0;
  padding: 12px 14px;
  color: var(--amber);
  background: var(--amber-soft);
  border-top: 1px solid var(--amber);
  border-bottom: 1px solid var(--amber);
}
.ocr-review-alert > .el-icon {
  flex: none;
  margin-top: 2px;
  font-size: 18px;
}
.ocr-review-alert > div {
  min-width: 0;
}
.ocr-review-alert strong {
  display: block;
  color: var(--ivory);
  font-size: 14px;
}
.ocr-review-alert p {
  margin: 3px 0 0;
  color: var(--ivory-dim);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.failed-item { background: var(--seal-soft) !important; }
.batch-progress {
  padding: 8px 2px 2px;
}
.batch-summary {
  font-size: 12px;
  color: var(--muted);
  text-align: right;
  padding-top: 4px;
}
@media (max-width: 640px) {
  .batch-result-head {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .batch-result-item-top {
    align-items: flex-start;
    flex-direction: column;
  }
  .batch-result-item-main,
  .batch-result-item-meta {
    width: 100%;
  }
  .batch-result-item-meta {
    flex-wrap: wrap;
    justify-content: space-between;
  }
  .batch-result-item-action {
    width: 100%;
  }
  .batch-result-item-progress-row {
    grid-template-columns: minmax(0, 1fr) 4ch;
  }
  .batch-result-item-stage {
    grid-column: 1;
    white-space: normal;
  }
  .batch-result-item-percentage {
    grid-column: 2;
    grid-row: 1 / span 2;
    align-self: center;
  }
  .onboard {
    flex-direction: column;
    min-height: 0;
    padding: 20px 16px;
    gap: 16px;
  }
  .onboard-step {
    width: 100%;
    padding-right: 0;
  }
  .step-arrow { display: none; }
  .result-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .result-kpis {
    grid-template-columns: 1fr 1fr;
  }
  .kpi-mini:nth-child(2) { border-right: 0; }
  .kpi-mini:nth-child(-n + 2) { border-bottom: 1px solid var(--line); }
  .risk-head { flex-wrap: wrap; }
  .status-tag { margin-left: 0; }
  .dim-toggle { flex-wrap: wrap; }
  .dim-hint {
    margin-left: 0;
    max-width: none;
    flex-basis: 100%;
  }
  .ocr-review-alert {
    align-items: flex-start;
    padding: 12px;
  }
  .ocr-review-alert p {
    max-width: 100%;
  }
}
</style>
