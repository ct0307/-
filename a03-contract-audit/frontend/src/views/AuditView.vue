<script setup lang="ts">
// 合同合规审查（真实接口核心闭环）：上传→解析→审查→复核→生成整改。
// 闭环逻辑迁移自 WorkbenchView，数据落 audit-session store。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, RefreshRight, Switch, WarningFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadRawFile } from 'element-plus'
import { getLookups } from '@/api/admin'

import type { RiskOut } from '@/api/types'
import { useAuditSessionStore, type UploadRecord, type UploadStatus } from '@/stores/audit-session'
import { useRectifyStore } from '@/stores/rectify'
import { useNotifyStore } from '@/stores/notify'
import { useAuthStore } from '@/stores/auth'
import { useBatchStore } from '@/stores/batch'
import RiskReviewDrawer from '@/components/audit/RiskReviewDrawer.vue'
import AnnotationModal from '@/components/audit/AnnotationModal.vue'
import { auditProgressDisplay, type AuditUiState } from '@/utils/audit-progress'
import { formatOcrConfidence, reviewStatusLabel } from '@/utils/ocr-quality'

const session = useAuditSessionStore()
const rectify = useRectifyStore()
const notify = useNotifyStore()
const auth = useAuthStore()
const batchStore = useBatchStore()
const route = useRoute()
const router = useRouter()

const department = ref('采购中心') // 保留兼容（批量上传可能引用），实际展示改用 auth.department
const contractType = ref('')
const dimExpanded = ref(false) // 审查维度折叠面板，默认收起

// 降级默认值（接口失败时兜底）
const _DEFAULT_DEPTS = ['采购中心', '销售部', '研发部', '法务部', '财务部', '人力资源部', '行政部', '运营部']
const _DEFAULT_CTYPES = ['软件开发外包合同', '技术服务合同', '采购合同', '销售合同', '劳动合同', '租赁合同', '保密协议', '合作协议']

const departmentOptions = ref<string[]>(_DEFAULT_DEPTS)
const contractTypeOptions = ref<string[]>(_DEFAULT_CTYPES)

const _TYPE_HINTS = [
  { family: 'purchase', label: '采购合同', keywords: ['采购', '设备购置', '供货'] },
  { family: 'software', label: '软件开发外包合同', keywords: ['软件开发', '源代码', '系统开发'] },
  { family: 'labor', label: '劳动合同', keywords: ['劳动合同', '劳动关系', '试用期'] },
  { family: 'lease', label: '租赁合同', keywords: ['租赁', '出租方', '承租方'] },
] as const

function contractTypeFamily(value: string) {
  const matched = _TYPE_HINTS.find((item) => item.keywords.some((keyword) => value.includes(keyword)))
  return matched?.family ?? value
}

const suggestedContractType = computed(() => {
  const material = `${session.filename} ${JSON.stringify(session.elements ?? {})}`
  return _TYPE_HINTS.find((item) => item.keywords.some((keyword) => material.includes(keyword)))?.label ?? ''
})

const hasContractTypeConflict = computed(() => Boolean(
  suggestedContractType.value
  && contractType.value
  && contractTypeFamily(suggestedContractType.value) !== contractTypeFamily(contractType.value),
))

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
  const batchId = Number(route.query.batch)
  if (!Number.isInteger(batchId) || batchId <= 0) return
  batchOpen.value = true
  try {
    await batchStore.resume(batchId)
  } catch {
    ElMessage.error(batchStore.error || '批次状态恢复失败')
  }
})

onBeforeUnmount(() => batchStore.stopPolling())

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

// —— 上传 + 解析（真接口）——
function onFileChange(uploadFile: { raw?: UploadRawFile }) {
  if (uploadFile.raw) onFile(uploadFile.raw)
}

async function onFile(file: UploadRawFile) {
  contractType.value = ''
  try {
    await session.uploadAndParse(file)
    ElMessage.success('上传并解析完成')
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '上传或解析失败，请稍后重试')
  }
}

const auditState = ref<AuditUiState>('idle')
const auditDisplay = computed(() => auditProgressDisplay(auditState.value))

const uploadStatusMeta: Record<UploadStatus, {
  label: string
  type: 'success' | 'warning' | 'danger' | 'info'
}> = {
  uploading: { label: '上传中', type: 'info' },
  upload_failed: { label: '上传失败', type: 'danger' },
  parsing: { label: '解析中', type: 'warning' },
  parse_failed: { label: '上传成功，解析失败', type: 'danger' },
  parsed: { label: '解析完成', type: 'success' },
}

