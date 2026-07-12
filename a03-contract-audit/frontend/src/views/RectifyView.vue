<script setup lang="ts">
// 整改跟踪：源自 rectify store（含 AuditView 复核确认生成的真实整改项）。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRectifyStore, type RectifyStatus } from '@/stores/rectify'
import DemoBadge from '@/components/common/DemoBadge.vue'

const rectify = useRectifyStore()
const filter = ref<'全部' | RectifyStatus>('全部')
const keyword = ref('')
const page = ref(1)
const pageSize = 10
const changing = ref<Set<string>>(new Set()) // 正在流转的整改项 ID 集合

onMounted(() => rectify.load())

// R1：支持合同名/风险描述/责任人关键词搜索
const filtered = computed(() => {
  const kw = keyword.value.trim()
  let list = filter.value === '全部' ? rectify.items : rectify.items.filter((r) => r.status === filter.value)
  if (kw) list = list.filter((r) =>
    r.contract.includes(kw) || r.risk.includes(kw) || r.owner.includes(kw),
  )
  return list
})
// R2：分页
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}
const statusType: Record<RectifyStatus, 'info' | 'warning' | 'success'> = {
  待处理: 'info',
  处理中: 'warning',
  已闭环: 'success',
}
const segs: ('全部' | RectifyStatus)[] = ['全部', '待处理', '处理中', '已闭环']

// 状态流转：待处理 → 处理中 → 已闭环 → 待处理（循环）
const nextStatusMap: Record<RectifyStatus, { next: RectifyStatus; label: string; btnType: 'primary' | 'success' | '' }> = {
  待处理: { next: '处理中', label: '开始处理', btnType: 'primary' },
  处理中: { next: '已闭环', label: '标记闭环', btnType: 'success' },
  已闭环: { next: '待处理', label: '重新开启', btnType: '' },
}

