<script setup lang="ts">
// 合同合规审查（真实接口核心闭环）：上传→解析→审查→复核→生成整改。
// 闭环逻辑迁移自 WorkbenchView，数据落 audit-session store。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadRawFile } from 'element-plus'
import { getLookups } from '@/api/admin'
import { batchUploadContracts, auditContract, type BatchUploadResult } from '@/api/contract'

// 用户选文件后立即显示名称（不等后端返回），上传完成后由 session.filename 接管
const pendingFilename = ref('')
import type { RiskOut } from '@/api/types'
import { useAuditSessionStore } from '@/stores/audit-session'
import { useRectifyStore } from '@/stores/rectify'
import { useNotifyStore } from '@/stores/notify'
import { useAuthStore } from '@/stores/auth'
import RiskReviewDrawer from '@/components/audit/RiskReviewDrawer.vue'
import AnnotationModal from '@/components/audit/AnnotationModal.vue'

const session = useAuditSessionStore()
const rectify = useRectifyStore()
const notify = useNotifyStore()
const auth = useAuthStore()

const department = ref('采购中心')
const contractType = ref('软件开发外包合同')

// 降级默认值（接口失败时兜底）
const _DEFAULT_DEPTS = ['采购中心', '销售部', '研发部', '法务部', '财务部', '人力资源部', '行政部', '运营部']
const _DEFAULT_CTYPES = ['软件开发外包合同', '技术服务合同', '采购合同', '销售合同', '劳动合同', '租赁合同', '保密协议', '合作协议']

const departmentOptions = ref<string[]>(_DEFAULT_DEPTS)
const contractTypeOptions = ref<string[]>(_DEFAULT_CTYPES)

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

// 审查维度（对齐 demo，仅前端展示，不改后端契约）
const dimensions = ref([
  { key: 'legal', label: '法律条款合规性', on: true },
  { key: 'risk', label: '风险条款识别', on: true },
  { key: 'payment', label: '金额与付款条款', on: true },
  { key: 'breach', label: '违约责任分析', on: true },
  { key: 'ip', label: '知识产权条款', on: false },
  { key: 'confidentiality', label: '保密条款审查', on: false },
  { key: 'termination', label: '终止与解除条款', on: false },
  { key: 'dispute', label: '争议解决条款', on: false },
])

// —— 上传 + 解析（真接口）——
function onFileChange(uploadFile: { raw?: UploadRawFile }) {
  if (uploadFile.raw) onFile(uploadFile.raw)
}

async function onFile(file: UploadRawFile) {
  pendingFilename.value = file.name // 立即显示文件名，不等后端返回
  try {
    await session.uploadAndParse(file, contractType.value)
    pendingFilename.value = '' // 后端已返回 session.filename，清除 pending 态
    ElMessage.success('上传并解析完成')
  } catch {
    pendingFilename.value = '' // 失败时清除，避免残留
    ElMessage.error('上传或解析失败')
  }
}

// —— 审查进度模拟（方案A：纯前端，无需后端改动）——
const auditProgress = ref(0)
const auditProgressLabel = ref('')
const auditState = ref<'idle' | 'running' | 'done' | 'failed'>('idle')

// 四阶段：目标百分比 + 标签 + 模拟持续时间（ms）
const _AUDIT_STEPS = [
  { pct: 15, label: '解析合同文本…',   ms: 800 },
  { pct: 55, label: '法务 Agent 分析中…', ms: 3000 },
  { pct: 85, label: '财务 Agent 审查中…', ms: 2500 },
  { pct: 99, label: '生成风险报告…',   ms: 1500 },
]

let _progressTimer: ReturnType<typeof setInterval> | null = null

function _startProgress() {
  auditProgress.value = 0
  auditState.value = 'running'
  auditProgressLabel.value = '准备中…'
  let idx = 0
  let stepStart = Date.now()
  _progressTimer = setInterval(() => {
    if (idx >= _AUDIT_STEPS.length) return
    const s = _AUDIT_STEPS[idx]
    const prev = idx === 0 ? 0 : _AUDIT_STEPS[idx - 1].pct
    const frac = Math.min((Date.now() - stepStart) / s.ms, 1)
    auditProgress.value = Math.round(prev + (s.pct - prev) * frac)
    auditProgressLabel.value = s.label
    if (frac >= 1) { idx++; stepStart = Date.now() }
  }, 60)
}

function _clearProgress() {
  if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null }
}

