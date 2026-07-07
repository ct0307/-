<script setup lang="ts">
// 审查历史记录：el-table + 分页 + 搜索 + 风险等级筛选。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getHistory } from '@/api/history'
import type { HistoryRow } from '@/mock/history'
import DemoBadge from '@/components/common/DemoBadge.vue'

const rows = ref<HistoryRow[]>([])
const loading = ref(false)
const keyword = ref('')
const levelFilter = ref('全部')
const page = ref(1)
const pageSize = 8

async function load() {
  loading.value = true
  try {
    rows.value = await getHistory()
  } catch {
    ElMessage.error('历史记录加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return rows.value.filter((r) => {
    const kwOk = !kw || r.name.includes(kw) || r.id.includes(kw)
    const lvOk = levelFilter.value === '全部' || r.level === levelFilter.value
    return kwOk && lvOk
  })
})
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

const levelType: Record<string, 'danger' | 'warning' | 'info'> = {
  高风险: 'danger',
  中风险: 'warning',
  低风险: 'info',
}
const statusType: Record<string, 'success' | 'warning' | 'info'> = {
  合规: 'success',
  待整改: 'warning',
  已整改: 'info',
}
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <div class="filters">
        <el-input v-model="keyword" placeholder="搜索合同名称 / 编号" :prefix-icon="'Search'" style="width: 240px" clearable @input="page = 1" />
        <el-select v-model="levelFilter" style="width: 140px" @change="page = 1">
          <el-option label="全部风险等级" value="全部" />
          <el-option label="高风险" value="高风险" />
          <el-option label="中风险" value="中风险" />
          <el-option label="低风险" value="低风险" />
        </el-select>
      </div>
      <DemoBadge />
    </div>

    <el-card shadow="never">
      <el-table :data="paged" style="width: 100%" empty-text="无匹配记录">
        <el-table-column prop="id" label="编号" width="120">
          <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column prop="name" label="合同名称" min-width="200" />
        <el-table-column prop="type" label="类型" width="150" />
        <el-table-column prop="submitter" label="提交人" width="90" />
        <el-table-column prop="time" label="审查时间" width="150">
          <template #default="{ row }"><span class="mono">{{ row.time }}</span></template>
        </el-table-column>
        <el-table-column label="风险等级" width="100">
          <template #default="{ row }"><el-tag :type="levelType[row.level]" size="small">{{ row.level }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="riskCount" label="风险条款" width="90" align="center">
          <template #default="{ row }"><span class="mono">{{ row.riskCount }}</span></template>
        </el-table-column>
        <el-table-column label="合规状态" width="100">
          <template #default="{ row }"><el-tag :type="statusType[row.status]" size="small" effect="plain">{{ row.status }}</el-tag></template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <span class="count mono">共 {{ filtered.length }} 条记录</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="filtered.length"
          layout="prev, pager, next"
          background
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.filters {
  display: flex;
  gap: 12px;
}
.table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}
.count {
  font-size: 12px;
  color: var(--muted);
}
</style>
