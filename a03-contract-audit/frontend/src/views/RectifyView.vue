<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRectifyStore, type Rectification, type RectifyStatus } from '@/stores/rectify'
import { useAuthStore } from '@/stores/auth'
import { getRectificationMaterials } from '@/api/rectify'
import { uploadContract } from '@/api/contract'
import type { RectificationMaterial, RectificationPlan, RectificationUpdate } from '@/mock/rectify'
import RectificationPlanDialog from '@/components/rectify/RectificationPlanDialog.vue'
import AnnotationModal from '@/components/audit/AnnotationModal.vue'

type ViewFilter = '未闭环' | '已逾期' | '即将到期' | '高风险未闭环' | '全部' | RectifyStatus

const rectify = useRectifyStore()
const auth = useAuthStore()
const router = useRouter()
const filter = ref<ViewFilter>('未闭环')
const keyword = ref('')
const page = ref(1)
const pageSize = 10
const changing = ref<Set<string>>(new Set())
const drawerOpen = ref(false)
const activeId = ref('')
const resolutionDraft = ref('')
const reviewDraft = ref('')
const lastLoadedAt = ref('')
const evidenceIds = ref<number[]>([])
const afterText = ref('')
const acceptanceReason = ref('')
const residualRisk = ref('')
const materials = ref<RectificationMaterial[]>([])
const materialsLoading = ref(false)
const materialsError = ref('')
const uploading = ref(false)
const planOpen = ref(false)
const planSaving = ref(false)
const planError = ref('')
const documentOpen = ref(false)
const documentId = ref<number | null>(null)
const documentFilename = ref('')
let materialsGeneration = 0
const professional = computed(() => ['legal', 'finance', 'admin'].includes(auth.role))
const canManage = (item: Rectification) => professional.value && (item.can_manage ?? true)
const canExecute = (item: Rectification) => item.owner === auth.username && (item.can_execute ?? true)
const isIndependent = (item: Rectification) => item.owner !== auth.username && item.submitted_by !== auth.username
const canReview = (item: Rectification) => professional.value && isIndependent(item) && (item.can_review ?? true)
const canAccept = (item: Rectification) => auth.role === 'admin' && isIndependent(item) && (item.can_accept ?? true)
const canReopen = (item: Rectification) => professional.value && (item.can_reopen ?? Boolean(item.contract_id))
const canEscalate = (item: Rectification) => (professional.value || canExecute(item)) && (item.can_escalate ?? true)
const planComplete = (item: Rectification) => Boolean(item.owner && item.due && item.note?.trim() && item.acceptance_criteria?.trim() && item.contract_stage && item.handling_method)

async function refresh(force = false) {
  await rectify.load(force)
  if (!rectify.error) {
    lastLoadedAt.value = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(new Date())
  }
}

onMounted(() => refresh())

const dateOnly = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const today = () => dateOnly(new Date())
const addDays = (value: string, days: number) => {
  const date = new Date(`${value}T00:00:00`)
  date.setDate(date.getDate() + days)
  return dateOnly(date)
}
const isOpen = (item: Rectification) => !['已闭环', '已接受风险'].includes(item.status)
const isOverdue = (item: Rectification) => isOpen(item) && Boolean(item.due) && item.due < today()
const isDueSoon = (item: Rectification) => isOpen(item) && Boolean(item.due)
  && item.due >= today() && item.due <= addDays(today(), 3)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  let list: Rectification[]
  if (filter.value === '全部') list = rectify.items
  else if (filter.value === '未闭环') list = rectify.items.filter(isOpen)
  else if (filter.value === '已逾期') list = rectify.items.filter(isOverdue)
  else if (filter.value === '即将到期') list = rectify.items.filter(isDueSoon)
  else if (filter.value === '高风险未闭环') {
    list = rectify.items.filter((item) => isOpen(item) && item.level === 'high')
  } else list = rectify.items.filter((item) => item.status === filter.value)
  if (kw) {
    list = list.filter((item) => [item.id, item.contract, item.risk, item.owner, item.note]
      .some((value) => value?.toLowerCase().includes(kw)))
  }
  return [...list].sort((a, b) => {
    if (isOverdue(a) !== isOverdue(b)) return isOverdue(a) ? -1 : 1
    const levelOrder = { high: 0, medium: 1, low: 2 }
    return levelOrder[a.level] - levelOrder[b.level] || a.due.localeCompare(b.due)
  })
})
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const activeItem = computed(() => rectify.items.find((item) => item.id === activeId.value) ?? null)
const overdueCount = computed(() => rectify.items.filter(isOverdue).length)
const dueSoonCount = computed(() => rectify.items.filter(isDueSoon).length)
const highOpenCount = computed(() => rectify.items.filter((item) => isOpen(item) && item.level === 'high').length)

