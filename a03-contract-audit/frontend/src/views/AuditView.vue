<script setup lang="ts">
// 合同合规审查（真实接口核心闭环）：上传→解析→审查→复核→生成整改。
// 闭环逻辑迁移自 WorkbenchView，数据落 audit-session store。
import { ref } from 'vue'
import { ElMessage, type UploadRawFile } from 'element-plus'
import type { RiskOut } from '@/api/types'
import { useAuditSessionStore } from '@/stores/audit-session'
import { useRectifyStore } from '@/stores/rectify'
import { useNotifyStore } from '@/stores/notify'
import { useDemoStore } from '@/stores/demo'
import RiskReviewDrawer from '@/components/audit/RiskReviewDrawer.vue'
import AnnotationModal from '@/components/audit/AnnotationModal.vue'

const session = useAuditSessionStore()
const rectify = useRectifyStore()
const notify = useNotifyStore()
const demo = useDemoStore()

const department = ref('采购中心')
const contractType = ref('软件开发外包合同')

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
async function onFile(file: UploadRawFile) {
  try {
    await session.uploadAndParse(file, contractType.value)
    ElMessage.success('上传并解析完成')
  } catch {
    ElMessage.error('上传或解析失败')
  }
  return false // 阻止 el-upload 默认上传
}

// —— 触发审查（真接口）——
async function onAudit() {
  if (!session.contractId) {
    ElMessage.warning('请先上传合同')
    return
  }
  try {
    await session.runAudit()
    const n = session.riskCount
    ElMessage.success(`审查完成，检出 ${n} 条风险`)
    if (session.levelCounts.high > 0) {
      notify.push('alert', '高风险预警', `${session.filename} 检出 ${session.levelCounts.high} 项高风险条款。`)
    }
  } catch {
    ElMessage.error('审查失败（需 legal / finance 角色）')
  }
}

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
    rectify.addFromRisk(risk, session.filename || '当前合同', demo.profile.name)
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
}

// 多智能体协同（展示态：预设步骤，审查完成后点亮）
const collabSteps = {
  legal: ['解析合同结构与条款', '比对法规知识库', '标注合规风险', '交接财务复核 →'],
  finance: ['← 接收法务标注', '核对金额与付款节点', '识别财务风险', '汇总协同结论'],
}
</script>

<template>
  <div class="audit-grid">
    <!-- 左栏：上传 + 配置 -->
    <div class="left-stack">
      <el-card shadow="never" class="upload-panel">
        <el-upload
          drag
          :auto-upload="false"
          :show-file-list="false"
          :before-upload="onFile"
          accept=".pdf,.docx,.txt"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">
            拖拽合同到此，或<em>点击选择</em>
            <p class="upload-hint">支持 PDF / Word / TXT</p>
          </div>
        </el-upload>
        <div v-if="session.filename" class="filename mono">
          当前：{{ session.filename }}（合同 #{{ session.contractId }}）
        </div>
      </el-card>

      <el-card shadow="never" class="config-panel">
        <template #header>审查维度配置</template>
        <div class="form-grid">
          <label>业务部门
            <el-select v-model="department" size="default">
              <el-option label="采购中心" value="采购中心" />
              <el-option label="研发外包部" value="研发外包部" />
              <el-option label="市场运营部" value="市场运营部" />
            </el-select>
          </label>
          <label>合同类型
            <el-select v-model="contractType" size="default">
              <el-option label="软件开发外包合同" value="软件开发外包合同" />
              <el-option label="采购合同" value="采购合同" />
              <el-option label="技术服务合同" value="技术服务合同" />
            </el-select>
          </label>
        </div>
        <div class="check-grid">
          <el-checkbox v-for="d in dimensions" :key="d.key" v-model="d.on" :label="d.label" />
        </div>
        <el-button
          type="primary"
          class="run-btn"
          :loading="session.busy"
          :disabled="session.step < 1"
          @click="onAudit"
        >
          <el-icon><MagicStick /></el-icon>启动合规审查
        </el-button>
      </el-card>
    </div>

    <!-- 右栏：结果 -->
    <div class="right-stack">
      <el-card shadow="never" class="result-panel">
        <el-empty v-if="session.step < 2" description="上传合同并启动智能审查，法务 Agent 查合规、财务 Agent 对账目" />

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

          <!-- 多智能体协同双泳道 -->
          <div class="collab">
            <div class="collab-head"><h3>多智能体协同</h3><span class="mono">协同完成</span></div>
            <div class="collab-lanes">
              <div class="lane">
                <div class="lane-head"><el-icon><Stamp /></el-icon><b>法务专家 Agent</b><small>查合规</small></div>
                <div v-for="(s, i) in collabSteps.legal" :key="i" class="collab-step" :class="{ handoff: i === 3 }">
                  <i /><span>{{ s }}</span>
                </div>
              </div>
              <div class="lane">
                <div class="lane-head"><el-icon><Coin /></el-icon><b>财务会计 Agent</b><small>对账目</small></div>
                <div v-for="(s, i) in collabSteps.finance" :key="i" class="collab-step"><i /><span>{{ s }}</span></div>
              </div>
            </div>
          </div>

          <div class="result-two-col">
            <section class="result-col">
              <div class="col-head"><h2>风险清单</h2><el-tag type="danger" size="small">{{ session.riskCount }} 条</el-tag></div>
              <div class="risk-list">
                <article
                  v-for="r in session.risks"
                  :key="r.id"
                  class="risk-card"
                  :class="`lvl-${r.level}`"
                  @click="openReview(r)"
                >
                  <div class="risk-head">
                    <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}风险</el-tag>
                    <span class="risk-cat">{{ r.category }}</span>
                    <el-tag size="small" effect="plain" class="status-tag">{{ statusLabel[r.review_status] }}</el-tag>
                  </div>
                  <p class="risk-line">{{ r.suggestion }}</p>
                  <span class="review-cta">进入复核 →</span>
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
  margin-top: 12px;
  font-size: 12px;
  color: var(--ivory-dim);
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
.collab {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 14px;
  margin-bottom: 18px;
  background: var(--ink-3);
}
.collab-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.collab-head h3 {
  margin: 0;
  font-size: 15px;
}
.collab-head span {
  font-size: 12px;
  color: var(--sage);
}
.collab-lanes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.lane-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-bottom: 8px;
  margin-bottom: 8px;
  border-bottom: 2px solid var(--brass);
  font-size: 13px;
}
.lane:nth-child(2) .lane-head {
  border-bottom-color: var(--sage);
}
.lane-head b {
  color: var(--ivory);
}
.lane-head small {
  color: var(--muted);
}
.collab-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ivory-dim);
  padding: 4px 0;
}
.collab-step i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brass);
  flex: none;
}
.collab-step.handoff {
  color: var(--brass);
  font-weight: 600;
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
.col-head h2 {
  margin: 0;
  font-size: 15px;
}
.risk-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.risk-card {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s var(--ease);
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
  .result-two-col,
  .collab-lanes {
    grid-template-columns: 1fr;
  }
}
</style>
