<script setup lang="ts">
// 高风险条款 TOP5（横向条形，朱红渐深）
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'
import { readThemePalette, useTheme } from '@/theme/theme'

const props = defineProps<{ data: ReportData['tops'] }>()
const { effectiveTheme } = useTheme()

const option = computed<EChartsCoreOption>(() => {
  effectiveTheme.value
  const palette = readThemePalette()
  const sorted = [...props.data].sort((a, b) => a.value - b.value)
  return {
    textStyle: { color: palette.textSecondary, fontFamily: 'JetBrains Mono, PingFang SC, sans-serif' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: palette.surface,
      borderColor: palette.lineStrong,
      textStyle: { color: palette.text },
    },
    grid: { left: 130, right: 30, top: 10, bottom: 20 },
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
        data: sorted.map((d) => d.value),
        barWidth: 14,
        itemStyle: { color: palette.seal, borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right', color: palette.muted },
      },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" height="260px" />
</template>
