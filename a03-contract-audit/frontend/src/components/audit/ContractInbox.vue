<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Delete, DocumentChecked, RefreshRight, UploadFilled } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'

import type { ImportItem } from '@/api/imports'
import { importErrorMeta } from '@/utils/import-errors'

const props = defineProps<{
  items: ImportItem[]
  contractTypes: string[]
  departments: string[]
  selectedIds: number[]
  canChangeDepartment: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  upload: [files: File[]]
  confirm: [itemId: number, contractType: string, department: string]
  retry: [itemId: number]
  removeRecord: [itemId: number]
  deleteDraft: [itemId: number]
  toggleSelected: [itemId: number]
  auditReady: []
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const draftTypes = ref<Record<number, string>>({})
const draftDepartments = ref<Record<number, string>>({})

watch(
  () => props.items,
  (items) => {
    for (const item of items) {
      draftTypes.value[item.id] = item.confirmed_type || item.suggested_type
      draftDepartments.value[item.id] = item.department || props.departments[0] || ''
    }
  },
  { immediate: true, deep: true },
)

const counts = computed(() => ({
  total: props.items.length,
  ready: props.items.filter((item) => item.status === 'ready').length,
  attention: props.items.filter((item) => item.status === 'awaiting_confirmation').length,
  failed: props.items.filter((item) => item.status === 'failed').length,
}))

const statusMeta: Record<ImportItem['status'], {
  label: string
  type: 'success' | 'warning' | 'danger' | 'info'
}> = {
  queued: { label: '等待解析', type: 'info' },
  parsing: { label: '解析中', type: 'info' },
  awaiting_confirmation: { label: '待确认', type: 'warning' },
  ready: { label: '可以审查', type: 'success' },
  failed: { label: '处理失败', type: 'danger' },
  auditing: { label: '审查中', type: 'info' },
  done: { label: '已审查', type: 'success' },
  deleted: { label: '已删除', type: 'info' },
}

function chooseFiles() {
  if (props.loading) return
  fileInput.value?.click()
}

function submitFiles(files: FileList | File[]) {
  if (props.loading) return
  const selected = Array.from(files)
  if (selected.length) emit('upload', selected)
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files) submitFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragging.value = false
  if (props.loading) return
  if (event.dataTransfer?.files) submitFiles(event.dataTransfer.files)
}

function isLocked(item: ImportItem) {
  return ['queued', 'parsing', 'auditing', 'done'].includes(item.status)
}

function shouldConfirm(item: ImportItem) {
  return item.status === 'awaiting_confirmation'
    || (item.status === 'ready' && (
      draftTypes.value[item.id] !== item.confirmed_type
      || draftDepartments.value[item.id] !== item.department
    ))
}

function confirm(item: ImportItem) {
  const contractType = draftTypes.value[item.id]?.trim()
  const department = draftDepartments.value[item.id]?.trim()
  if (contractType && department) emit('confirm', item.id, contractType, department)
}

function failureMeta(item: ImportItem) {
  return importErrorMeta(item)
}

function canRetry(item: ImportItem) {
  return item.status === 'failed' && Boolean(item.contract_id) && failureMeta(item).retryable
}

function confidencePercent(confidence: number) {
  return Math.round(Math.min(1, Math.max(0, confidence)) * 100)
}

async function deleteDraft(item: ImportItem) {
  try {
    await ElMessageBox.confirm(
      '合同草稿进入回收站 30 天，尚未产生审查结果。确认删除？',
      '删除合同草稿',
      {
        type: 'warning',
        confirmButtonText: '删除草稿',
        cancelButtonText: '取消',
      },
    )
    emit('deleteDraft', item.id)
  } catch {
    // 用户取消时保持当前队列。
  }
}
</script>

