<script setup lang="ts">
// 合同全文批注：左侧风险原文列表（真实 original_text），右侧批注。
// 点击右侧批注项 → 左侧对应原文平滑滚动到中央并 flash 高亮。
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { RiskOut } from '@/api/types'
import { useAuditSessionStore } from '@/stores/audit-session'

const props = defineProps<{ modelValue: boolean; risks: RiskOut[]; filename: string }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean] }>()

const session = useAuditSessionStore()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 已应用为合同建议的 risk id 集合（当次打开内有效）
const appliedIds = ref(new Set<number>())
const applyingId = ref<number | null>(null)

async function applyAsSuggestion(risk: RiskOut) {
  if (appliedIds.value.has(risk.id) || applyingId.value === risk.id) return
  applyingId.value = risk.id
  try {
    await session.setRiskStatus(risk, 'to_modify')
    appliedIds.value.add(risk.id)
    ElMessage.success('已应用为合同修改建议，可在整改跟踪中查看')
  } catch {
    ElMessage.error('操作失败')
  } finally {
    applyingId.value = null
  }
}

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}

const docRef = ref<HTMLElement>()
async function scrollToRisk(id: number) {
  await nextTick()
  const el = docRef.value?.querySelector(`#risk-${id}`) as HTMLElement | null
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('flash')
  setTimeout(() => el.classList.remove('flash'), 1400)
}
</script>

<template>
  <el-dialog v-model="visible" :title="`合同全文批注 · ${filename}`" width="1000px" top="6vh">
    <div class="fulltext">
      <article ref="docRef" class="doc">
        <div class="doc-hint">以下为 AI 提取的风险原文，点击右侧批注项可定位</div>
        <section
          v-for="r in risks"
          :id="`risk-${r.id}`"
          :key="r.id"
          class="clause"
          :class="`lvl-${r.level}`"
        >
          <div class="clause-head">
            <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}风险</el-tag>
            <b>{{ r.category }}</b>
          </div>
          <mark class="ann-sentence">{{ r.original_text || `（${r.category}相关条款未提取到原文）` }}</mark>
        </section>
        <div v-if="!risks.length" class="doc-empty">暂无风险原文，完成合同审查后批注自动生成</div>
      </article>

      <aside class="ann-list">
        <div class="ann-head">批注（{{ risks.length }}）</div>
        <div
          v-for="(r, i) in risks"
          :key="r.id"
          class="ann-item"
          :class="`lvl-${r.level}`"
          @click="scrollToRisk(r.id)"
        >
          <div class="ann-item-head">
            <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}</el-tag>
            <b>{{ r.category }}</b>
          </div>
          <p>{{ r.suggestion }}</p>
          <el-button
            size="small"
            :type="appliedIds.has(r.id) ? 'success' : 'primary'"
            :loading="applyingId === r.id"
            :disabled="appliedIds.has(r.id)"
            plain
            class="apply-btn"
            @click.stop="applyAsSuggestion(r)"
          >
            {{ appliedIds.has(r.id) ? '已应用 ✓' : '应用为合同建议' }}
          </el-button>
        </div>
      </aside>
    </div>
  </el-dialog>
</template>

<style scoped>
.fulltext {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 16px;
  height: 66vh;
}
.doc {
  overflow-y: auto;
  padding: 24px 28px;
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background-image: repeating-linear-gradient(
    to bottom,
    transparent,
    transparent 31px,
    var(--paper-line) 32px
  );
  line-height: 2;
}
.clause {
  margin-bottom: 18px;
}
.clause h4 {
  margin: 0 0 4px;
  font-family: var(--serif);
  color: var(--ivory);
  font-size: 15px;
}
.clause p {
  margin: 0;
  color: var(--ivory-dim);
  font-family: var(--serif);
}
.ann-list {
  overflow-y: auto;
  padding-right: 4px;
}
.ann-head {
  font-family: var(--serif);
  font-weight: 600;
  color: var(--ivory);
  margin-bottom: 10px;
}
.ann-item {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 10px 12px;
  margin-bottom: 10px;
  cursor: pointer;
  position: relative;
  transition: border-color 0.2s var(--ease), background-color 0.2s var(--ease);
}
.ann-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: var(--r-sm) 0 0 var(--r-sm);
}
.ann-item.lvl-high::before {
  background: var(--seal);
}
.ann-item.lvl-medium::before {
  background: var(--amber);
}
.ann-item.lvl-low::before {
  background: var(--sage);
}
.ann-item:hover {
  border-color: var(--brass);
}
.ann-item-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.ann-item-head b {
  color: var(--ivory);
  font-size: 13px;
}
.ann-item p {
  margin: 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.5;
}
.apply-btn {
  margin-top: 8px;
  width: 100%;
}
:deep(.ann-sentence) {
  text-decoration: underline wavy var(--seal);
  text-underline-offset: 3px;
  background: var(--seal-soft);
  color: var(--ivory);
  padding: 0 2px;
  border-radius: 2px;
  transition: background 0.3s var(--ease);
}
:deep(.ann-sentence.flash) {
  background: var(--amber-soft);
  animation: flash 1.4s var(--ease);
}
@keyframes flash {
  0%,
  100% {
    background: var(--seal-soft);
  }
  30% {
    background: var(--annotation-highlight);
  }
}
.doc-hint {
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 12px;
  font-family: var(--serif);
}
.doc-empty {
  font-size: 13px;
  color: var(--muted);
  text-align: center;
  padding: 40px 0;
}
.clause-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.clause-head b {
  font-size: 13px;
  color: var(--ivory);
}
.clause.lvl-high { border-left-color: var(--seal); }
.clause.lvl-medium { border-left-color: var(--amber); }
.clause.lvl-low { border-left-color: var(--sage); }
</style>