const levelMeta = {
  high: { label: '高风险', type: 'danger' as const },
  medium: { label: '中风险', type: 'warning' as const },
  low: { label: '低风险', type: 'info' as const },
}
const statusType: Record<RectifyStatus, 'info' | 'warning' | 'primary' | 'success'> = {
  待处理: 'info', 处理中: 'warning', 待复核: 'primary', 已闭环: 'success', 待风险接受: 'warning', 已接受风险: 'warning',
}
const filters: ViewFilter[] = ['未闭环', '待处理', '处理中', '待复核', '待风险接受', '已闭环', '已接受风险', '全部']

function selectFilter(value: ViewFilter) {
  filter.value = value
  page.value = 1
}

function filterCount(value: ViewFilter) {
  if (value in rectify.countByStatus) {
    return rectify.countByStatus[value as RectifyStatus]
  }
  return null
}

function openDetail(item: Rectification) {
  activeId.value = item.id
  resolutionDraft.value = item.status === '处理中' ? '' : item.resolution
  reviewDraft.value = ''
  afterText.value = item.status === '处理中' ? '' : item.after_text ?? ''
  evidenceIds.value = []
  acceptanceReason.value = ''
  residualRisk.value = ''
  planError.value = ''
  drawerOpen.value = true
  void loadMaterials(item)
}

async function transition(item: Rectification, payload: Omit<RectificationUpdate, 'version'>) {
  if (changing.value.has(item.id)) return false
  changing.value = new Set([...changing.value, item.id])
  try {
    await rectify.update(item.id, { ...payload, version: item.version ?? 1 })
    reviewDraft.value = ''
    return true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '状态更新失败，请重试')
    return false
  } finally {
    const next = new Set(changing.value)
    next.delete(item.id)
    changing.value = next
  }
}

async function start(item: Rectification) {
  if (!planComplete(item)) return void ElMessage.warning('请先补齐责任人、截止日期和验收条件等整改计划')
  if (await transition(item, { status: '处理中' })) ElMessage.success('已开始处理')
}

async function submitReview(item: Rectification) {
  const resolution = resolutionDraft.value.trim()
  if (!resolution) return void ElMessage.warning('请填写具体整改结果')
  if (!planComplete(item)) return void ElMessage.warning('请先补齐整改计划')
  if (!evidenceIds.value.length) return void ElMessage.warning('请至少关联一份修订版或凭证')
  if (item.contract_stage === 'unknown') return void ElMessage.warning('请先确认合同阶段')
  if (item.contract_stage === 'signed' && item.handling_method === 'revision') return void ElMessage.warning('已签署合同请选择补充协议或履约措施')
  if (item.handling_method !== 'performance' && !afterText.value.trim()) return void ElMessage.warning('请填写修改后条款')
  if (await transition(item, { status: '待复核', resolution, evidence_contract_ids: evidenceIds.value, after_text: afterText.value.trim() })) ElMessage.success('已提交复核')
}

async function approve(item: Rectification) {
  const reviewComment = reviewDraft.value.trim()
  if (!reviewComment) return void ElMessage.warning('请填写复核结论')
  if (await transition(item, { status: '已闭环', review_comment: reviewComment })) {
    ElMessage.success('复核通过，整改项已闭环')
  }
}

async function reject(item: Rectification) {
  const reviewComment = reviewDraft.value.trim()
  if (!reviewComment) return void ElMessage.warning('请填写退回原因')
  if (await transition(item, { status: '处理中', review_comment: reviewComment })) {
    resolutionDraft.value = ''
    afterText.value = ''
    evidenceIds.value = []
    ElMessage.success('已退回责任人继续整改')
  }
}

async function reopen(item: Rectification) {
  try {
    await ElMessageBox.confirm('重新开启后，该项将回到“待处理”，历史整改结果仍保留。', '重新开启整改项', {
      type: 'warning', confirmButtonText: '确认重新开启', cancelButtonText: '取消',
    })
  } catch { return }
  if (await transition(item, { status: '待处理' })) ElMessage.success('整改项已重新开启')
}

function formatTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

async function loadMaterials(item: Rectification) {
  const request = ++materialsGeneration
  materials.value = []
  materialsError.value = ''
  if (!item.risk_id) { materialsLoading.value = false; return }
  materialsLoading.value = true
  try {
    const result = await getRectificationMaterials(item.risk_id)
    if (request === materialsGeneration) materials.value = result.filter(material => material.id !== item.contract_id)
  } catch (error) {
    if (request === materialsGeneration) materialsError.value = error instanceof Error ? error.message : '材料列表加载失败'
  } finally { if (request === materialsGeneration) materialsLoading.value = false }
}

async function uploadEvidence(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const item = activeItem.value
  if (!file || !item) return
  if (!/\.(pdf|docx|txt)$/i.test(file.name)) {
    input.value = ''
    return void ElMessage.warning('请选择 PDF、DOCX 或 TXT 文件')
  }
  uploading.value = true
  try {
    const uploaded = await uploadContract(file, '', crypto.randomUUID(), item.department ?? '')
    if (activeId.value !== item.id) return
    await loadMaterials(item)
    if (!materials.value.some(material => material.id === uploaded.id)) {
      ElMessage.warning('文件已上传，但暂不在可关联材料中，请刷新列表并核对部门权限。')
      return
    }
    evidenceIds.value = [...new Set([...evidenceIds.value, uploaded.id])]
    ElMessage.success('材料已上传并关联，可核对原文；如需模型审查请主动进入审查页。')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '材料上传失败') }
  finally { uploading.value = false; input.value = '' }
}

