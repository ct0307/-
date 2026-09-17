<script setup lang="ts">
// 合同审查趋势折线图（3 系列：审查总数 / 通过数 / 高风险数）
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'
import { readThemePalette, useTheme } from '@/theme/theme'

const props = withDefaults(defineProps<{ data: ReportData['trend']; labels?: [string, string, string] }>(), { labels: () => ['审查总数', '通过数', '高风险数'] })
const { effectiveTheme } = useTheme()

const option = computed<EChartsCoreOption>(() => {
  effectiveTheme.value
  const palette = readThemePalette()
  return {
    color: [palette.brass, palette.sage, palette.seal],
    textStyle: { color: palette.textSecondary, fontFamily: 'JetBrains Mono, PingFang SC, sans-serif' },
    tooltip: {
      trigger: 'axis',
      backgroundColor: palette.surface,
      borderColor: palette.lineStrong,
      textStyle: { color: palette.text },
    },
    legend: { data: props.labels, top: 0, textStyle: { color: palette.textSecondary } },
    grid: { left: 40, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category',
      data: props.data.labels,
      axisLine: { lineStyle: { color: palette.lineStrong } },
      axisLabel: { color: palette.muted },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: palette.line } },
      axisLabel: { color: palette.muted },
    },
    series: [
      {
        name: props.labels[0],
        type: 'line',
        smooth: true,
        data: props.data.total,
        areaStyle: { opacity: 0.12 },
        lineStyle: { width: 2.5 },
      },
      { name: props.labels[1], type: 'line', smooth: true, data: props.data.pass, lineStyle: { width: 2 } },
      { name: props.labels[2], type: 'line', smooth: true, data: props.data.risk, lineStyle: { width: 2 } },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" height="260px" />
</template>
