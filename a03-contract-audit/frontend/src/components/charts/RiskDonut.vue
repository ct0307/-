<script setup lang="ts">
// 风险等级分布环形图（高/中/低风险条款），中心显风险条款总数。
// 量纲统一为「条款数」——通过率是合同级口径，已退回 KPI 卡，不再混入此图。
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'

const props = defineProps<{ data: ReportData['donut'] }>()

// 按语义固定颜色：高=朱 中=琥珀 低=绿
const COLOR: Record<string, string> = {
  高风险: '#b23a2c',
  中风险: '#b0741a',
  低风险: '#3e7a5c',
}

const totalClauses = computed(() => props.data.reduce((s, d) => s + d.value, 0))

const option = computed<EChartsCoreOption>(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, textStyle: { color: '#565e70' } },
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
          a: { fontSize: 26, fontWeight: 700, color: '#2a3248', fontFamily: 'JetBrains Mono' },
          b: { fontSize: 12, color: '#8c8574', padding: [6, 0, 0, 0] },
        },
      },
      labelLine: { show: false },
      data: props.data.map((d) => ({
        name: d.name,
        value: d.value,
        itemStyle: { color: COLOR[d.name] || '#8a6a1c' },
      })),
    },
  ],
}))
</script>

<template>
  <BaseChart :option="option" height="260px" />
</template>
