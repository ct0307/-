<script setup lang="ts">
// ECharts 基础封装：按需引入减包 + ResizeObserver 自适应 + 卷宗主题。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

// 注册卷宗主题（色板对齐设计令牌）
echarts.registerTheme('juanzong', {
  color: ['#8a6a1c', '#b23a2c', '#b0741a', '#3e7a5c', '#b8912f'],
  textStyle: { fontFamily: 'JetBrains Mono, PingFang SC, sans-serif' },
  backgroundColor: 'transparent',
})

const props = defineProps<{ option: EChartsCoreOption; height?: string }>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

function render() {
  if (!chart) return
  chart.setOption(props.option, true)
}

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value, 'juanzong')
  render()
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="chart" :style="{ height: height || '300px' }" />
</template>

<style scoped>
.chart {
  width: 100%;
}
</style>
