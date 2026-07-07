<script setup lang="ts">
// 数据来源标识。传入 module 时按 MOCK_ENABLED 自动判定：
//   - 该模块已切真接口 → 绿色「实时数据 · 已接入后端」
//   - 仍走 mock → 琥珀色「演示数据 · 待后端接入」
// 不传 module 时保持原演示态（兼容旧用法）。
import { computed } from 'vue'
import { MOCK_ENABLED } from '@/mock'

const props = defineProps<{
  module?: keyof typeof MOCK_ENABLED
}>()

// 未指定模块视为演示态；指定则读开关
const isLive = computed(() => (props.module ? !MOCK_ENABLED[props.module] : false))
</script>

<template>
  <span class="demo-badge" :class="{ live: isLive }">
    <el-icon :size="13">
      <component :is="isLive ? 'SuccessFilled' : 'InfoFilled'" />
    </el-icon>
    {{ isLive ? '实时数据 · 已接入后端' : '演示数据 · 待后端接入' }}
  </span>
</template>

<style scoped>
.demo-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-soft);
  font-family: var(--mono);
}
.demo-badge.live {
  color: var(--sage);
  background: var(--sage-soft);
}
</style>
