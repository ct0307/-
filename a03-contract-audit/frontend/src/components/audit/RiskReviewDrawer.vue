<script setup lang="ts">
// 风险复核抽屉：先展示业务问题和待办，再提供原文、依据与可展开的技术记录。
// 每次独立解释当前风险；显示记录在关闭/切换风险后清空。
import { computed, ref, watch, nextTick } from 'vue'
import { ChatDotRound, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { RiskOut } from '@/api/types'
import { chatWithRisk } from '@/api/chat'
import { useRiskChat } from '@/composables/useRiskChat'
import { isEvidenceVerified, relationEvidenceMeta, riskEvidenceMeta, validationModeLabel } from '@/utils/risk-evidence'
import { applicabilityMeta, ruleStatusMeta } from '@/utils/audit-trace'
import { useAuthStore } from '@/stores/auth'
import { originalTextLocated, riskReviewGuidance } from '@/utils/professional-review'

const props = defineProps<{
  modelValue: boolean
  risk: RiskOut | null
}>()
const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  confirm: [risk: RiskOut]
  ignore: [risk: RiskOut]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高风险', type: 'danger' },
  medium: { label: '中风险', type: 'warning' },
  low: { label: '低风险', type: 'info' },
}

const auth = useAuthStore()
const readingPerspective = ref<'legal' | 'finance'>(auth.role === 'finance' ? 'finance' : 'legal')
const guidance = computed(() => props.risk ? riskReviewGuidance(props.risk) : null)
watch(() => [props.modelValue, props.risk?.id], () => {
  readingPerspective.value = auth.role === 'finance' ? 'finance' : 'legal'
})

// —— 追问对话 ——
const { messages, userInput, chatLoading, sendMessage: send } = useRiskChat(
  () => props.risk, () => props.modelValue, chatWithRisk,
  () => ElMessage.error('AI 暂时不可用，请稍后重试'),
)
const chatListRef = ref<HTMLElement | null>(null)

// 消息变化后滚动到最新回答。
watch(() => messages.value.length, scrollToBottom)

async function sendMessage() {
  const pending = send()
  scrollToBottom()
  await pending
  scrollToBottom()
}

function scrollToBottom() {
  nextTick(() => {
    if (chatListRef.value) {
      chatListRef.value.scrollTop = chatListRef.value.scrollHeight
    }
  })
}

function onEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}
</script>

