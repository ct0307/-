<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { confirmSignDate, getSignDate } from '@/api/contract'
import type { SignDateConfirmation } from '@/api/types'

const props = defineProps<{ contractId: number; disabled?: boolean; canEdit: boolean; refreshKey?: number }>()
const emit = defineEmits<{ confirmed: [value: SignDateConfirmation]; loaded: [value: SignDateConfirmation] }>()
const value = ref<SignDateConfirmation | null>(null)
const draft = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
let generation = 0
const validDate = computed(() => /^\d{4}-\d{2}-\d{2}$/.test(draft.value)
  && !Number.isNaN(Date.parse(`${draft.value}T00:00:00Z`))
  && new Date(`${draft.value}T00:00:00Z`).toISOString().slice(0, 10) === draft.value)
const changed = computed(() => !value.value?.confirmed || draft.value !== value.value.sign_date)

function displayError(problem: unknown, fallback: string) {
  return problem instanceof Error ? problem.message : fallback
}

async function load() {
  const requestGeneration = ++generation
  loading.value = true
  error.value = ''
  try {
    const response = await getSignDate(props.contractId)
    if (requestGeneration !== generation) return
    if (response.contract_id !== props.contractId) throw new Error('签订日期读取失败，请重试')
    value.value = response
    emit('loaded', response)
    const matched = response.sign_date.match(/^(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?$/)
    draft.value = matched ? `${matched[1]}-${matched[2]!.padStart(2, '0')}-${matched[3]!.padStart(2, '0')}` : ''
  } catch (problem) {
    if (requestGeneration === generation) error.value = displayError(problem, '签订日期读取失败，请重试')
  } finally {
    if (requestGeneration === generation) loading.value = false
  }
}

watch(() => [props.contractId, props.refreshKey], () => { value.value = null; draft.value = ''; void load() }, { immediate: true })

async function submit() {
  if (!validDate.value || props.disabled || !props.canEdit || saving.value) return
  const requestGeneration = generation
  saving.value = true
  error.value = ''
  try {
    const response = await confirmSignDate(props.contractId, draft.value)
    if (requestGeneration !== generation) return
    value.value = response
    emit('confirmed', response)
  } catch (problem) {
    if (requestGeneration === generation) error.value = displayError(problem, '日期确认失败，请重试')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="sign-date" :aria-label="`合同 ${contractId} 签订日期确认`">
    <span v-if="loading" role="status">正在读取签订日期…</span>
    <template v-else-if="value">
      <p class="date-status" :class="{ confirmed: value.confirmed }">
        {{ value.confirmed ? `已确认 · ${value.confirmed_by_name || value.confirmed_by}` : '未确认 · 法规适用时点未知' }}
        <time v-if="value.confirmed_at" :datetime="value.confirmed_at"> · {{ new Date(value.confirmed_at).toLocaleString('zh-CN') }}</time>
      </p>
      <p v-if="!value.sign_date" class="date-hint">未检出签订日期，请核对原文后填写</p>
      <p v-else-if="!value.confirmed" class="date-hint">自动识别：{{ value.sign_date }}，请核对原文</p>
      <div class="date-controls">
        <label :for="`sign-date-${contractId}`">签订日期</label>
        <input :id="`sign-date-${contractId}`" v-model="draft" type="date" :disabled="disabled || !canEdit || saving" aria-label="签订日期">
        <el-button v-if="canEdit" size="small" :loading="saving" :disabled="disabled || !validDate || !changed" @click="submit">{{ value.confirmed ? '更新确认日期' : '确认签订日期' }}</el-button>
      </div>
      <p v-if="canEdit && changed" class="date-hint">确认日期仅确定法规适用时点；已完成的审查需重新运行。</p>
      <p v-if="value.audit_invalidated" class="date-warning">签订日期已确认或变更，请重新审查；历史结果不能用于当前终审。</p>
    </template>
    <div v-if="error" class="date-error" role="alert">{{ error }} <el-button v-if="!value" link size="small" @click="load">重试读取日期</el-button></div>
  </section>
</template>

<style scoped>
.sign-date { min-width: 0; margin-top: 9px; color: var(--ivory-dim); font-size: 12px; overflow-wrap: anywhere; }
.date-status, .date-hint, .date-warning { margin: 5px 0; line-height: 1.5; }
.date-status, .date-warning { color: var(--amber); }
.date-status.confirmed { color: var(--sage); }
.date-hint { color: var(--muted); font-size: 11px; }
.date-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.date-controls input { min-width: 0; max-width: 100%; width: 138px; border: 1px solid var(--line); border-radius: var(--r-sm); padding: 5px; background: var(--ink-3); color: var(--ivory); font: inherit; }
.date-controls input:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }
.date-controls input:disabled { opacity: .65; }
.date-error { color: var(--seal); margin-top: 6px; }
</style>
