<script setup lang="ts">
// 部门风险排行（横向条形）
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'
import { readThemePalette, useTheme } from '@/theme/theme'

const props = defineProps<{ data: ReportData['depts'] }>()
const { effectiveTheme } = useTheme()

const option = computed<EChartsCoreOption>(() => {
  effectiveTheme.value
  const palette = readThemePalette()
  const sorted = [...props.data].sort((a, b) => a.risk - b.risk)
  return {
    textStyle: { color: palette.textSecondary, fontFamily: 'JetBrains Mono, PingFang SC, sans-serif' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: palette.surface,
      borderColor: palette.lineStrong,
      textStyle: { color: palette.text },
    },
    grid: { left: 90, right: 30, top: 10, bottom: 20 },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: palette.line } },
      axisLabel: { color: palette.muted },
    },
    yAxis: {
      type: 'category',
      data: sorted.map((d) => d.name),
      axisLine: { lineStyle: { color: palette.lineStrong } },
      axisLabel: { color: palette.textSecondary },
    },
    series: [
      {
        type: 'bar',
        data: sorted.map((d) => d.risk),
        barWidth: 14,
        itemStyle: { color: palette.brass, borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right', color: palette.muted },
      },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" height="260px" />
</template>