<template>
  <el-drawer v-model="visible" title="风险复核" size="min(560px, 100vw)" :with-header="true">
    <template v-if="risk">
      <!-- 风险详情 -->
      <div class="rd-head">
        <el-tag :type="levelMeta[risk.level].type" size="small">{{ levelMeta[risk.level].label }}</el-tag>
        <span class="rd-cat">{{ risk.category }}</span>
        <span class="rd-confidence mono">{{ riskEvidenceMeta(risk).label }}</span>
      </div>

      <section class="rd-block evidence-step business-summary">
        <span class="step-index mono">01</span>
        <div class="step-content">
          <h4>业务摘要</h4>
          <p class="rd-text">{{ guidance?.summary }}</p>
          <div class="reading-perspective">
            <el-radio-group v-model="readingPerspective" size="small" aria-label="阅读视角">
              <el-radio-button value="legal">法务视角</el-radio-button>
              <el-radio-button value="finance">财务视角</el-radio-button>
            </el-radio-group>
            <p class="rd-text perspective-focus">{{ readingPerspective === 'finance'
              ? '核对付款条件、金额口径与履约凭据；金额和计算结果以合同及已核验记录为准。'
              : '核对条款效力、法规适用时点与责任分配。' }}</p>
            <p class="rd-subtle">阅读视角仅调整关注提示，共用同一复核记录。</p>
          </div>
        </div>
      </section>

      <section class="rd-block evidence-step">
        <span class="step-index mono">02</span>
        <div class="step-content">
          <h4>下一步核对</h4>
          <ul class="review-next-steps"><li v-for="step in guidance?.nextSteps" :key="step">{{ step }}</li></ul>
        </div>
      </section>
      <section class="rd-block evidence-step">
        <span class="step-index mono">03</span>
        <div class="step-content">
          <h4>修改建议</h4>
          <p class="rd-text">{{ risk.suggestion || '暂无修改建议，请在核对合同和依据后记录处理意见。' }}</p>
        </div>
      </section>

      <section class="rd-block evidence-step">
        <span class="step-index mono">04</span>
        <div class="step-content">
          <template v-if="originalTextLocated(risk)">
            <h4>合同原文（已定位）</h4>
            <p class="rd-clause annotate">{{ risk.original_text }}</p>
            <p class="rd-subtle">文本定位通过仅说明能在合同中找到该段，依据与法律判断仍需分别核对。</p>
          </template>
          <template v-else>
            <h4>合同文本待核对</h4>
            <p class="rd-validation-note">原文定位尚未通过，模型候选不能作为已核验合同原文。</p>
            <details v-if="risk.original_text?.trim()" :key="`candidate-${risk.id}-${modelValue}`" class="review-details candidate-text">
              <summary>查看模型候选文本</summary>
              <p class="rd-subtle">以下为模型提供的待定位候选，请对照合同全文核实。</p>
              <p class="rd-clause">{{ risk.original_text }}</p>
            </details>
            <p v-else class="rd-subtle">暂无候选文本，请对照合同全文核对。</p>
          </template>
        </div>
      </section>

      <section class="rd-block evidence-step" :class="{ 'source-missing': !risk.rag_sources?.length }">
        <span class="step-index mono">05</span>
        <div class="step-content">
          <h4>法规 / 规则依据</h4>
          <p class="rd-subtle">{{ isEvidenceVerified(risk) ? '已核验的风险依据' : '风险提出的依据（待核对）' }}</p>
          <p class="rd-text">{{ risk.basis || '尚未提供明确依据。' }}</p>
          <p class="rd-validation-note">{{ guidance?.supportExplanation }}</p>
          <template v-if="risk.rag_sources?.length">
            <h5 class="source-heading">{{ isEvidenceVerified(risk) ? '已核验来源' : '待核验资料' }}</h5>
            <div v-for="(source, i) in risk.rag_sources" :key="i" class="rag-source-card">
              <div class="rag-source-head">
                <span class="rag-tag" :title="source.source">{{ source.source }}</span>
                <span class="rag-rank mono">#{{ i + 1 }}</span>
              </div>
              <p class="rag-content">{{ source.content }}</p>
            </div>
          </template>
          <div v-else class="missing-evidence" role="alert">
            <el-icon><WarningFilled /></el-icon>
            <div>
              <strong>无可靠依据</strong>
              <p>当前结论必须由人工复核确认，不能直接作为正式审查依据。</p>
            </div>
          </div>
        </div>
      </section>

      <section class="rd-block evidence-step">
        <span class="step-index mono">06</span>
        <div class="step-content">
          <h4>法规适用性</h4>
          <el-tag :type="applicabilityMeta(guidance?.applicability.displayStatus).type" size="small">
            {{ applicabilityMeta(guidance?.applicability.displayStatus).label }}
          </el-tag>
          <p class="rd-validation-note">{{ guidance?.applicability.explanation }}</p>
        </div>
      </section>

      <details :key="`trace-${risk.id}-${modelValue}`" class="review-details technical-details">
        <summary>技术核验与检索记录</summary>
        <p class="rd-subtle">以下保留系统原始记录，供追溯核验过程。</p>
        <p class="rd-text">完整问题说明：{{ risk.risk_reason || '未记录' }}</p>
        <p v-if="risk.support_validation_reason" class="rd-validation-note">支持关系校验：{{ risk.support_validation_reason }}（{{ risk.support_validator_version }}）</p>
        <p v-else class="rd-validation-note">验证器版本：{{ risk.support_validator_version || '未记录' }}</p>
        <p class="rd-validation-note">核验方式：{{ validationModeLabel(risk.support_validation_mode) }}</p>
        <p class="rd-validation-note">核验阶段：{{ risk.support_validation_failed_stage || '未记录' }} · 原因码：{{ risk.support_validation_reason_code || '未记录' }}</p>
        <p v-if="risk.applicability_reason_codes?.length" class="rd-validation-note">适用性原因码：{{ risk.applicability_reason_codes.join('、') }}</p>
        <p v-if="risk.decision_trace?.reason_codes?.length" class="rd-validation-note">决策原因码：{{ risk.decision_trace.reason_codes.join('、') }}</p>
        <p v-if="risk.secondary_review_reason" class="rd-validation-note">二次复核记录：{{ risk.secondary_review_reason }}</p>
        <section v-if="risk.rule_executions?.length" class="rd-block technical-section">
          <h4>规则核验</h4>
          <div v-for="(rule, i) in risk.rule_executions" :key="`${rule.rule_id || 'rule'}-${i}`">
            <div class="trace-row">
              <span>{{ rule.rule_id || '规则' }}<small v-if="rule.rule_version"> · {{ rule.rule_version }}</small></span>
              <el-tag :type="ruleStatusMeta(rule.status).type" size="small">{{ ruleStatusMeta(rule.status).label }}</el-tag>
            </div>
            <p v-if="rule.reason_code" class="rd-subtle">原因码：{{ rule.reason_code }}</p>
            <p v-if="rule.calculation" class="rd-text">{{ rule.calculation }}</p>
          </div>
        </section>
        <section v-if="risk.retrieval_attempts?.length" class="rd-block technical-section candidate-evidence">
          <h4>检索候选与核验记录</h4>
          <p class="rd-validation-note">检索命中需逐条核验。只有通过当前验证规则的资料可作为已核验依据，其余资料需人工复核。</p>
          <div v-for="(attempt, attemptIndex) in risk.retrieval_attempts" :key="attemptIndex">
            <p class="rd-subtle">检索轮次：{{ attempt.attempt || attemptIndex + 1 }} · 候选状态：{{ attempt.candidate_match_status || '未记录' }} · 支持状态：{{ attempt.support_status || '未记录' }}</p>
            <p v-if="attempt.source_ids?.length" class="rd-subtle">来源编号：{{ attempt.source_ids.join('、') }}</p>
            <div v-for="(relation, i) in attempt.evidence_relations || []" :key="i" class="rag-source-card">
              <div class="rag-source-head"><span class="rag-tag">{{ relation.source?.source || '候选来源' }} · {{ relation.source?.evidence_id || relation.source?.chunk_id || relation.source?.id || '未编号' }}</span><el-tag size="small" :type="relationEvidenceMeta(relation, risk).type">{{ relationEvidenceMeta(relation, risk).label }}</el-tag></div>
              <p v-if="relation.source?.content" class="rag-content">{{ relation.source.content }}</p>
              <p class="rag-content">{{ relation.reason || '尚未完成支持关系核验' }}</p>
              <p class="rd-subtle">阶段：{{ relation.failed_stage || '未记录' }} · 原因码：{{ relation.reason_code || '未记录' }} · 版本：{{ relation.validator_version || '未记录' }}</p>
            </div>
          </div>
        </section>
      </details>

      <el-alert
        type="warning"
        :closable="false"
        title="本结论由系统自动生成，仅供参考，以人工复核为准。"
        class="rd-disclaimer"
      />

      <section class="rd-block evidence-step human-review">
        <span class="step-index mono">07</span>
        <div class="step-content">
          <h4>人工复核记录</h4>
          <template v-if="risk.decision_trace?.human_review">
            <p class="rd-text">操作人ID {{ risk.decision_trace.human_review.operator_id }} · {{ risk.decision_trace.human_review.reviewed_at }}</p>
            <p class="rd-text">{{ risk.decision_trace.human_review.reason || '已重置为待复核' }}</p>
          </template>
          <p v-else class="rd-validation-note">暂无人工复核记录。人工确认独立于机器证据核验。</p>
        </div>
      </section>

      <!-- 追问区域 -->
      <div class="chat-section">
        <div class="chat-header">
          <el-icon><ChatDotRound /></el-icon>
          <span>向 AI 追问</span>
          <span class="chat-hint">每次独立解释当前风险，不记忆前文</span>
        </div>

        <!-- 消息列表 -->
        <div ref="chatListRef" class="chat-list" :class="{ 'has-messages': messages.length }">
          <div v-if="messages.length === 0" class="chat-empty">
            <p>可以就这条风险向 AI 追问，例如：</p>
            <ul>
              <li>「请解释这条风险对应的已核验依据。」</li>
              <li>「这些资料有哪些无法判断的事项？」</li>
            </ul>
          </div>
          <template v-else>
            <div
              v-for="(m, i) in messages"
              :key="i"
              class="chat-msg"
              :class="m.role"
            >
              <span class="msg-role">{{ m.role === 'user' ? '你' : 'AI' }}</span>
              <div class="msg-body">
                <p class="msg-text">{{ m.content }}</p>
                <p v-if="m.state && m.state !== 'ANSWERED'" class="rd-validation-note">需人工复核，未形成可采纳结论</p>
                <p v-if="m.references?.length" class="rd-validation-note">引用资料：{{ m.references.map(r => r.evidence_id).join('、') }}（引用编号校验不代表法律结论正确）</p>
              </div>
            </div>
            <div v-if="chatLoading" class="chat-msg assistant loading">
              <span class="msg-role">AI</span>
              <p class="msg-text"><el-icon class="is-loading"><Loading /></el-icon> 思考中…</p>
            </div>
          </template>
        </div>

        <!-- 输入框 -->
        <div class="chat-input-row">
          <el-input
            v-model="userInput"
            type="textarea"
            :rows="2"
            :maxlength="1000"
            placeholder="输入问题，Enter 发送，Shift+Enter 换行"
            :disabled="chatLoading"
            resize="none"
            @keydown.enter="onEnter"
          />
          <el-button
            type="primary"
            :loading="chatLoading"
            :disabled="!userInput.trim()"
            class="send-btn"
            @click="sendMessage"
          >
            发送
          </el-button>
        </div>
      </div>
    </template>

    <template #footer>
      <el-button @click="risk && emit('ignore', risk)">标记误报</el-button>
      <el-button type="primary" @click="risk && emit('confirm', risk)">确认并生成整改项</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.rd-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.rd-cat {
  font-family: var(--sans);
  font-weight: 600;
  font-size: 15px;
  color: var(--ivory);
  min-width: 0;
  overflow-wrap: anywhere;
}
.rd-confidence {
  margin-left: auto;
  color: var(--muted);
  font-size: 11px;
}
.rd-block {
  margin-bottom: 0;
}
.evidence-step {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 0;
  position: relative;
}
.evidence-step:not(:last-of-type)::before {
  content: '';
  position: absolute;
  left: 13px;
  top: 25px;
  bottom: -1px;
  width: 1px;
  background: var(--line);
}
.step-index {
  position: relative;
  z-index: 1;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--ink-2);
  color: var(--brass);
  font-size: 10px;
}
.step-content {
  min-width: 0;
  padding: 2px 0 20px 10px;
}
.rd-block h4 {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--brass);
  font-family: var(--mono);
  letter-spacing: 0;
}
.trace-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 6px 0;
  border-bottom: 1px solid var(--line);
  color: var(--ivory);
  font-size: 12px;
}
.trace-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trace-row small {
  color: var(--muted);
}
.rd-clause {
  margin: 0;
  padding: 10px 12px;
  line-height: 1.7;
  color: var(--ivory);
  font-family: var(--serif);
  background: var(--ink-3);
  border-left: 2px solid var(--brass);
  overflow-wrap: anywhere;
}
.rd-text {
  margin: 0;
  line-height: 1.7;
  color: var(--ivory-dim);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.rd-subtle {
  margin: 7px 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.reading-perspective { margin-top: 12px; }
.perspective-focus { margin-top: 8px; }
.review-next-steps {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--ivory-dim);
  line-height: 1.8;
}
.review-details {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  color: var(--ivory-dim);
  overflow-wrap: anywhere;
}
.review-details summary {
  cursor: pointer;
  color: var(--brass);
  font-size: 13px;
  line-height: 1.6;
}
.review-details summary:focus-visible { outline: 2px solid var(--brass); outline-offset: 3px; }
.technical-details { margin: 0 0 18px 44px; }
.technical-section { margin-top: 16px; }
.source-heading { margin: 12px 0 8px; color: var(--ivory-dim); font-size: 12px; }
.rd-validation-note {
  margin: 8px 0 0;
  color: var(--amber);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.rd-disclaimer {
  margin: 2px 0 0 44px;
  width: calc(100% - 44px);
}
.missing-evidence {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 11px 12px;
  background: var(--amber-soft);
  border-left: 2px solid var(--amber);
  color: var(--amber);
}
.missing-evidence > .el-icon {
  flex: none;
  margin-top: 2px;
}
.missing-evidence strong {
  display: block;
  color: var(--ivory);
  font-size: 13px;
}
.missing-evidence p {
  margin: 3px 0 0;
  color: var(--ivory-dim);
  font-size: 12px;
  line-height: 1.5;
}

/* —— 追问区域 —— */
.chat-section {
  margin: 20px 0 0 44px;
  border-top: 1px solid var(--line);
  padding-top: 16px;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--brass);
}
.chat-hint {
  font-size: 11px;
  color: var(--muted);
  font-weight: 400;
  margin-left: 4px;
}

/* 消息列表 */
.chat-list {
  min-height: 80px;
  max-height: 260px;
  overflow-y: auto;
  margin-bottom: 10px;
  padding: 4px 0;
  scroll-behavior: smooth;
}
.chat-empty {
  padding: 8px 4px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.8;
}
.chat-empty ul {
  margin: 6px 0 0;
  padding-left: 16px;
  color: var(--ivory-dim);
}
.chat-msg {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  align-items: flex-start;
}
.chat-msg.user {
  flex-direction: row-reverse;
}
.msg-role {
  flex: none;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: var(--r-xs);
  line-height: 1.6;
}
.user .msg-role {
  background: var(--brass-soft);
  color: var(--brass);
}
.assistant .msg-role {
  background: var(--ink-3);
  color: var(--ivory-dim);
}
.msg-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ivory);
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-body {
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}
.user .msg-text {
  text-align: right;
}
.chat-msg.loading .msg-text {
  color: var(--muted);
}