async function retryUploadRecord(record: UploadRecord) {
  try {
    await session.retryParse(record)
    contractType.value = ''
    auditState.value = 'idle'
    ElMessage.success('解析完成')
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '解析失败，请稍后重试')
  }
}

async function selectUploadRecord(record: UploadRecord) {
  try {
    await session.selectParsedContract(record)
    contractType.value = ''
    auditState.value = 'idle'
    ElMessage.success(`已切换到 ${record.filename}`)
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '合同切换失败，请稍后重试')
  }
}

// —— 触发审查（真接口）——
async function onAudit() {
  if (!session.contractId) {
    ElMessage.warning('请先上传合同')
    return
  }
  if (!contractType.value) {
    ElMessage.warning('请先确认合同类型')
    return
  }
  if (hasContractTypeConflict.value) {
    try {
      await ElMessageBox.confirm(
        `材料内容更像“${suggestedContractType.value}”，当前选择为“${contractType.value}”。请核对后再继续。`,
        '合同类型待确认',
        {
          type: 'warning',
          confirmButtonText: '确认当前类型并继续',
          cancelButtonText: '返回修改',
        },
      )
    } catch {
      return
    }
  }
  auditState.value = 'running'
  try {
    await session.runAudit(
      contractType.value,
      dimensions.value.filter(d => d.on).map(d => d.key),
    )
    auditState.value = 'done'
    const n = session.riskCount
    ElMessage.success(`审查完成，检出 ${n} 条风险`)
    if (session.levelCounts.high > 0) {
      notify.push('alert', '高风险预警', `${session.filename} 检出 ${session.levelCounts.high} 项高风险条款。`)
    }
  } catch {
    auditState.value = 'failed'
    ElMessage.error('审查失败（需 legal / finance 角色）')
  }
}

// 清除已上传合同（二次确认，防误触）
async function cancelUpload() {
  try {
    await ElMessageBox.confirm(
      '已上传的合同和审查结果将被清空，确认重新上传？',
      '确认清除',
      { type: 'warning', confirmButtonText: '确认清除', cancelButtonText: '取消' },
    )
    session.reset()
    auditState.value = 'idle'
  } catch {
    // 用户取消，不操作
  }
}