<template>
  <section class="contract-inbox" aria-labelledby="contract-inbox-title">
    <header class="inbox-head">
      <div>
        <span class="eyebrow mono">CONTRACT INBOX</span>
        <h2 id="contract-inbox-title">待审合同</h2>
      </div>
      <p>合同类型按文件识别，可在进入审查前逐份修正。</p>
    </header>

    <div
      class="upload-band"
      :class="{ dragging, disabled: loading }"
      role="button"
      :tabindex="loading ? -1 : 0"
      :aria-disabled="loading"
      aria-label="选择或拖拽合同文件"
      @click="chooseFiles"
      @keydown.enter.prevent="chooseFiles"
      @keydown.space.prevent="chooseFiles"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInput"
        class="file-input"
        type="file"
        accept=".pdf,.docx,.txt"
        multiple
        :disabled="loading"
        @change="onFileChange"
      >
      <el-icon><UploadFilled /></el-icon>
      <span class="upload-primary">添加合同</span>
      <span class="upload-secondary">拖拽或选择 PDF、Word、TXT，单次最多 200 份</span>
    </div>

    <div class="summary-strip" aria-label="导入状态摘要">
      <div><span>全部</span><strong class="mono">{{ counts.total }}</strong></div>
      <div class="ready"><span>可以审查</span><strong class="mono">{{ counts.ready }}</strong></div>
      <div class="attention"><span>待确认</span><strong class="mono">{{ counts.attention }}</strong></div>
      <div class="failed"><span>失败</span><strong class="mono">{{ counts.failed }}</strong></div>
    </div>

    <div v-if="items.length" class="inbox-table" role="table" aria-label="待审合同队列">
      <div class="table-row table-header" role="row">
        <span role="columnheader">选择</span>
        <span role="columnheader">文件</span>
        <span role="columnheader">状态</span>
        <span role="columnheader">合同类型</span>
        <span role="columnheader">归属部门</span>
        <span role="columnheader">操作</span>
      </div>
      <div
        v-for="item in items"
        :key="item.id"
        class="table-row"
        :class="`status-${item.status}`"
        role="row"
      >
        <div class="select-cell" role="cell" data-label="选择">
          <input
            class="row-checkbox"
            type="checkbox"
            :checked="selectedIds.includes(item.id)"
            :disabled="item.status !== 'ready'"
            :aria-label="`选择${item.filename}`"
            @change="emit('toggleSelected', item.id)"
          >
        </div>
        <div class="file-cell" role="cell" data-label="文件">
          <el-icon><DocumentChecked /></el-icon>
          <div>
            <strong :title="item.filename">{{ item.filename }}</strong>
            <template v-if="item.status === 'failed'">
              <small role="alert">{{ failureMeta(item).message }}</small>
              <small class="error-action">建议：{{ failureMeta(item).action }}</small>
            </template>
            <small v-else-if="item.ocr_confidence != null" class="confidence mono">
              OCR 置信度 {{ confidencePercent(item.ocr_confidence) }}%
            </small>
            <small v-else-if="item.confidence !== null" class="confidence mono">
              类型置信度 {{ confidencePercent(item.confidence) }}%
            </small>
          </div>
        </div>
        <div role="cell" data-label="状态">
          <div class="status-tags">
            <el-tag :type="statusMeta[item.status].type" size="small">
              {{ statusMeta[item.status].label }}
            </el-tag>
            <el-tag v-if="item.requires_review" type="warning" effect="plain" size="small">
              需人工复核
            </el-tag>
          </div>
        </div>
        <div role="cell" data-label="合同类型">
          <el-select
            v-model="draftTypes[item.id]"
            :aria-label="`${item.filename} 的合同类型`"
            :disabled="isLocked(item) || !item.contract_id"
            filterable
            size="small"
            placeholder="请选择类型"
          >
            <el-option v-for="type in contractTypes" :key="type" :label="type" :value="type" />
          </el-select>
        </div>
        <div role="cell" data-label="归属部门">
          <el-select
            v-if="canChangeDepartment && item.contract_id"
            v-model="draftDepartments[item.id]"
            :aria-label="`${item.filename} 的归属部门`"
            :disabled="isLocked(item)"
            filterable
            size="small"
          >
            <el-option v-for="department in departments" :key="department" :label="department" :value="department" />
          </el-select>
          <span v-else class="department-text">{{ item.department || '未落库' }}</span>
        </div>
        <div class="actions" role="cell" data-label="操作">
          <el-button
            v-if="shouldConfirm(item)"
            size="small"
            type="primary"
            plain
            :disabled="!draftTypes[item.id] || !draftDepartments[item.id]"
            :aria-label="`确认 ${item.filename}`"
            @click="confirm(item)"
          >确认</el-button>
          <el-tooltip v-if="canRetry(item)" content="使用已保存的草稿重新解析">
            <el-button
              circle
              size="small"
              :icon="RefreshRight"
              :aria-label="`重新解析 ${item.filename}`"
              @click="emit('retry', item.id)"
            />
          </el-tooltip>
          <el-tooltip v-if="item.status === 'failed' && !item.contract_id" content="从当前收件箱移出失败记录">
            <el-button
              circle
              size="small"
              :icon="Delete"
              :aria-label="`移出 ${item.filename}`"
              @click="emit('removeRecord', item.id)"
            />
          </el-tooltip>
          <el-tooltip
            v-if="item.contract_id && ['awaiting_confirmation', 'ready', 'failed'].includes(item.status)"
            content="删除合同草稿"
          >
            <el-button
              circle
              size="small"
              type="danger"
              plain
              :icon="Delete"
              :aria-label="`删除合同草稿 ${item.filename}`"
              @click="deleteDraft(item)"
            />
          </el-tooltip>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <el-icon><DocumentChecked /></el-icon>
      <strong>收件箱为空</strong>
      <span>添加一份或多份合同后，系统会逐份识别并列出。</span>
    </div>

    <footer class="action-bar">
      <span>已选 <strong class="mono">{{ selectedIds.length }}</strong> 份就绪合同</span>
      <el-button
        type="primary"
        :loading="loading"
        :disabled="selectedIds.length === 0"
        aria-label="审查就绪项"
        @click="emit('auditReady')"
      >审查就绪项</el-button>
    </footer>
  </section>
