<script setup lang="ts">
// 整改跟踪：源自 rectify store（含 AuditView 复核确认生成的真实整改项）。
import { computed, ref } from 'vue'
import { useRectifyStore, type RectifyStatus } from '@/stores/rectify'
import DemoBadge from '@/components/common/DemoBadge.vue'

const rectify = useRectifyStore()
const filter = ref<'全部' | RectifyStatus>('全部')

const filtered = computed(() =>
  filter.value === '全部' ? rectify.items : rectify.items.filter((r) => r.status === filter.value),
)

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
</script>

<template>
  <div>
    <div class="toolbar">
      <div class="seg">
        <button
          v-for="s in segs"
          :key="s"
          :class="{ active: filter === s }"
          @click="filter = s"
        >
          {{ s }}
        </button>
      </div>
      <DemoBadge />
    </div>

    <section class="rk-row">
      <article class="rk-card"><span>待处理</span><strong class="mono">{{ rectify.countByStatus.待处理 }}</strong></article>
      <article class="rk-card"><span>处理中</span><strong class="mono">{{ rectify.countByStatus.处理中 }}</strong></article>
      <article class="rk-card"><span>已闭环</span><strong class="mono">{{ rectify.countByStatus.已闭环 }}</strong></article>
      <article class="rk-card"><span>整改项合计</span><strong class="mono">{{ rectify.total }}</strong></article>
    </section>

    <el-card shadow="never">
      <template #header>
        <div class="panel-head"><span>整改项列表</span><span class="count mono">共 {{ filtered.length }} 项</span></div>
      </template>
      <el-empty v-if="!filtered.length" description="暂无整改项" />
      <article v-for="r in filtered" :key="r.id" class="rect-item" :class="`lvl-${r.level}`">
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
        <div class="rect-meta mono">
          <span>责任人 {{ r.owner }}</span>
          <span>创建 {{ r.created }}</span>
          <span>截止 {{ r.due }}</span>
        </div>
      </article>
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
.rect-item.lvl-high::before {
  background: var(--seal);
}
.rect-item.lvl-medium::before {
  background: var(--amber);
}
.rect-item.lvl-low::before {
  background: var(--sage);
}
.rect-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.rect-id {
  font-size: 12px;
  color: var(--brass);
}
.rect-contract {
  color: var(--ivory);
  font-size: 14px;
}
.rect-risk,
.rect-note {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.5;
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
@media (max-width: 1180px) {
  .rk-row {
    grid-template-columns: 1fr 1fr;
  }
  .rect-item {
    flex-direction: column;
  }
  .rect-meta {
    text-align: left;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 12px;
  }
}
</style>