// —— 触发审查（真接口）——
async function onAudit() {
  if (!session.contractId) {
    ElMessage.warning('请先上传合同')
    return
  }
  _startProgress()
  try {
    await session.runAudit()
    _clearProgress()
    auditProgress.value = 100
    auditProgressLabel.value = '审查完成'
    auditState.value = 'done'
    const n = session.riskCount
    ElMessage.success(`审查完成，检出 ${n} 条风险`)
    if (session.levelCounts.high > 0) {
      notify.push('alert', '高风险预警', `${session.filename} 检出 ${session.levelCounts.high} 项高风险条款。`)
    }
  } catch {
    _clearProgress()
    auditProgress.value = 0
    auditProgressLabel.value = '审查失败，请重试'
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
  _clearProgress()
  auditProgress.value = 0
  auditProgressLabel.value = '已中止'
  auditState.value = 'idle'
  ElMessage.info('审查已中止')
}

// —— 风险排序：待复核在前（high→medium→low），已处理（confirmed/ignored）沉底 ——
const _LEVEL_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 }
const _DONE_STATUS = new Set(['confirmed', 'ignored'])
const sortedRisks = computed(() =>
  [...session.risks].sort((a, b) => {
    const doneA = _DONE_STATUS.has(a.review_status) ? 1 : 0
    const doneB = _DONE_STATUS.has(b.review_status) ? 1 : 0
    if (doneA !== doneB) return doneA - doneB
    return (_LEVEL_ORDER[a.level] ?? 9) - (_LEVEL_ORDER[b.level] ?? 9)
  })
)

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

interface BatchItem {
  file: File
  status: 'pending' | 'uploading' | 'success' | 'failed'
  contractId?: number
  error?: string
}

const batchItems = ref<BatchItem[]>([])
const batchUploading = ref(false)

function onBatchFileChange(uploadFile: { raw: File }) {
  if (batchItems.value.length >= 200) {
    ElMessage.warning('单次最多选择 200 份')
    return
  }
  if (!batchItems.value.find((i) => i.file.name === uploadFile.raw.name)) {
    batchItems.value.push({ file: uploadFile.raw, status: 'pending' })
  }
}

function removeBatchItem(idx: number) {
  batchItems.value.splice(idx, 1)
}

async function startBatchUpload() {
  const pending = batchItems.value.filter((i) => i.status === 'pending')
  if (!pending.length) return
  batchUploading.value = true
  pending.forEach((i) => (i.status = 'uploading'))
  try {
    const results: BatchUploadResult[] = await batchUploadContracts(
      pending.map((i) => i.file),
      contractType.value,
    )
    results.forEach((r, idx) => {
      const item = pending[idx]
      if (!item) return
      item.status = r.status
      item.contractId = r.contract_id
      item.error = r.error
    })
    const ok = results.filter((r) => r.status === 'success').length
    ElMessage.success(`批量上传完成：${ok}/${results.length} 份成功`)
  } catch {
    pending.forEach((i) => (i.status = 'failed'))
    ElMessage.error('批量上传失败，请检查后端连接')
  } finally {
    batchUploading.value = false
  }
}

// A6：批量上传成功后一键触发全部审查
const batchAuditing = ref(false)
const batchSuccessIds = computed(() =>
  batchItems.value.filter((i) => i.status === 'success' && i.contractId).map((i) => i.contractId as number),
)

async function startBatchAudit() {
  if (!batchSuccessIds.value.length) return
  batchAuditing.value = true
  let done = 0
  for (const cid of batchSuccessIds.value) {
    try { await auditContract(cid) } catch { /* 单份失败不中断 */ }
    done++
  }
  batchAuditing.value = false
  ElMessage.success(`已触发 ${done} 份合同审查，可在审查页查看结果`)
}