async function savePlan(plan: RectificationPlan) {
  const item = activeItem.value
  if (!item) return
  planSaving.value = true
  planError.value = ''
  try {
    await rectify.savePlan(item.id, plan, item.version ?? 1)
    planOpen.value = false
    ElMessage.success('整改计划已保存')
  } catch (error) { planError.value = error instanceof Error ? error.message : '计划保存失败，请重试' }
  finally { planSaving.value = false }
}

function viewDocument(id: number, filename: string) {
  documentId.value = id
  documentFilename.value = filename
  documentOpen.value = true
}
function openAudit(id: number, filename: string) {
  void router.push({ path: '/audit', query: { contractId: String(id), filename } })
}
async function requestAcceptance(item: Rectification) {
  if (!planComplete(item) || item.contract_stage === 'unknown') return void ElMessage.warning('请先补齐整改计划并确认合同阶段')
  if (!resolutionDraft.value.trim() || !acceptanceReason.value.trim() || !residualRisk.value.trim()) return void ElMessage.warning('请填写控制措施、接受理由和剩余风险')
  if (await transition(item, { status: '待风险接受', resolution: resolutionDraft.value.trim(), acceptance_reason: acceptanceReason.value.trim(), residual_risk: residualRisk.value.trim() })) ElMessage.success('已提交另一位管理员审批风险接受')
}
async function approveAcceptance(item: Rectification) {
  if (!reviewDraft.value.trim()) return void ElMessage.warning('请填写本次风险接受审批意见')
  if (await transition(item, { status: '已接受风险', review_comment: reviewDraft.value.trim() })) ElMessage.success('已批准风险接受，剩余风险继续保留')
}
async function escalate(item: Rectification) {
  try {
    const { value: reason } = await ElMessageBox.prompt('请说明升级原因及需要协调的事项，仅登记系统内升级记录。', '登记升级处理', { inputType: 'textarea', inputValidator: value => !!value?.trim() || '请填写升级理由', confirmButtonText: '登记升级', cancelButtonText: '取消' })
    await rectify.escalate(item.id, reason.trim(), item.version ?? 1)
    ElMessage.success('已登记升级处理')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '升级登记失败') }
}
const stageLabels = { unsigned: '未签署', signed: '已签署', unknown: '待确认' }
const methodLabels = { revision: '草稿修订', supplement: '补充协议', performance: '履约措施' }
const snapshotLabels: Record<string, string> = { owner: '责任人', previous_owner: '原责任人', previous_plan: '调整前计划', due: '截止日期', note: '整改措施', acceptance_criteria: '验收条件', collaborators: '协作人', contract_stage: '合同阶段', handling_method: '处理方式', resolution: '整改结果 / 控制措施', before_text: '风险原文', after_text: '修改后条款', review_comment: '本次意见', evidence: '关联材料', acceptance_reason: '接受理由', residual_risk: '剩余风险', reason: '升级理由', escalation_reason: '升级理由', filename: '文件名', content_sha256: 'SHA-256', description: '提交说明' }
const actionLabels: Record<string, string> = { create: '创建整改计划', update_plan: '调整整改计划', start: '开始处理', submit: '提交复核', approve: '验收通过', reject: '退回整改', reopen: '重新开启', request_acceptance: '申请风险接受', accept: '批准风险接受', escalate: '登记升级处理' }
function snapshotValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(snapshotValue).join('\n') || '无'
  if (value && typeof value === 'object') return Object.entries(value).filter(([key]) => snapshotLabels[key]).map(([key, entry]) => `${snapshotLabels[key]}：${snapshotValue(entry)}`).join('\n')
  if (typeof value === 'string') return ({ ...stageLabels, ...methodLabels } as Record<string, string>)[value] ?? value
  return String(value)
}
</script>