</template>

<style scoped>
.contract-inbox {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--ink-2);
}
.inbox-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--line);
}
.inbox-head h2 { margin: 2px 0 0; font-size: 19px; }
.inbox-head p { margin: 0; color: var(--muted); font-size: 12px; }
.eyebrow { color: var(--brass); font-size: 10px; }
.upload-band {
  display: flex;
  min-height: 58px;
  align-items: center;
  gap: 10px;
  margin: 14px 20px;
  padding: 10px 14px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--bg-soft);
  cursor: pointer;
  transition: border-color .18s var(--ease), background .18s var(--ease);
}
.upload-band:hover,
.upload-band.dragging { border-color: var(--brass); background: var(--brass-soft); }
.upload-band.disabled { cursor: not-allowed; opacity: .65; }
.upload-band.disabled:hover { border-color: var(--line-strong); background: var(--bg-soft); }
.upload-band > .el-icon { flex: none; color: var(--brass); font-size: 22px; }
.file-input { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.upload-primary { flex: none; color: var(--ivory); font-weight: 600; font-size: 13px; }
.upload-secondary { min-width: 0; color: var(--muted); font-size: 12px; }
.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.summary-strip > div { display: flex; align-items: baseline; gap: 8px; padding: 10px 20px; border-right: 1px solid var(--line); }
.summary-strip > div:last-child { border-right: 0; }
.summary-strip span { color: var(--muted); font-size: 11px; }
.summary-strip strong { color: var(--ivory); font-size: 18px; }
.summary-strip .ready strong { color: var(--sage); }
.summary-strip .attention strong { color: var(--amber); }
.summary-strip .failed strong { color: var(--seal); }
.inbox-table { width: 100%; }
.table-row {
  display: grid;
  grid-template-columns: 48px minmax(190px, 1.5fr) 106px minmax(180px, 1fr) minmax(140px, .8fr) 132px;
  min-width: 0;
  align-items: center;
  border-bottom: 1px solid var(--line);
}
.table-row > * { min-width: 0; padding: 10px 12px; }
.table-header { min-height: 36px; background: var(--ink-3); color: var(--muted); font-size: 11px; }
.status-failed { background: var(--seal-panel-soft); }
.status-awaiting_confirmation { background: var(--amber-soft); }
.select-cell { display: flex; justify-content: center; }
.row-checkbox {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: var(--brass);
  cursor: pointer;
}
.row-checkbox:disabled { cursor: not-allowed; opacity: .45; }
.file-cell { display: flex; align-items: flex-start; gap: 9px; }
.file-cell > .el-icon { flex: none; margin-top: 2px; color: var(--info); }
.file-cell strong { display: block; overflow: hidden; color: var(--ivory); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.file-cell small { display: block; margin-top: 4px; color: var(--seal); font-size: 11px; line-height: 1.35; overflow-wrap: anywhere; }
.file-cell .error-action { color: var(--amber); }
.file-cell .confidence { color: var(--muted); }
.status-tags { display: flex; min-width: 0; flex-wrap: wrap; gap: 5px; }
.department-text { color: var(--ivory-dim); font-size: 12px; }
.actions { display: flex; align-items: center; justify-content: flex-end; gap: 5px; }
.actions :deep(.el-button + .el-button) { margin-left: 0; }
.empty-state { display: flex; min-height: 150px; flex-direction: column; align-items: center; justify-content: center; gap: 7px; color: var(--muted); }
.empty-state > .el-icon { color: var(--brass); font-size: 28px; }
.empty-state strong { color: var(--ivory-dim); font-size: 13px; }
.empty-state span { font-size: 12px; }
.action-bar { display: flex; min-height: 58px; align-items: center; justify-content: flex-end; gap: 18px; padding: 10px 20px; background: var(--ink-3); }
.action-bar span { color: var(--muted); font-size: 12px; }
.action-bar strong { color: var(--ivory); }

@media (max-width: 900px) {
  .table-header { display: none; }
  .table-row { grid-template-columns: 38px minmax(0, 1fr); padding: 12px; }
  .table-row > * { padding: 6px 8px; }
  .table-row > :not(.select-cell):not(.file-cell) { grid-column: 2; }
  .select-cell { grid-row: 1 / span 5; grid-column: 1; align-self: start; padding-top: 9px; }
  .file-cell { grid-column: 2; }
  .table-row > [data-label]::before { content: attr(data-label); display: inline-block; width: 72px; color: var(--muted); font-size: 10px; vertical-align: middle; }
  .file-cell::before,
  .select-cell::before { display: none !important; }
  .table-row > [data-label="合同类型"],
  .table-row > [data-label="归属部门"] { display: grid; grid-template-columns: 72px minmax(0, 1fr); align-items: center; }
  .actions { justify-content: flex-start; }
}

@media (max-width: 640px) {
  .inbox-head { align-items: flex-start; flex-direction: column; gap: 5px; padding: 15px 14px 12px; }
  .upload-band { align-items: flex-start; flex-wrap: wrap; margin: 12px 14px; }
  .upload-secondary { flex-basis: 100%; padding-left: 32px; line-height: 1.4; }
  .summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-strip > div { padding: 9px 14px; }
  .summary-strip > div:nth-child(2) { border-right: 0; }
  .summary-strip > div:nth-child(-n + 2) { border-bottom: 1px solid var(--line); }
  .table-row { padding: 10px 6px; }
  .action-bar { position: sticky; bottom: 0; z-index: 2; justify-content: space-between; padding: 10px 14px; }
}
</style>