function closeBatch() {
  batchOpen.value = false
  batchItems.value = []
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
        <!-- 上传中：立即显示文件名 + loading；上传完成：切换为 session.filename -->
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
        <div v-else-if="pendingFilename" class="filename mono pending">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在上传 {{ pendingFilename }}…
        </div>
        <!-- 批量上传入口 -->
        <el-button class="batch-btn" size="small" :icon="'Files'" @click="batchOpen = true">
          批量上传（支持50份以上）
        </el-button>
      </el-card>

      <el-card shadow="never" class="config-panel">
        <template #header><span class="panel-title">审查维度配置</span></template>
        <div class="form-grid">
          <label>业务部门
            <el-select v-model="department" size="default" filterable>
              <el-option v-for="d in departmentOptions" :key="d" :label="d" :value="d" />
            </el-select>
          </label>
          <label>合同类型
            <el-select v-model="contractType" size="default" filterable>
              <el-option v-for="t in contractTypeOptions" :key="t" :label="t" :value="t" />
            </el-select>
          </label>
        </div>
        <div class="check-grid">
          <el-checkbox v-for="d in dimensions" :key="d.key" v-model="d.on" :label="d.label" />
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
          :disabled="session.step < 1 || session.busy"
          @click="onAudit"
        >
          <el-icon><MagicStick /></el-icon>启动合规审查
        </el-button>

        <!-- 审查进度条：运行中/完成/失败三态 -->
        <div v-if="auditState !== 'idle'" class="audit-progress-wrap">
          <div class="audit-progress-head">
            <span class="audit-progress-label">{{ auditProgressLabel }}</span>
            <span class="audit-progress-pct mono">{{ auditProgress }}%</span>
          </div>
          <div class="audit-progress-track">
            <div
              class="audit-progress-fill"
              :class="auditState"
              :style="{ width: `${auditProgress}%` }"
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

          <div class="result-kpis">
            <div class="kpi-mini">
              <span>审查状态</span><strong class="mono">已完成</strong>
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
                  :class="[`lvl-${r.level}`, { reviewed: _DONE_STATUS.has(r.review_status) }]"
                  @click="openReview(r)"
                >
                  <div class="risk-head">
                    <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}风险</el-tag>
                    <span class="risk-cat">{{ r.category }}</span>
                    <el-tag size="small" effect="plain" class="status-tag">{{ statusLabel[r.review_status] }}</el-tag>
                  </div>
                  <p class="risk-line">{{ r.suggestion }}</p>
                  <span class="review-cta">
                    {{ _DONE_STATUS.has(r.review_status) ? '查看详情 →' : '进入复核 →' }}
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

      <div v-if="batchItems.length" class="batch-list">
        <div v-for="(item, i) in batchItems" :key="i" class="batch-item" :class="{ 'failed-item': item.status === 'failed' }">
          <span class="batch-name mono">{{ item.file.name }}</span>
          <el-tag v-if="item.status === 'pending'" size="small" effect="plain" class="batch-tag">待上传</el-tag>
          <el-tag v-else-if="item.status === 'uploading'" type="warning" size="small" effect="light" class="batch-tag">上传中…</el-tag>
          <el-tag v-else-if="item.status === 'success'" type="success" size="small" effect="light" class="batch-tag">✓ #{{ item.contractId }}</el-tag>
          <el-tag v-else type="danger" size="small" effect="dark" class="batch-tag">✗ {{ item.error || '失败' }}</el-tag>
          <el-button v-if="item.status === 'pending'" size="small" :icon="'Delete'" circle plain
            @click="removeBatchItem(i)" />
        </div>
        <div class="batch-summary mono">
          共 {{ batchItems.length }} 份 ·
          成功 {{ batchItems.filter(i => i.status === 'success').length }} ·
          失败 {{ batchItems.filter(i => i.status === 'failed').length }}
        </div>
      </div>

      <template #footer>
        <el-button @click="closeBatch">关闭</el-button>
        <!-- A6：上传成功后一键触发全部审查 -->
        <el-button
          v-if="batchSuccessIds.length"
          type="warning"
          :loading="batchAuditing"
          @click="startBatchAudit"
        >
          一键触发全部审查（{{ batchSuccessIds.length }} 份）
        </el-button>
        <el-button
          type="primary"
          :loading="batchUploading"
          :disabled="!batchItems.filter(i => i.status === 'pending').length"
          @click="startBatchUpload"
        >
          开始上传（{{ batchItems.filter(i => i.status === 'pending').length }} 份）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.audit-grid {
  display: grid;
  grid-template-columns: 400px 1fr;
  gap: 20px;
  align-items: start;
}
.left-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
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
.check-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  margin-bottom: 16px;
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
  transition: width 0.06s linear;
  background: var(--brass);
}
.audit-progress-fill.done   { background: var(--sage); }
.audit-progress-fill.failed { background: var(--seal); }
.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.result-head h2 {
  margin: 2px 0 0;
  font-size: 18px;
}
.eyebrow {
  font-size: 11px;
  color: var(--brass);
  letter-spacing: 0.06em;
}
.result-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 16px 0;
}
.kpi-mini {
  background: var(--ink-3);
  border-radius: var(--r-md);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  grid-template-columns: 1.4fr 1fr;
  gap: 20px;
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
  letter-spacing: 0.02em;
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
  align-items: flex-start;
  gap: 0;
  padding: 32px 20px;
  justify-content: center;
}
.onboard-step {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex: 1;
  max-width: 200px;
  opacity: 0.45;
  transition: opacity 0.2s ease;
  position: relative;
}
.onboard-step.active { opacity: 1; }
.onboard-step.done   { opacity: 0.7; }
.step-num {
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid var(--brass);
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
  right: -18px;
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
.risk-card {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 12px 14px;
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
  border-color: var(--brass);
  box-shadow: var(--shadow-sm);
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
.review-cta {
  font-size: 12px;
  color: var(--brass);
  margin-top: 6px;
  display: inline-block;
}
.metadata-list {
  margin: 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px 14px;
  font-size: 13px;
}
.metadata-list dt {
  color: var(--ivory-dim);
}
.metadata-list dd {
  margin: 0;
  color: var(--ivory);
  font-family: var(--mono);
}
.metadata-list dd.warn {
  color: var(--seal);
}
@media (max-width: 1180px) {
  .audit-grid {
    grid-template-columns: 1fr;
  }
  .result-two-col {
    grid-template-columns: 1fr;
  }
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
.failed-item { background: var(--seal-soft) !important; }
.batch-summary {
  font-size: 12px;
  color: var(--muted);
  text-align: right;
  padding-top: 4px;
}
</style>