<template>
  <div class="rectify-page">
    <div class="toolbar">
      <div class="filters" role="tablist" aria-label="整改状态筛选">
        <button v-for="item in filters" :key="item" :class="{ active: filter === item }" @click="selectFilter(item)">
          {{ item }}
          <span v-if="filterCount(item) !== null" class="filter-count">{{ filterCount(item) }}</span>
        </button>
      </div>
      <div class="toolbar-right">
        <el-input v-model="keyword" placeholder="搜索合同、风险、责任人" :prefix-icon="'Search'" clearable @input="page = 1" />
        <span v-if="lastLoadedAt" class="freshness">本次加载 {{ lastLoadedAt }}</span>
        <el-button :icon="'RefreshRight'" :loading="rectify.loading" @click="refresh(true)">刷新</el-button>
      </div>
    </div>

    <el-result v-if="rectify.error" icon="error" title="整改任务加载失败" :sub-title="rectify.error">
      <template #extra><el-button type="primary" @click="refresh(true)">重新加载</el-button></template>
    </el-result>

    <template v-else>
      <section class="attention-strip" aria-label="需要关注的整改任务">
        <button class="metric danger" :class="{ selected: filter === '已逾期' }" @click="selectFilter('已逾期')"><span>已逾期</span><strong>{{ overdueCount }}</strong><small>需优先催办</small></button>
        <button class="metric amber" :class="{ selected: filter === '即将到期' }" @click="selectFilter('即将到期')"><span>3 天内到期</span><strong>{{ dueSoonCount }}</strong><small>提前跟进</small></button>
        <button class="metric blue" @click="selectFilter('待复核')"><span>待复核</span><strong>{{ rectify.countByStatus.待复核 }}</strong><small>等待验收</small></button>
        <button class="metric seal" :class="{ selected: filter === '高风险未闭环' }" @click="selectFilter('高风险未闭环')"><span>高风险未闭环</span><strong>{{ highOpenCount }}</strong><small>管理重点</small></button>
      </section>

      <section v-loading="rectify.loading" class="worklist">
        <header class="list-head"><div><h2>整改任务</h2><p>默认优先显示逾期与高风险任务</p></div><span class="count">共 {{ filtered.length }} 项</span></header>
        <div v-if="!rectify.loading && !filtered.length" class="empty-wrap">
          <el-empty :description="keyword ? '未找到匹配的整改任务' : '当前范围暂无整改任务'" />
        </div>
        <button v-for="item in paged" :key="item.id" class="task-row" :class="`level-${item.level}`" @click="openDetail(item)">
          <div class="task-identity">
            <div class="task-badges">
              <span class="task-id">{{ item.id }}</span>
              <el-tag :type="levelMeta[item.level].type" size="small">{{ levelMeta[item.level].label }}</el-tag>
              <el-tag :type="statusType[item.status]" size="small" effect="plain">{{ item.status }}</el-tag>
              <el-tag v-if="isOverdue(item)" type="danger" size="small" effect="dark">已逾期</el-tag>
            </div>
            <strong>{{ item.risk }}</strong><span class="contract-name">{{ item.contract }}</span>
          </div>
          <div class="task-owner"><span>责任人</span><strong>{{ item.owner || '未分派' }}</strong></div>
          <div class="task-date" :class="{ overdue: isOverdue(item) }"><span>截止日期</span><strong>{{ item.due }}</strong></div>
          <div class="task-action"><span>{{ item.status === '已闭环' ? '查看验收' : '查看并处理' }}</span><el-icon><ArrowRight /></el-icon></div>
        </button>
        <footer v-if="filtered.length > pageSize" class="pagination-bar">
          <el-pagination v-model:current-page="page" :page-size="pageSize" :total="filtered.length" layout="prev, pager, next, total" background />
        </footer>
      </section>
    </template>

    <el-drawer v-model="drawerOpen" size="min(680px, 100vw)" class="rectify-drawer">
      <template #header><div v-if="activeItem" class="drawer-title"><span>{{ activeItem.id }} · {{ activeItem.status }}</span><strong>{{ activeItem.risk }}</strong></div></template>
      <template v-if="activeItem">
        <section class="detail-section source-section">
          <div class="detail-label">来源审查</div><h3>{{ activeItem.contract }}</h3>
          <div class="source-meta"><el-tag :type="levelMeta[activeItem.level].type" size="small">{{ levelMeta[activeItem.level].label }}</el-tag><span v-if="activeItem.risk_id">风险编号 R{{ activeItem.risk_id }}</span><span>创建于 {{ activeItem.created }}</span></div>
          <p>{{ activeItem.note || '暂无整改建议' }}</p>
          <div v-if="activeItem.contract_id" class="material-actions"><el-button link type="primary" @click="viewDocument(activeItem.contract_id!, activeItem.contract)">查看来源原文</el-button><el-button link @click="openAudit(activeItem.contract_id!, activeItem.contract)">进入来源审查</el-button></div>
        </section>
        <section class="detail-section">
          <div class="section-heading"><h3>整改计划</h3><el-button v-if="canManage(activeItem) && ['待处理', '处理中'].includes(activeItem.status)" link type="primary" @click="planError = ''; planOpen = true">补齐或调整计划</el-button></div>
          <el-alert v-if="!planComplete(activeItem)" type="warning" :closable="false" title="历史计划尚未补齐，请由专业人员明确责任、措施和验收条件。" />
          <div class="assignment-grid"><div><span>责任人</span><strong>{{ activeItem.owner || '未分派' }}</strong></div><div><span>截止日期</span><strong :class="{ overdue: isOverdue(activeItem) }">{{ activeItem.due || '待补齐' }}</strong></div><div><span>协作人</span><strong>{{ activeItem.collaborators?.join('、') || '无' }}</strong></div><div><span>合同阶段 / 处理方式</span><strong>{{ stageLabels[activeItem.contract_stage ?? 'unknown'] }} / {{ activeItem.handling_method ? methodLabels[activeItem.handling_method] : '待补齐' }}</strong></div></div>
          <h4>验收条件</h4><p class="detail-copy">{{ activeItem.acceptance_criteria || '待补齐，不可直接提交复核' }}</p>
        </section>
        <section class="detail-section clause-comparison">
          <h3>人工条款对照</h3><p class="detail-copy">对照用于人工核对，尚未经过模型差异验证。</p>
          <el-tag :type="activeItem.original_text_verified ? 'success' : 'warning'" size="small">{{ activeItem.original_text_verified ? '原文已定位核实' : '原文尚未定位核实' }}</el-tag>
          <h4>风险原文</h4><blockquote>{{ activeItem.before_text || '暂无可核实的引用，请查看来源原文。' }}</blockquote>
          <label class="field-label" for="after-text">修改后条款</label><el-input id="after-text" v-model="afterText" type="textarea" :rows="4" :readonly="activeItem.status !== '处理中' || !canExecute(activeItem)" maxlength="10000" :placeholder="activeItem.handling_method === 'performance' ? '履约措施可不修改条款，在整改结果中说明凭证' : '草稿修订或补充协议必须填写修改后条款'" />
        </section>
        <section class="detail-section">
          <label class="field-label" for="resolution">整改结果 <em v-if="activeItem.status === '处理中'">必填</em></label>
          <el-input id="resolution" v-model="resolutionDraft" type="textarea" :rows="5" maxlength="2000" show-word-limit :readonly="activeItem.status !== '处理中' || !canExecute(activeItem)" placeholder="填写本次完成情况、控制措施和可验收的结果" />
          <el-alert v-if="activeItem.status === '已闭环' && !activeItem.resolution" class="legacy-alert" type="warning" :closable="false" title="该历史记录未保存结构化整改结果" description="可重新开启后补充整改结果，再按新流程提交复核。" />
          <p v-if="activeItem.submitted_at" class="time-note">{{ activeItem.status === '待复核' || activeItem.status === '已闭环' ? '提交复核' : '上次提交复核' }}：{{ formatTime(activeItem.submitted_at) }}</p>
        </section>
        <section class="detail-section">
          <h3>整改材料</h3>
          <template v-if="activeItem.status === '处理中' && canExecute(activeItem)">
            <label class="field-label" for="evidence-materials">关联整改材料</label>
            <el-select id="evidence-materials" v-model="evidenceIds" aria-label="关联整改材料" multiple filterable :loading="materialsLoading" placeholder="选择修订版或实际履约凭证"><el-option v-for="material in materials" :key="material.id" :value="material.id" :label="`${material.filename} · #${material.id}`" /></el-select>
            <div class="material-actions"><label class="upload-control" :class="{ disabled: uploading }">{{ uploading ? '正在上传材料…' : '上传修订版或凭证' }}<input type="file" aria-label="上传修订版或凭证" accept=".pdf,.docx,.txt" :disabled="uploading" @change="uploadEvidence" /></label><el-button link :loading="materialsLoading" @click="loadMaterials(activeItem)">刷新材料列表</el-button></div>
            <p class="detail-copy">支持 PDF、DOCX、TXT。上传保留原合同，不自动运行模型审查。至少关联一份材料才能提交复核。</p>
            <el-alert v-if="materialsError" type="error" :closable="false" :title="materialsError" />
            <p v-else-if="!materialsLoading && !materials.length" class="detail-copy">暂无可关联材料，请上传修订版或凭证。</p>
          </template>
          <div v-for="material in materials.filter(row => evidenceIds.includes(row.id))" :key="material.id" class="material-row"><strong>{{ material.filename }}</strong><div class="material-actions"><el-button link type="primary" @click="viewDocument(material.id, material.filename)">查看材料原文</el-button><el-button link @click="openAudit(material.id, material.filename)">进入材料审查</el-button></div></div>
          <div v-for="evidence in activeItem.evidence ?? []" :key="evidence.contract_id" class="material-row"><strong>{{ evidence.filename }}</strong><p class="hash">SHA-256 {{ evidence.content_sha256 || '历史记录未保存哈希' }}</p><p v-if="evidence.description" class="detail-copy">{{ evidence.description }}</p><div class="material-actions"><el-button link type="primary" @click="viewDocument(evidence.contract_id, evidence.filename)">查看材料原文</el-button><el-button link @click="openAudit(evidence.contract_id, evidence.filename)">进入材料审查</el-button></div></div>
          <p v-if="!activeItem.evidence?.length && activeItem.status !== '处理中'" class="detail-copy">该记录尚无已提交的关联材料。</p>
        </section>
        <section v-if="activeItem.status === '处理中' && canExecute(activeItem)" class="detail-section">
          <details><summary>申请风险接受</summary><p class="detail-copy">无法消除的剩余风险由另一位管理员单独批准，批准后显示“已接受风险”，不计为已闭环。</p>
            <label class="field-label" for="acceptance-reason">接受理由</label><el-input id="acceptance-reason" v-model="acceptanceReason" type="textarea" :rows="3" maxlength="2000" />
            <label class="field-label" for="residual-risk">剩余风险</label><el-input id="residual-risk" v-model="residualRisk" type="textarea" :rows="3" maxlength="2000" />
            <el-button class="acceptance-submit" :loading="changing.has(activeItem.id)" @click="requestAcceptance(activeItem)">提交风险接受申请</el-button>
          </details>
        </section>
        <section v-if="['待风险接受', '已接受风险'].includes(activeItem.status)" class="detail-section">
          <h3>风险接受</h3><el-alert type="warning" :closable="false" :title="activeItem.status === '已接受风险' ? '已接受风险不代表风险已消除，保留剩余风险。' : '等待另一位管理员审批风险接受。'" /><h4>接受理由</h4><p class="detail-copy">{{ activeItem.acceptance_reason }}</p><h4>剩余风险</h4><p class="detail-copy">{{ activeItem.residual_risk }}</p><p v-if="activeItem.accepted_at" class="time-note">接受时间：{{ formatTime(activeItem.accepted_at) }}</p>
        </section>
        <section v-if="activeItem.status === '待复核' || activeItem.status === '待风险接受' || activeItem.review_comment || activeItem.status === '已闭环'" class="detail-section">
          <p v-if="activeItem.status === '待复核' && !canReview(activeItem)" class="detail-copy">由其他法务、财务或管理员独立验收</p>
          <p v-if="activeItem.review_comment" class="detail-copy">上次意见：{{ activeItem.review_comment }}</p>
          <template v-if="(activeItem.status === '待复核' && canReview(activeItem)) || (activeItem.status === '待风险接受' && canAccept(activeItem))">
          <label class="field-label" for="review-comment">复核意见</label>
          <el-input id="review-comment" v-model="reviewDraft" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="每次通过或退回都须填写本次意见" />
          </template>
          <p v-if="activeItem.closed_at" class="time-note">闭环时间：{{ formatTime(activeItem.closed_at) }}</p>
        </section>
        <section class="detail-section">
          <div class="section-heading"><h3>处理时间线</h3><el-button v-if="canEscalate(activeItem) && isOpen(activeItem) && (activeItem.level === 'high' || isOverdue(activeItem))" link type="danger" @click="escalate(activeItem)">登记升级处理</el-button></div>
          <p v-if="!activeItem.events?.length" class="detail-copy">历史记录未提供事件明细，后续操作将保留记录。</p>
          <ol v-else class="event-timeline"><li v-for="event in activeItem.events" :key="event.id"><strong>{{ actionLabels[event.action] ?? event.action }}</strong><span>{{ event.actor }} · {{ formatTime(event.occurred_at) }}</span><p>{{ event.from_status || '创建' }} → {{ event.to_status }}</p><details><summary>查看本次记录</summary><dl><template v-for="(value, key) in event.snapshot" :key="key"><template v-if="snapshotLabels[key as string] && value !== null && value !== ''"><dt>{{ snapshotLabels[key as string] }}</dt><dd>{{ snapshotValue(value) }}</dd></template></template></dl></details></li></ol>
        </section>
      </template>
      <template #footer><div v-if="activeItem" class="drawer-actions">
        <el-button @click="drawerOpen = false">关闭</el-button>
        <el-button v-if="activeItem.status === '待处理' && canExecute(activeItem)" type="primary" :disabled="!planComplete(activeItem)" :loading="changing.has(activeItem.id)" @click="start(activeItem)">开始处理</el-button>
        <el-button v-if="activeItem.status === '处理中' && canExecute(activeItem)" type="primary" :loading="changing.has(activeItem.id) || uploading" @click="submitReview(activeItem)">提交复核</el-button>
        <template v-if="activeItem.status === '待复核' && canReview(activeItem)"><el-button :loading="changing.has(activeItem.id)" @click="reject(activeItem)">退回整改</el-button><el-button type="success" :loading="changing.has(activeItem.id)" @click="approve(activeItem)">通过并闭环</el-button></template>
        <template v-if="activeItem.status === '待风险接受' && canAccept(activeItem)"><el-button :loading="changing.has(activeItem.id)" @click="reject(activeItem)">退回风险接受</el-button><el-button type="warning" :loading="changing.has(activeItem.id)" @click="approveAcceptance(activeItem)">批准风险接受</el-button></template>
        <el-button v-if="['已闭环', '已接受风险'].includes(activeItem.status) && canReopen(activeItem)" :loading="changing.has(activeItem.id)" @click="reopen(activeItem)">重新开启</el-button>
      </div></template>
    </el-drawer>
    <RectificationPlanDialog v-if="activeItem" v-model="planOpen" :risk-id="activeItem.risk_id ?? null" :initial="activeItem" :saving="planSaving" :error="planError" @save="savePlan" />
    <AnnotationModal v-model="documentOpen" :risks="[]" :filename="documentFilename" :contract-id="documentId" />
  </div>