/* 输入区 */
.chat-input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.chat-input-row :deep(.el-textarea) {
  flex: 1;
}
.send-btn {
  flex: none;
  height: 54px;
}

/* —— RAG 检索溯源卡片 —— */
.rag-source-card {
  border: 1px solid var(--line);
  border-left: 3px solid var(--brass);
  border-radius: var(--r-sm);
  padding: 8px 10px;
  margin-bottom: 8px;
  background: var(--ink-3);
}
.rag-source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  gap: 6px;
  flex-wrap: wrap;
}
.rag-tag {
  font-size: 11px;
  background: var(--brass-soft);
  color: var(--brass);
  padding: 2px 8px;
  border-radius: var(--r-xs);
  font-family: var(--mono);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rag-rank {
  font-size: 11px;
  color: var(--muted);
  flex: none;
}
.rag-content {
  margin: 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.6;
  overflow-wrap: anywhere;
}
@media (max-width: 640px) {
  .rd-head { flex-wrap: wrap; }
  .rd-confidence { margin-left: 0; flex-basis: 100%; }
  .rd-disclaimer,
  .chat-section,
  .technical-details { margin-left: 0; }
  .rd-disclaimer { width: 100%; }
  .chat-input-row { flex-direction: column; align-items: stretch; }
  .send-btn { width: 100%; height: 36px; }
}
</style>