async function advance(id: string, current: RectifyStatus) {
  if (changing.value.has(id)) return
  // R3：重新开启需二次确认（会清除闭环状态）
  if (current === '已闭环') {
    try {
      await ElMessageBox.confirm(
        '确认重新开启此整改项？该项将回退至"待处理"状态。',
        '确认重新开启',
        { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
      )
    } catch {
      return // 用户取消
    }
  }
  const { next } = nextStatusMap[current]
  changing.value = new Set([...changing.value, id])
  try {
    await rectify.setStatus(id, next)
  } catch {
    ElMessage.error('状态更新失败，请重试')
  } finally {
    const s = new Set(changing.value)
    s.delete(id)
    changing.value = s
  }
}
</script>

<template>
  <div>
    <div class="toolbar">
      <div class="left-bar">
        <div class="seg">
          <button
            v-for="s in segs"
            :key="s"
            :class="{ active: filter === s }"
            @click="filter = s; page = 1"
          >
            {{ s }}
          </button>
        </div>
        <!-- R1：关键词搜索 -->
        <el-input
          v-model="keyword"
          placeholder="搜索合同名 / 风险 / 责任人"
          :prefix-icon="'Search'"
          style="width: 240px"
          clearable
          @input="page = 1"
        />
      </div>
      <DemoBadge module="rectify" />
    </div>

    <el-alert
      v-if="rectify.error"
      :title="rectify.error"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    >
      <el-button size="small" @click="rectify.load(true)">重试</el-button>
    </el-alert>

    <section class="rk-row">
      <article class="rk-card rk-pending"><span>待处理</span><strong class="mono">{{ rectify.countByStatus.待处理 }}</strong></article>
      <article class="rk-card rk-processing"><span>处理中</span><strong class="mono">{{ rectify.countByStatus.处理中 }}</strong></article>
      <article class="rk-card rk-done"><span>已闭环</span><strong class="mono">{{ rectify.countByStatus.已闭环 }}</strong></article>
      <article class="rk-card rk-total"><span>整改项合计</span><strong class="mono">{{ rectify.total }}</strong></article>
    </section>

    <el-card v-loading="rectify.loading" shadow="never">
      <template #header>
        <div class="panel-head">
          <span>整改项列表</span>
          <span class="count mono">共 {{ filtered.length }} 项</span>
        </div>
      </template>
      <el-empty v-if="!rectify.loading && !filtered.length" description="暂无整改项" />
      <!-- R2：显示 paged 而非 filtered -->
      <article v-for="r in paged" :key="r.id" class="rect-item" :class="`lvl-${r.level}`">
        <div class="rect-main">
          <div class="rect-head">
            <span class="rect-id mono">{{ r.id }}</span>
            <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}风险</el-tag>
            <el-tag :type="statusType[r.status]" size="small" effect="plain">{{ r.status }}</el-tag>
          </div>
          <b class="rect-contract">{{ r.contract }}</b>
          <p class="rect-risk">风险：{{ r.risk }}</p>
          <p v-if="r.note" class="rect-note">{{ r.note }}</p>
        </div>
        <div class="rect-right">
          <div class="rect-meta mono">
            <span>责任人 {{ r.owner }}</span>
            <span>创建 {{ r.created }}</span>
            <span :class="{ overdue: r.status !== '已闭环' && r.due && r.due < new Date().toISOString().slice(0, 10) }">截止 {{ r.due }}</span>
          </div>
          <el-button
            size="small"
            :type="nextStatusMap[r.status].btnType || undefined"
            :loading="changing.has(r.id)"
            :plain="r.status === '已闭环'"
            class="advance-btn"
            @click="advance(r.id, r.status)"
          >
            {{ nextStatusMap[r.status].label }}
          </el-button>
        </div>
      </article>
      <!-- R2：分页 -->
      <div v-if="filtered.length > pageSize" class="pagination-bar">
        <span class="count mono">{{ filtered.length }} 项</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="filtered.length"
          layout="prev, pager, next, total"
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
  gap: 12px;
}
.left-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.seg {
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--ink-2);
}
.seg button {
  padding: 7px 16px;
  border: none;
  background: transparent;
  color: var(--ivory-dim);
  cursor: pointer;
  font-size: 13px;
}
.seg button.active {
  background: var(--brass);
  color: #fff;
}
.rk-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.rk-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  padding: 16px 20px;
  box-shadow: var(--shadow-sm);
}
.rk-card span {
  font-size: 13px;
  color: var(--ivory-dim);
}
.rk-card strong {
  display: block;
  font-size: 28px;
  color: var(--ivory);
  margin-top: 6px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
}
.count {
  font-size: 12px;
  color: var(--muted);
}
.pagination-bar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  margin-top: 16px;
  gap: 12px;
}
.rect-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  margin-bottom: 10px;
  position: relative;
}
.rect-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: var(--r-sm) 0 0 var(--r-sm);
}
.rect-item.lvl-high::before { background: var(--seal); }
.rect-item.lvl-medium::before { background: var(--amber); }
.rect-item.lvl-low::before { background: var(--sage); }
.rect-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.rect-id { font-size: 12px; color: var(--brass); }
.rect-contract { color: var(--ivory); font-size: 14px; }
.rect-risk,
.rect-note {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.5;
}
.rect-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  flex-shrink: 0;
}
.rect-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
  text-align: right;
  white-space: nowrap;
}
.advance-btn { width: 88px; }
.rk-pending strong  { color: var(--seal); }
.rk-processing strong { color: var(--amber); }
.rk-done strong     { color: var(--sage); }
.overdue            { color: var(--seal) !important; font-weight: 600; }
@media (max-width: 1180px) {
  .rk-row { grid-template-columns: 1fr 1fr; }
  .rect-item { flex-direction: column; }
  .rect-right { align-items: flex-start; flex-direction: row; flex-wrap: wrap; gap: 12px; }
  .rect-meta { text-align: left; flex-direction: row; flex-wrap: wrap; gap: 12px; }
  .advance-btn { width: auto; }
}
</style>
