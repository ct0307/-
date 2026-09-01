<script setup lang="ts">
// 风险等级分布环形图（高/中/低风险条款），中心显风险条款总数。
// 量纲统一为「条款数」——通过率是合同级口径，已退回 KPI 卡，不再混入此图。
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'
import { readThemePalette, useTheme } from '@/theme/theme'

const props = defineProps<{ data: ReportData['donut'] }>()
const { effectiveTheme } = useTheme()

const totalClauses = computed(() => props.data.reduce((s, d) => s + d.value, 0))

const option = computed<EChartsCoreOption>(() => {
  effectiveTheme.value
  const palette = readThemePalette()
  const riskColor: Record<string, string> = {
    高风险: palette.seal,
    中风险: palette.amber,
    低风险: palette.sage,
  }
  return {
    textStyle: { color: palette.textSecondary, fontFamily: 'JetBrains Mono, PingFang SC, sans-serif' },
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)',
      backgroundColor: palette.surface,
      borderColor: palette.lineStrong,
      textStyle: { color: palette.text },
    },
    legend: { bottom: 0, textStyle: { color: palette.textSecondary } },
    series: [
      {
        type: 'pie',
        radius: ['55%', '75%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: false,
        label: {
          show: true,
          position: 'center',
          formatter: `{a|${totalClauses.value}}\n{b|风险条款总数}`,
          rich: {
            a: { fontSize: 26, fontWeight: 700, color: palette.text, fontFamily: 'JetBrains Mono' },
            b: { fontSize: 12, color: palette.muted, padding: [6, 0, 0, 0] },
          },
        },
        labelLine: { show: false },
        data: props.data.map((d) => ({
          name: d.name,
          value: d.value,
          itemStyle: { color: riskColor[d.name] || palette.brass },
        })),
      },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" height="260px" />
</template>
