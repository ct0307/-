<script setup lang="ts">
// 风险复核抽屉：命中原文 / 依据 / 建议 + 底部操作 + AI 追问对话。
// 追问上下文绑定当前风险条款，历史在抽屉内保留，关闭/切换风险自动清空。
import { computed, ref, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import type { RiskOut } from '@/api/types'
import { chatWithRisk, type ChatMessage } from '@/api/chat'

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

// —— 追问对话 ——
const messages = ref<ChatMessage[]>([])
const userInput = ref('')
const chatLoading = ref(false)
const chatListRef = ref<HTMLElement | null>(null)

// 风险切换时清空对话历史
watch(() => props.risk?.id, () => {
  messages.value = []
  userInput.value = ''
})

async function sendMessage() {
  const text = userInput.value.trim()
  if (!text || !props.risk || chatLoading.value) return

  messages.value.push({ role: 'user', content: text })
  userInput.value = ''
  chatLoading.value = true
  scrollToBottom()

  try {
    const res = await chatWithRisk(props.risk, text, messages.value.slice(0, -1))
    messages.value.push({ role: 'assistant', content: res.reply })
  } catch {
    ElMessage.error('AI 暂时不可用，请稍后重试')
    messages.value.pop() // 移除刚推入的用户消息，避免假历史
  } finally {
    chatLoading.value = false
    scrollToBottom()
  }
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
  <el-drawer v-model="visible" title="风险复核" size="480px" :with-header="true">
    <template v-if="risk">
      <!-- 风险详情 -->
      <div class="rd-head">
        <el-tag :type="levelMeta[risk.level].type" size="small">{{ levelMeta[risk.level].label }}</el-tag>
        <span class="rd-cat">{{ risk.category }}</span>
        <el-tag size="small" effect="plain" class="mono">置信度 {{ risk.confidence }}</el-tag>
      </div>

      <section class="rd-block">
        <h4>命中原文</h4>
        <p class="rd-clause annotate">{{ risk.original_text }}</p>
      </section>
      <section class="rd-block">
        <h4>法规 / 规则依据</h4>
        <p class="rd-text">{{ risk.basis }}</p>
      </section>
      <section class="rd-block">
        <h4>修改建议</h4>
        <p class="rd-text">{{ risk.suggestion }}</p>
      </section>

      <el-alert
        type="warning"
        :closable="false"
        title="本结论由系统自动生成，仅供参考，以人工复核为准。"
        class="rd-disclaimer"
      />

      <!-- 追问区域 -->
      <div class="chat-section">
        <div class="chat-header">
          <el-icon><ChatDotRound /></el-icon>
          <span>向 AI 追问</span>
          <span class="chat-hint">基于上方条款上下文作答</span>
        </div>

        <!-- 消息列表 -->
        <div ref="chatListRef" class="chat-list" :class="{ 'has-messages': messages.length }">
          <div v-if="messages.length === 0" class="chat-empty">
            <p>可以就这条风险向 AI 追问，例如：</p>
            <ul>
              <li>「这个违约上限在行业里正常吗？」</li>
              <li>「我方有哪些谈判空间？」</li>
              <li>「类似条款的常见改写方式是什么？」</li>
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
              <p class="msg-text">{{ m.content }}</p>
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
  margin-bottom: 16px;
}
.rd-cat {
  font-family: var(--serif);
  font-weight: 600;
  font-size: 15px;
  color: var(--ivory);
}
.rd-block {
  margin-bottom: 16px;
}
.rd-block h4 {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--brass);
  font-family: var(--mono);
  letter-spacing: 0.05em;
}
.rd-clause {
  margin: 0;
  padding: 10px 12px;
  line-height: 1.7;
  color: var(--ivory);
  font-family: var(--serif);
}
.rd-text {
  margin: 0;
  line-height: 1.7;
  color: var(--ivory-dim);
  font-size: 13px;
}
.rd-disclaimer {
  margin-top: 10px;
}

/* —— 追问区域 —— */
.chat-section {
  margin-top: 20px;
  border-top: 2px solid var(--brass);
  padding-top: 14px;
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
  border-radius: 4px;
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
</style>