</template>

<style scoped>
.rectify-page { min-width: 0; }
.toolbar { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.filters { display: flex; align-items: center; border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; background: var(--ink-2); }
.filters button { min-height: 38px; padding: 0 14px; border: 0; border-right: 1px solid var(--line); background: transparent; color: var(--ivory-dim); cursor: pointer; font-family: var(--font-body); font-size: var(--type-label); font-weight: 500; line-height: 1.4; }
.filters button:last-child { border-right: 0; }.filters button.active { background: var(--brass); color: var(--on-brass); font-weight: 600; }.filter-count { margin-left: 4px; opacity: .75; }
.toolbar-right { display: flex; align-items: center; gap: 12px; }.toolbar-right :deep(.el-input) { width: 280px; }.freshness { white-space: nowrap; font-family: var(--font-data); font-size: var(--type-caption); font-variant-numeric: tabular-nums; line-height: 1.4; color: var(--muted); }
.attention-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.metric { display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto; gap: 4px 12px; min-height: 86px; padding: 14px 16px; text-align: left; background: var(--ink-2); border: 1px solid var(--line); border-top: 3px solid var(--muted); border-radius: var(--r-sm); color: var(--ivory); cursor: pointer; font-family: var(--font-body); }
.metric span { font-size: var(--type-label); font-weight: 500; line-height: 1.4; color: var(--ivory-dim); }.metric strong { grid-row: 1 / 3; grid-column: 2; align-self: center; font-family: var(--font-data); font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums lining-nums; line-height: 1; }.metric small { font-size: var(--type-caption); line-height: 1.4; color: var(--muted); }
.metric.selected { box-shadow: inset 0 0 0 1px var(--brass); background: var(--brass-soft); }
.metric.danger,.metric.seal { border-top-color: var(--seal); }.metric.danger strong,.metric.seal strong { color: var(--seal); }.metric.amber { border-top-color: var(--amber); }.metric.amber strong { color: var(--amber); }.metric.blue { border-top-color: #527ca5; }.metric.blue strong { color: #527ca5; }
.worklist { background: var(--ink-2); border: 1px solid var(--line); border-radius: var(--r-sm); overflow: hidden; }.list-head { display: flex; justify-content: space-between; align-items: center; padding: 16px 18px; border-bottom: 1px solid var(--line); }
.list-head h2 { margin: 0; font-family: var(--font-body); font-size: var(--type-subtitle); font-weight: 650; line-height: 1.4; color: var(--ivory); }.list-head p { margin: 4px 0 0; font-size: var(--type-label); line-height: 1.5; color: var(--muted); }.count { font-family: var(--font-data); font-size: var(--type-caption); font-variant-numeric: tabular-nums; line-height: 1.4; color: var(--muted); }
.task-row { position: relative; display: grid; grid-template-columns: minmax(280px, 1fr) 130px 130px 120px; width: 100%; gap: 18px; align-items: center; min-height: 96px; padding: 15px 18px 15px 20px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: inherit; text-align: left; cursor: pointer; font-family: var(--font-body); }
.task-row::before { position: absolute; left: 0; top: 16px; bottom: 16px; width: 3px; content: ''; background: var(--sage); }.task-row.level-high::before { background: var(--seal); }.task-row.level-medium::before { background: var(--amber); }.task-row:hover { background: var(--brass-soft); }
.task-identity { min-width: 0; display: flex; flex-direction: column; gap: 6px; }.task-identity strong { overflow: hidden; color: var(--ivory); text-overflow: ellipsis; white-space: nowrap; font-size: 15px; font-weight: 650; line-height: 1.45; }.task-badges { display: flex; align-items: center; gap: 6px; }.task-id { font-family: var(--font-code); font-size: var(--type-caption); font-weight: 500; line-height: 1.35; color: var(--brass); }.contract-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--type-label); line-height: 1.5; color: var(--ivory-dim); }
.task-owner,.task-date { display: flex; flex-direction: column; gap: 5px; }.task-owner span,.task-date span { font-size: var(--type-caption); line-height: 1.35; color: var(--muted); }.task-owner strong,.task-date strong { font-size: var(--type-label); line-height: 1.45; color: var(--ivory-dim); font-weight: 500; }.task-date strong { font-family: var(--font-data); font-variant-numeric: tabular-nums; }.task-action { display: flex; justify-content: flex-end; align-items: center; gap: 5px; color: var(--brass); font-size: var(--type-label); font-weight: 500; line-height: 1.4; }.overdue { color: var(--seal) !important; font-weight: 600 !important; }
.empty-wrap { min-height: 260px; display: grid; place-items: center; }.pagination-bar { display: flex; justify-content: flex-end; padding: 14px 18px; }
.drawer-title { display: flex; flex-direction: column; gap: 5px; }.drawer-title span { font-family: var(--font-code); font-size: var(--type-caption); font-weight: 500; line-height: 1.35; color: var(--brass); }.drawer-title strong { font-family: var(--font-body); font-size: 18px; font-weight: 650; line-height: 1.45; color: var(--ivory); }
.detail-section { padding: 18px 0; border-bottom: 1px solid var(--line); }.detail-section:first-child { padding-top: 0; }.detail-label,.field-label { display: block; margin-bottom: 9px; font-size: var(--type-label); font-weight: 500; line-height: 1.45; color: var(--muted); }.field-label em { margin-left: 5px; color: var(--seal); font-style: normal; }
.source-section h3 { margin: 0 0 9px; font-family: var(--font-body); font-size: 15px; font-weight: 650; line-height: 1.5; color: var(--ivory); }.source-section p { margin: 12px 0 0; color: var(--ivory-dim); font-size: var(--type-body); line-height: var(--leading-body); }.source-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: var(--type-caption); line-height: 1.45; color: var(--muted); }
.assignment-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }.assignment-grid div { display: flex; flex-direction: column; gap: 5px; }.assignment-grid span { color: var(--muted); font-size: var(--type-caption); line-height: 1.35; }.assignment-grid strong { color: var(--ivory); font-size: var(--type-body); font-weight: 600; line-height: 1.45; }.time-note { margin: 8px 0 0; font-family: var(--font-data); font-size: var(--type-caption); font-variant-numeric: tabular-nums; line-height: 1.45; color: var(--muted); }.drawer-actions { display: flex; justify-content: flex-end; gap: 8px; }
.legacy-alert { margin-top: 10px; }
.detail-section :deep(.el-select__placeholder) { pointer-events: none; }
.detail-section h3 { margin: 0 0 12px; color: var(--ivory); font-size: 15px; }.detail-section h4 { margin: 16px 0 8px; color: var(--ivory-dim); font-size: 13px; }.section-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }.section-heading h3 { margin: 0; }.detail-copy { color: var(--ivory-dim); font-size: var(--type-label); line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }.assignment-grid { margin-top: 14px; }.clause-comparison blockquote { margin: 10px 0 18px; padding: 12px 14px; border-left: 3px solid var(--brass); background: var(--brass-soft); color: var(--ivory-dim); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; }.detail-section :deep(.el-select) { width: 100%; }.material-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 10px; }.material-row { padding: 14px 0; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }.material-row strong { font-size: 14px; color: var(--ivory); }.hash { font-family: var(--font-code); font-size: 11px; color: var(--muted); overflow-wrap: anywhere; }.upload-control { position: relative; padding: 6px 12px; border: 1px solid var(--brass); border-radius: var(--r-sm); color: var(--brass); font-size: 13px; cursor: pointer; }.upload-control input { position: absolute; inset: 0; opacity: 0; width: 100%; cursor: pointer; }.upload-control:focus-within { outline: 2px solid var(--brass); outline-offset: 3px; }.upload-control.disabled { opacity: .6; }.acceptance-submit { margin-top: 12px; }.detail-section details summary { cursor: pointer; color: var(--brass); font-size: 13px; }.event-timeline { list-style: none; padding: 0 0 0 16px; margin: 0; border-left: 2px solid var(--line); }.event-timeline li { position: relative; padding: 0 0 22px 8px; }.event-timeline li::before { content: ''; position: absolute; left: -22px; top: 5px; width: 8px; height: 8px; border-radius: 50%; background: var(--brass); }.event-timeline li > strong,.event-timeline li > span { display: block; font-size: 13px; line-height: 1.7; }.event-timeline li > span,.event-timeline li > p { color: var(--muted); font-size: 12px; }.event-timeline dl { margin: 10px 0; font-size: 12px; line-height: 1.7; }.event-timeline dt { color: var(--muted); }.event-timeline dd { margin: 0 0 8px; color: var(--ivory-dim); white-space: pre-wrap; overflow-wrap: anywhere; }.drawer-actions { flex-wrap: wrap; }.filters { min-width: 0; overflow-x: auto; }.filters button { flex-shrink: 0; }
@media (max-width: 1180px) { .toolbar { flex-direction: column; }.toolbar-right { justify-content: space-between; }.attention-strip { grid-template-columns: 1fr 1fr; }.task-row { grid-template-columns: minmax(220px, 1fr) 110px 120px; }.task-action { display: none; } }
@media (max-width: 720px) { .filters { width: 100%; overflow-x: auto; }.filters button { flex: 0 0 auto; }.toolbar-right { align-items: stretch; flex-direction: column; }.toolbar-right :deep(.el-input) { width: 100%; }.attention-strip { grid-template-columns: 1fr 1fr; }.task-row { grid-template-columns: 1fr 1fr; gap: 12px; }.task-identity { grid-column: 1 / -1; }.task-date { align-items: flex-end; }.assignment-grid { grid-template-columns: 1fr; } }
</style>
