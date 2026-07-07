<script setup lang="ts">
// 风险等级分布环形图（高/中/低/无风险），中心显合规通过率。
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import BaseChart from './BaseChart.vue'
import type { ReportData } from '@/mock/reports'

const props = defineProps<{ data: ReportData['donut']; pass: number }>()

// 按语义固定颜色：高=朱 中=琥珀 低=绿 无=灰
const COLOR: Record<string, string> = {
  高风险: '#b23a2c',
  中风险: '#b0741a',
  低风险: '#3e7a5c',
  无风险: '#c9c1ad',
}

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
        formatter: `{a|${props.pass}%}\n{b|合规通过率}`,
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
  <BaseChart :option="option" height="300px" />
</template>
