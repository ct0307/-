<script setup lang="ts">
// 部门风险排行（横向条形）
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'

const props = defineProps<{ data: ReportData['depts'] }>()

const option = computed<EChartsCoreOption>(() => {
  const sorted = [...props.data].sort((a, b) => a.risk - b.risk)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 90, right: 30, top: 10, bottom: 20 },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(58,50,34,0.1)' } },
      axisLabel: { color: '#8c8574' },
    },
    yAxis: {
      type: 'category',
      data: sorted.map((d) => d.name),
      axisLine: { lineStyle: { color: 'rgba(58,50,34,0.26)' } },
      axisLabel: { color: '#565e70' },
    },
    series: [
      {
        type: 'bar',
        data: sorted.map((d) => d.risk),
        barWidth: 14,
        itemStyle: { color: '#8a6a1c', borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right', color: '#8c8574' },
      },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" height="260px" />
</template>
