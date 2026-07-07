<script setup lang="ts">
// 风险复核抽屉：展示命中原文/依据/建议，底部"标记误报"或"确认并生成整改项"。
// 确认时：PATCH 真接口更新状态 → 生成整改项 → 推通知（由父组件回调串起）。
import { computed } from 'vue'
import type { RiskOut } from '@/api/types'

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
</script>

<template>
  <el-drawer v-model="visible" title="风险复核" size="440px" :with-header="true">
    <template v-if="risk">
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
</style>
