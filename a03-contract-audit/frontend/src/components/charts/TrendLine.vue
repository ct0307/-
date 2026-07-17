<script setup lang="ts">
// 合同审查趋势折线图（3 系列：审查总数 / 通过数 / 高风险数）
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'

const props = defineProps<{ data: ReportData['trend'] }>()

const option = computed<EChartsCoreOption>(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['审查总数', '通过数', '高风险数'], top: 0, textStyle: { color: '#565e70' } },
  grid: { left: 40, right: 20, top: 40, bottom: 30 },
  xAxis: {
    type: 'category',
    data: props.data.labels,
    axisLine: { lineStyle: { color: 'rgba(58,50,34,0.26)' } },
    axisLabel: { color: '#8c8574' },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(58,50,34,0.1)' } },
    axisLabel: { color: '#8c8574' },
  },
  series: [
    {
      name: '审查总数',
      type: 'line',
      smooth: true,
      data: props.data.total,
      areaStyle: { opacity: 0.12 },
      lineStyle: { width: 2.5 },
    },
    { name: '通过数', type: 'line', smooth: true, data: props.data.pass, lineStyle: { width: 2 } },
    { name: '高风险数', type: 'line', smooth: true, data: props.data.risk, lineStyle: { width: 2 } },
  ],
}))
</script>

<template>
  <BaseChart :option="option" height="260px" />
</template>
