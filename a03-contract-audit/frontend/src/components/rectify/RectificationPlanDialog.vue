<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { getRectificationParticipants } from '@/api/rectify'
import type { RectificationParticipant, RectificationPlan } from '@/mock/rectify'

const props = defineProps<{
  modelValue: boolean
  riskId: number | null
  initial?: Partial<RectificationPlan>
  saving?: boolean
  error?: string
  confirmed?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [plan: RectificationPlan]
}>()
const form = ref<FormInstance>()
// 明确挑选计划字段，避免完整任务对象中的状态、证据等字段进入更新请求。
function planValues(value?: Partial<RectificationPlan>): RectificationPlan {
  return { owner: value?.owner ?? '', collaborators: [...(value?.collaborators ?? [])], due: value?.due ?? '', note: value?.note ?? '', acceptance_criteria: value?.acceptance_criteria ?? '', contract_stage: value?.contract_stage || 'unknown', handling_method: value?.handling_method || (value?.contract_stage === 'signed' ? 'supplement' : 'revision') }
}
const draft = reactive<RectificationPlan>(planValues())
const participants = ref<RectificationParticipant[]>([])
const loading = ref(false)
const loadError = ref('')
let generation = 0
const rules: FormRules = {
  owner: [{ required: true, message: '请选择已注册的责任人', trigger: 'change' }],
  due: [{ required: true, message: '请选择明确截止日期', trigger: 'change' }],
  note: [{ required: true, whitespace: true, message: '请填写整改措施', trigger: 'blur' }],
  acceptance_criteria: [{ required: true, whitespace: true, message: '请填写验收条件', trigger: 'blur' }],
  handling_method: [{ required: true, message: '请选择处理方式', trigger: 'change' }],
}
async function loadParticipants() {
  const request = ++generation
  if (!props.riskId) {
    loadError.value = '该历史任务缺少来源风险，无法分派人员，请先核对来源。'
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    const rows = await getRectificationParticipants(props.riskId)
    if (request === generation) participants.value = rows
  } catch (error) {
    if (request === generation) loadError.value = error instanceof Error ? error.message : '可分派人员加载失败'
  } finally { if (request === generation) loading.value = false }
}
watch(() => props.modelValue, open => {
  if (!open) { generation++; return }
  Object.assign(draft, planValues(props.initial))
  form.value?.clearValidate()
  void loadParticipants()
})
watch(() => draft.contract_stage, stage => {
  if (stage === 'signed' && draft.handling_method === 'revision') draft.handling_method = 'supplement'
  if (stage === 'unsigned') draft.handling_method = 'revision'
})
async function save() {
  if (!(await form.value?.validate().catch(() => false))) return
  if (loadError.value || loading.value) return
  if (!participants.value.some(person => person.username === draft.owner)) {
    loadError.value = '责任人必须从当前可分派的已注册人员中选择。'
    return
  }
  emit('save', { ...planValues(draft), note: draft.note.trim(), acceptance_criteria: draft.acceptance_criteria.trim() })
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="整改计划" width="600px" class="rectification-plan-dialog" :close-on-click-modal="!saving" :close-on-press-escape="!saving" @update:model-value="emit('update:modelValue', $event)">
    <el-alert v-if="confirmed" type="success" :closable="false" title="风险已确认，请明确整改计划后生成任务。" />
    <el-alert v-if="error" type="error" :closable="false" :title="error" role="alert" />
    <el-alert v-if="loadError" type="error" :closable="false" :title="loadError"><el-button link @click="loadParticipants">重新加载人员</el-button></el-alert>
    <el-form ref="form" :model="draft" :rules="rules" label-position="top" class="plan-form" :disabled="saving">
      <div class="plan-grid">
        <el-form-item label="责任人" prop="owner"><el-select v-model="draft.owner" aria-label="责任人" placeholder="选择已注册人员" filterable :loading="loading"><el-option v-for="person in participants" :key="person.id" :value="person.username" :label="`${person.username} · ${person.department}`" /></el-select></el-form-item>
        <el-form-item label="截止日期" prop="due"><el-date-picker v-model="draft.due" aria-label="截止日期" type="date" value-format="YYYY-MM-DD" placeholder="选择明确截止日期" /></el-form-item>
      </div>
      <el-form-item label="协作人"><el-select v-model="draft.collaborators" aria-label="协作人" multiple filterable placeholder="可选，协作不替代责任"><el-option v-for="person in participants.filter(person => person.username !== draft.owner)" :key="person.id" :value="person.username" :label="`${person.username} · ${person.department}`" /></el-select></el-form-item>
      <el-form-item label="整改措施" prop="note"><el-input v-model="draft.note" aria-label="整改措施" type="textarea" :rows="3" maxlength="2000" placeholder="确认或调整建议，明确需要完成的工作" /></el-form-item>
      <el-form-item label="验收条件" prop="acceptance_criteria"><el-input v-model="draft.acceptance_criteria" aria-label="验收条件" type="textarea" :rows="3" maxlength="2000" placeholder="说明独立复核人应核对的条款、凭证与完成标准" /></el-form-item>
      <div class="plan-grid">
        <el-form-item label="合同阶段"><el-select v-model="draft.contract_stage" aria-label="合同阶段"><el-option label="待确认（暂不可提交复核）" value="unknown" /><el-option label="未签署" value="unsigned" /><el-option label="已签署" value="signed" /></el-select></el-form-item>
        <el-form-item label="处理方式" prop="handling_method"><el-select v-model="draft.handling_method" aria-label="处理方式" placeholder="请选择处理方式"><el-option label="草稿修订" value="revision" :disabled="draft.contract_stage === 'signed'" /><el-option label="补充协议" value="supplement" :disabled="draft.contract_stage === 'unsigned'" /><el-option label="履约措施" value="performance" :disabled="draft.contract_stage === 'unsigned'" /></el-select></el-form-item>
      </div>
      <p class="plan-hint">已签署合同通过补充协议或履约措施处理；上传材料保留原件。合同阶段待确认时可保存计划，确认后才能提交整改。</p>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="emit('update:modelValue', false)">稍后处理</el-button><el-button type="primary" :loading="saving" :disabled="!!loadError || loading" @click="save">保存整改计划</el-button></template>
  </el-dialog>
</template>

<style scoped>
.plan-form { margin-top: 18px; }.plan-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }.plan-form :deep(.el-select),.plan-form :deep(.el-date-editor) { width: 100%; min-width: 0; }.plan-hint { margin: 0; color: var(--muted); font-size: var(--type-caption); line-height: 1.6; }.el-alert + .el-alert { margin-top: 10px; }
@media (max-width: 600px) { .plan-grid { grid-template-columns: minmax(0, 1fr); gap: 0; } }
</style>
<style>
.rectification-plan-dialog { max-width: calc(100vw - 24px); }
</style>
