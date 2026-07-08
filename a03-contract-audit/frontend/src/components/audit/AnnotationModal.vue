<script setup lang="ts">
// 合同全文批注：左侧正文（信笺纹理，风险句红笔波浪线锚点），右侧批注列表。
// 点批注 → 左侧对应锚点平滑滚动到中央并 flash 高亮。
// 正文为演示范本，风险锚点按 store 中真实 risks 顺序挂靠。
import { computed, nextTick, ref } from 'vue'
import type { RiskOut } from '@/api/types'

const props = defineProps<{ modelValue: boolean; risks: RiskOut[]; filename: string }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 演示合同正文条款（{{n}} 为风险锚点占位，对应 risks[n]）
const CLAUSES = [
  { h: '第一条 合同主体', p: '甲方：某科技有限公司；乙方：{{4}}。双方本着平等自愿的原则签订本合同。' },
  { h: '第二条 合同标的与金额', p: '乙方为甲方提供软件开发外包服务，合同金额 {{2}}。' },
  { h: '第三条 履约期限', p: '本合同服务期限自双方签署之日起 12 个月。{{3}}' },
  { h: '第四条 付款方式', p: '甲方按项目里程碑分三期支付合同款项，每期验收合格后 15 个工作日内支付。' },
  { h: '第五条 违约责任', p: '{{0}}' },
  { h: '第六条 争议解决', p: '{{1}}' },
  { h: '第七条 其他', p: '本合同一式两份，甲乙双方各执一份，具有同等法律效力。' },
]

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}

// 把 {{n}} 替换为带锚点的批注句；命中 risk 则包红笔波浪线，否则用建议兜底
function renderClause(text: string): string {
  return text.replace(/\{\{(\d+)\}\}/g, (_, idx) => {
    const i = Number(idx)
    const r = props.risks[i]
    if (!r) return '（相关条款）'
    const sentence = r.original_text?.startsWith('（')
      ? `此处应包含${r.category}相关约定`
      : r.original_text || `${r.category}相关条款`
    return `<mark id="ann-${i}" class="ann-sentence">${sentence}</mark>`
  })
}

const renderedClauses = computed(() => CLAUSES.map((c) => ({ h: c.h, html: renderClause(c.p) })))

const docRef = ref<HTMLElement>()
async function scrollToAnn(i: number) {
  await nextTick()
  const mark = docRef.value?.querySelector(`#ann-${i}`) as HTMLElement | null
  if (!mark) return
  mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
  mark.classList.add('flash')
  setTimeout(() => mark.classList.remove('flash'), 1400)
}
</script>

<template>
  <el-dialog v-model="visible" :title="`合同全文批注 · ${filename}`" width="1000px" top="6vh">
    <div class="fulltext">
      <article ref="docRef" class="doc">
        <section v-for="(c, i) in renderedClauses" :key="i" class="clause">
          <h4>{{ c.h }}</h4>
          <p v-html="c.html" />
        </section>
      </article>

      <aside class="ann-list">
        <div class="ann-head">批注（{{ risks.length }}）</div>
        <div
          v-for="(r, i) in risks"
          :key="r.id"
          class="ann-item"
          :class="`lvl-${r.level}`"
          @click="scrollToAnn(i)"
        >
          <div class="ann-item-head">
            <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}</el-tag>
            <b>{{ r.category }}</b>
          </div>
          <p>{{ r.suggestion }}</p>
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
    rgba(58, 50, 34, 0.07) 32px
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
    background: rgba(176, 116, 26, 0.4);
  }
}
</style>
