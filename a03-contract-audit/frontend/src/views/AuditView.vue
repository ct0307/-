<script setup lang="ts">
// 合同合规审查（真实接口核心闭环）：上传→解析→审查→复核→生成整改。
// 闭环逻辑迁移自 WorkbenchView，数据落 audit-session store。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadRawFile } from 'element-plus'
import { getLookups } from '@/api/admin'

// 用户选文件后立即显示名称（不等后端返回），上传完成后由 session.filename 接管
const pendingFilename = ref('')
import type { RiskOut } from '@/api/types'
import { useAuditSessionStore } from '@/stores/audit-session'
import { useRectifyStore } from '@/stores/rectify'
import { useNotifyStore } from '@/stores/notify'
import { useAuthStore } from '@/stores/auth'
import { useBatchStore } from '@/stores/batch'
import RiskReviewDrawer from '@/components/audit/RiskReviewDrawer.vue'
import AnnotationModal from '@/components/audit/AnnotationModal.vue'
import { auditProgressDisplay, type AuditUiState } from '@/utils/audit-progress'

const session = useAuditSessionStore()
const rectify = useRectifyStore()
const notify = useNotifyStore()
const auth = useAuthStore()
const batchStore = useBatchStore()
const route = useRoute()
const router = useRouter()

const department = ref('采购中心') // 保留兼容（批量上传可能引用），实际展示改用 auth.department
const contractType = ref('软件开发外包合同')
const dimExpanded = ref(false) // 审查维度折叠面板，默认收起

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

const auditState = ref<AuditUiState>('idle')
const auditDisplay = computed(() => auditProgressDisplay(auditState.value))

// —— 触发审查（真接口）——
async function onAudit() {
  if (!session.contractId) {
    ElMessage.warning('请先上传合同')
    return
  }
  auditState.value = 'running'
  try {
    await session.runAudit(dimensions.value.filter(d => d.on).map(d => d.key))
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
        <template #header><span class="panel-title">合同信息 &amp; 审查配置</span></template>
        <div class="form-grid">
          <label>合同类型
            <el-select v-model="contractType" size="default" filterable>
              <el-option v-for="t in contractTypeOptions" :key="t" :label="t" :value="t" />
            </el-select>
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
          :disabled="session.step < 1 || session.busy"
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

      <div v-if="batchRows.length" class="batch-list">
        <div v-for="(item, i) in batchRows" :key="item.id" class="batch-item" :class="{ 'failed-item': item.status === 'failed' }">
          <span class="batch-name mono" :title="item.error || item.filename">{{ item.filename }}</span>
          <el-tag
            v-if="item.status === 'done'"
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
          :disabled="!batchItems.length"
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
/* 归属部门只读展示 */
.dept-readonly {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
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
  padding: 10px 0 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--ivory-dim);
  text-align: left;
}
.dim-toggle:hover { color: var(--ivory); }
.dim-summary { font-size: 12px; color: var(--brass); }
.dim-hint {
  margin-left: auto;
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
/* 命中用户关注维度的卡片：左侧加亮铜色竖线强调 */
.risk-card.dim-focus {
  border-color: var(--brass);
  background: var(--brass-soft);
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
.batch-error {
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
</style>
