<script setup lang="ts">
// ECharts 基础封装：按需引入减包 + ResizeObserver 自适应 + 主题重绘。
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { useTheme } from '@/theme/theme'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = defineProps<{ option: EChartsCoreOption; height?: string }>()
const { effectiveTheme } = useTheme()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null

function render() {
  if (!chart) return
  chart.setOption(props.option, true)
}

function initChart() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value)
  render()
}

onMounted(() => {
  if (!el.value) return
  initChart()
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value)
})

watch(() => props.option, render, { deep: true })
watch(effectiveTheme, async () => {
  await nextTick()
  initChart()
}, { flush: 'post' })

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