function onAbort() {
  session.abortAudit()
  auditState.value = 'idle'
  ElMessage.info('审查已中止')
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
const activeRisk = ref<RiskOut | null>(null)
function openReview(risk: RiskOut) {
  activeRisk.value = risk
  drawerOpen.value = true
}

async function confirmRisk(risk: RiskOut) {
  try {
    await session.setRiskStatus(risk, 'confirmed')
    // 跨模块联动：生成整改项 + 推通知
    await rectify.addFromRisk(risk, session.filename || '当前合同', auth.username)
    notify.push('rectify', '生成整改项', `已就"${risk.category}"生成整改项，进入整改跟踪。`)
    ElMessage.success('已确认并生成整改项')
    drawerOpen.value = false
  } catch {
    ElMessage.error('操作失败')
  }
}

async function ignoreRisk(risk: RiskOut) {
  try {
    await session.setRiskStatus(risk, 'ignored')
    ElMessage.success('已标记为误报')
    drawerOpen.value = false
  } catch {
    ElMessage.error('操作失败')
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
  { num: '1', title: '上传合同', desc: '支持 PDF / Word / TXT，文件即刻加密存储' },
  { num: '2', title: '智能审查', desc: '法务 + 财务双Agent 协同，比对法规知识库' },
  { num: '3', title: '人工复核 / 生成整改', desc: '确认风险条款，自动生成整改跟踪项' },
]

// —— 批量上传 ——
const batchOpen = ref(false)

interface PendingBatchItem {
  file: File
}

const batchItems = ref<PendingBatchItem[]>([])
const batchRows = computed(() => {
  if (batchStore.batch) return batchStore.batch.items
  return batchItems.value.map((item, index) => ({
    id: -index - 1,
    contract_id: 0,
    filename: item.file.name,
    status: 'pending' as const,
    error: null,
    attempts: 0,
    started_at: null,
    finished_at: null,
    requires_review: false,
    ocr_confidence: null,
    review_reason: null,
  }))
})

const batchStatusLabel: Record<string, string> = {
  pending: '待上传',
  queued: '等待处理',
  parsing: '解析中',
  auditing: '审查中',
  done: '已完成',
  failed: '失败',
}

function onBatchFileChange(uploadFile: { raw: File }) {
  if (batchItems.value.length >= 200) {
    ElMessage.warning('单次最多选择 200 份')
    return
  }
  if (!batchItems.value.find((i) => i.file.name === uploadFile.raw.name)) {
    batchItems.value.push({ file: uploadFile.raw })
  }
}

function removeBatchItem(idx: number) {
  batchItems.value.splice(idx, 1)
}

async function startBatchUpload() {
  if (!batchItems.value.length) return
  try {
    const created = await batchStore.create(
      batchItems.value.map((i) => i.file),
      contractType.value,
      dimensions.value.filter((item) => item.on).map((item) => item.key),
    )
    batchItems.value = []
    await router.replace({
      query: { ...route.query, batch: String(created.id) },
    })
    ElMessage.success(`批次 #${created.id} 已提交，共 ${created.total} 份合同`)
  } catch {
    ElMessage.error(batchStore.error || '批次提交失败，请检查后端连接')
  }
}

async function retryFailedBatch() {
  try {
    const result = await batchStore.retry()
    if (result) ElMessage.success(`已重新提交 ${result.retried} 个失败任务`)
  } catch {
    ElMessage.error(batchStore.error || '失败任务重试失败')
  }
}

async function resetBatch() {
  batchStore.reset()
  batchItems.value = []
  const query = { ...route.query }
  delete query.batch
  await router.replace({ query })
}

function closeBatch() {
  batchOpen.value = false
}


</script>

<template>
  <div class="audit-grid">
    <!-- 左栏：上传 + 配置 -->
    <div class="left-stack">
      <el-card shadow="never" class="upload-panel">
        <template #header><span class="panel-title">合同上传</span></template>
        <el-upload
          drag
          :disabled="session.busy"
          :auto-upload="false"
          :show-file-list="false"
          :on-change="onFileChange"
          accept=".pdf,.docx,.txt"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">
            拖拽合同到此，或<em>点击选择</em>
            <p class="upload-hint">PDF / Word / TXT · 拖拽或点击均可</p>
          </div>
        </el-upload>
        <!-- 当前审查合同与本次会话上传记录分开显示，解析失败不会覆盖当前合同。 -->
        <div v-if="session.filename" class="filename mono">
          <el-icon class="icon-ok"><CircleCheck /></el-icon>
          <span class="filename-text">{{ session.filename }}（合同 #{{ session.contractId }}）</span>
          <el-button
            v-if="!session.busy"
            class="filename-cancel"
            size="small"
            :icon="'Close'"
            circle
            plain
            title="取消，重新上传"
            @click="cancelUpload"
          />
        </div>
        <div class="upload-records" aria-label="本次上传记录">
          <div class="upload-records-title">本次上传记录</div>
          <div v-if="session.uploadRecords.length === 0" class="upload-record-empty">
            尚无上传记录
          </div>
          <div
            v-for="record in session.uploadRecords"
            v-else
            :key="record.localId"
            class="upload-record-row"
          >
            <div class="upload-record-main">
              <span class="upload-record-name mono" :title="record.filename">{{ record.filename }}</span>
              <el-tag size="small" :type="uploadStatusMeta[record.status].type">
                {{ uploadStatusMeta[record.status].label }}
              </el-tag>
            </div>
            <p v-if="record.errorMessage" class="upload-record-error" role="alert">
              {{ record.errorMessage }}
            </p>
            <div v-if="record.status === 'parse_failed' || (record.status === 'parsed' && record.contractId !== session.contractId)" class="upload-record-actions">
              <el-tooltip v-if="record.status === 'parse_failed'" content="使用已上传的合同重新解析" placement="top">
                <el-button
                  circle
                  size="small"
                  :icon="RefreshRight"
                  :disabled="session.busy"
                  :aria-label="`重新解析 ${record.filename}`"
                  @click="retryUploadRecord(record)"
                />
              </el-tooltip>
              <el-tooltip v-else content="切换当前审查合同" placement="top">
                <el-button
                  circle
                  size="small"
                  :icon="Switch"
                  :disabled="session.busy"
                  :aria-label="`切换到 ${record.filename}`"
                  @click="selectUploadRecord(record)"
                />
              </el-tooltip>
            </div>
          </div>
        </div>
        <!-- 批量上传入口 -->
        <el-button class="batch-btn" size="small" :icon="'Files'" @click="batchOpen = true">
          批量上传（支持50份以上）
        </el-button>
      </el-card>

      <el-card shadow="never" class="config-panel">
        <template #header><span class="panel-title">合同信息 &amp; 审查配置</span></template>
        <div class="form-grid">
          <label>合同类型 <span class="required-mark">*</span>
            <el-select v-model="contractType" size="default" filterable placeholder="请选择并确认合同类型">
              <el-option v-for="t in contractTypeOptions" :key="t" :label="t" :value="t" />
            </el-select>
            <span v-if="!contractType" class="field-error">审查前必须确认合同类型</span>
            <span v-else-if="hasContractTypeConflict" class="field-warning">
              材料建议类型：{{ suggestedContractType }}，请核对
            </span>
            <span v-else-if="suggestedContractType" class="field-hint">
              材料建议类型：{{ suggestedContractType }}
            </span>
          </label>
          <label>归属部门
            <div class="dept-readonly">
              {{ auth.department || '（未知部门）' }}
              <span class="dept-hint">当前账号自动归属</span>
            </div>
          </label>
        </div>
        <!-- 维度折叠区 -->
        <div class="dim-collapse">
          <button class="dim-toggle" @click="dimExpanded = !dimExpanded">
            <span>审查维度</span>
            <span class="dim-summary">{{ dimExpanded ? '▲ 收起' : `▼ 自定义（${dimensions.filter(d => d.on).length}/${dimensions.length} 项）` }}</span>
            <span class="dim-hint">全量审查 · 维度选择仅影响结果聚焦展示</span>
          </button>
          <div v-show="dimExpanded" class="check-grid">
            <el-checkbox v-for="d in dimensions" :key="d.key" v-model="d.on" :label="d.label" />
          </div>
        </div>
        <!-- 运行中：换成终止按钮；否则：启动按钮 -->
        <el-button
          v-if="auditState === 'running'"
          class="run-btn abort-btn"
          :loading="false"
          @click="onAbort"
        >
          ✕ 终止审查
        </el-button>
        <el-button
          v-else
          type="primary"
          class="run-btn"
          :loading="session.busy"
          :disabled="session.step < 1 || session.busy || !contractType"
          @click="onAudit"
        >
          <el-icon><MagicStick /></el-icon>启动合规审查
        </el-button>

        <!-- 同步接口没有服务端阶段百分比：运行中只展示不定进度，完成后才显示 100%。 -->
        <div v-if="auditState !== 'idle'" class="audit-progress-wrap">
          <div class="audit-progress-head">
            <span class="audit-progress-label">{{ auditDisplay.label }}</span>
            <span v-if="auditDisplay.percentage !== null" class="audit-progress-pct mono">
              {{ auditDisplay.percentage }}%
            </span>
          </div>
          <div class="audit-progress-track">
            <div
              class="audit-progress-fill"
              :class="[auditState, { indeterminate: auditDisplay.indeterminate }]"
              :style="auditDisplay.percentage === null ? undefined : { width: `${auditDisplay.percentage}%` }"
            />
          </div>
        </div>
      </el-card>
    </div>

    <!-- 右栏：结果 -->
    <div class="right-stack">
      <el-card shadow="never" class="result-panel">
        <template #header><span class="panel-title">智能审查结果</span></template>
        <!-- 3 步引导：未上传 / 已上传未审查时显示，代替纯文字空状态 -->
        <div v-if="session.step < 2" class="onboard">
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

        <template v-else>
          <div class="result-head">
            <div>
              <span class="eyebrow mono">当前查看</span>
              <h2>{{ session.filename }}</h2>
            </div>
            <el-button :icon="'Document'" @click="annotationOpen = true">查看合同全文批注</el-button>
          </div>

          <div v-if="session.requiresReview" class="ocr-review-alert" role="alert">
            <el-icon><WarningFilled /></el-icon>
            <div>
              <strong>扫描件需人工复核</strong>
              <p>
                {{ session.reviewReason || 'OCR 结果未达到自动采信门槛' }}
                · OCR 置信度 {{ formatOcrConfidence(session.ocrConfidence) }}
              </p>
            </div>
          </div>

          <div class="result-kpis">
            <div class="kpi-mini">
              <span>审查状态</span>
              <strong class="mono">{{ session.requiresReview ? '待人工复核' : '已完成' }}</strong>
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

          <div class="result-two-col">
            <section class="result-col">
              <div class="col-head"><h2>风险清单</h2><el-tag type="danger" size="small">{{ session.riskCount }} 条</el-tag></div>
              <div class="risk-list">
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
                >
                  <div class="risk-head">
                    <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}风险</el-tag>
                    <span class="risk-cat">{{ r.category }}</span>
                    <el-tag size="small" effect="plain" class="status-tag">{{ statusLabel[r.review_status] }}</el-tag>
                  </div>
                  <p class="risk-line">{{ r.suggestion }}</p>
                  <div class="risk-evidence" :class="{ 'is-missing': !r.rag_sources?.length }">
                    <span class="evidence-dot" />
                    <span>
                      {{ r.rag_sources?.length
                        ? `${r.rag_sources.length} 条可靠依据`
                        : '无可靠依据 · 待人工复核' }}
                    </span>
                    <span class="risk-confidence mono">{{ r.confidence }}%</span>
                  </div>
                  <span class="review-cta">
                    {{ _DONE_STATUS.has(r.review_status) ? '查看详情' : '进入复核' }}
                    <el-icon><ArrowRight /></el-icon>
                  </span>
                </article>
              </div>
            </section>
            <section class="result-col">
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
    </div>

    <RiskReviewDrawer
      v-model="drawerOpen"
      :risk="activeRisk"
      @confirm="confirmRisk"
      @ignore="ignoreRisk"
    />
    <AnnotationModal v-model="annotationOpen" :risks="session.risks" :filename="session.filename" />

    <!-- 批量上传对话框 -->
    <el-dialog v-model="batchOpen" title="批量合同上传" width="600px" :before-close="closeBatch">
      <el-upload
        multiple
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf,.docx,.txt"
        drag
        :on-change="onBatchFileChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽合同文件到此，或<em>点击选择</em><p class="upload-hint">支持50份以上批量处理 · PDF / Word / TXT</p></div>
      </el-upload>

      <div v-if="batchRows.length" class="batch-list">
        <div v-for="(item, i) in batchRows" :key="item.id" class="batch-item" :class="{ 'failed-item': item.status === 'failed' }">
          <span class="batch-name mono" :title="item.error || item.filename">{{ item.filename }}</span>
          <el-tag
            v-if="item.requires_review"
            type="warning"
            size="small"
            effect="dark"
            class="batch-tag"
          >{{ reviewStatusLabel(item) }}</el-tag>
          <el-tag
            v-else-if="item.status === 'done'"
            type="success"
            size="small"
            effect="light"
            class="batch-tag"
          >{{ batchStatusLabel[item.status] }}</el-tag>
          <el-tag
            v-else-if="item.status === 'failed'"
            type="danger"
            size="small"
            effect="dark"
            class="batch-tag batch-error"
          >{{ item.error || batchStatusLabel[item.status] }}</el-tag>
          <el-tag
            v-else
            :type="item.status === 'pending' || item.status === 'queued' ? 'info' : 'warning'"
            size="small"
            effect="light"
            class="batch-tag"
          >{{ batchStatusLabel[item.status] }}</el-tag>
          <el-button v-if="item.status === 'pending'" size="small" :icon="'Delete'" circle plain
            @click="removeBatchItem(i)" />
        </div>
        <div v-if="batchStore.batch" class="batch-progress">
          <el-progress :percentage="batchStore.progress" :stroke-width="6" />
          <div class="batch-summary mono">
            批次 #{{ batchStore.batch.id }} · 共 {{ batchStore.batch.total }} 份 ·
            已处理 {{ batchStore.batch.completed }} · 失败 {{ batchStore.batch.failed }}
          </div>
        </div>
        <div v-else class="batch-summary mono">
          已选择 {{ batchItems.length }} 份，提交后由服务端异步处理
        </div>
      </div>

      <template #footer>
        <el-button @click="closeBatch">关闭</el-button>
        <el-button
          v-if="batchStore.batch && batchStore.isTerminal"
          @click="resetBatch"
        >新建批次</el-button>
        <el-button
          v-if="batchStore.batch?.failed"
          type="warning"
          :loading="batchStore.loading"
          @click="retryFailedBatch"
        >
          重试失败项（{{ batchStore.batch.failed }}）
        </el-button>
        <el-button
          v-if="!batchStore.batch"
          type="primary"
          :loading="batchStore.loading"
          :disabled="!batchItems.length || !contractType"
          @click="startBatchUpload"
        >
          提交审查（{{ batchItems.length }} 份）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.audit-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
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
  min-height: calc(100vh - 124px);
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
