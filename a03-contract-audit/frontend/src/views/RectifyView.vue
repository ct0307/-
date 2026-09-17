<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRectifyStore, type Rectification, type RectifyStatus } from '@/stores/rectify'

type ViewFilter = '未闭环' | '已逾期' | '即将到期' | '高风险未闭环' | '全部' | RectifyStatus

const rectify = useRectifyStore()
const filter = ref<ViewFilter>('未闭环')
const keyword = ref('')
const page = ref(1)
const pageSize = 10
const changing = ref<Set<string>>(new Set())
const drawerOpen = ref(false)
const activeId = ref('')
const resolutionDraft = ref('')
const reviewDraft = ref('')
const lastLoadedAt = ref('')

async function refresh(force = false) {
  await rectify.load(force)
  if (!rectify.error) {
    lastLoadedAt.value = new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(new Date())
  }
}

onMounted(() => refresh())

const today = () => new Date().toISOString().slice(0, 10)
const addDays = (value: string, days: number) => {
  const date = new Date(`${value}T00:00:00`)
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}
const isOpen = (item: Rectification) => item.status !== '已闭环'
const isOverdue = (item: Rectification) => isOpen(item) && Boolean(item.due) && item.due < today()
const isDueSoon = (item: Rectification) => isOpen(item) && Boolean(item.due)
  && item.due >= today() && item.due <= addDays(today(), 3)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  let list: Rectification[]
  if (filter.value === '全部') list = rectify.items
  else if (filter.value === '未闭环') list = rectify.items.filter(isOpen)
  else if (filter.value === '已逾期') list = rectify.items.filter(isOverdue)
  else if (filter.value === '即将到期') list = rectify.items.filter(isDueSoon)
  else if (filter.value === '高风险未闭环') {
    list = rectify.items.filter((item) => isOpen(item) && item.level === 'high')
  } else list = rectify.items.filter((item) => item.status === filter.value)
  if (kw) {
    list = list.filter((item) => [item.id, item.contract, item.risk, item.owner, item.note]
      .some((value) => value?.toLowerCase().includes(kw)))
  }
  return [...list].sort((a, b) => {
    if (isOverdue(a) !== isOverdue(b)) return isOverdue(a) ? -1 : 1
    const levelOrder = { high: 0, medium: 1, low: 2 }
    return levelOrder[a.level] - levelOrder[b.level] || a.due.localeCompare(b.due)
  })
})
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const activeItem = computed(() => rectify.items.find((item) => item.id === activeId.value) ?? null)
const overdueCount = computed(() => rectify.items.filter(isOverdue).length)
const dueSoonCount = computed(() => rectify.items.filter(isDueSoon).length)
const highOpenCount = computed(() => rectify.items.filter((item) => isOpen(item) && item.level === 'high').length)

const levelMeta = {
  high: { label: '高风险', type: 'danger' as const },
  medium: { label: '中风险', type: 'warning' as const },
  low: { label: '低风险', type: 'info' as const },
}
const statusType: Record<RectifyStatus, 'info' | 'warning' | 'primary' | 'success'> = {
  待处理: 'info', 处理中: 'warning', 待复核: 'primary', 已闭环: 'success',
}
const filters: ViewFilter[] = ['未闭环', '待处理', '处理中', '待复核', '已闭环', '全部']

function selectFilter(value: ViewFilter) {
  filter.value = value
  page.value = 1
}

function filterCount(value: ViewFilter) {
  if (value === '待处理' || value === '处理中' || value === '待复核' || value === '已闭环') {
    return rectify.countByStatus[value]
  }
  return null
}

function openDetail(item: Rectification) {
  activeId.value = item.id
  resolutionDraft.value = item.resolution
  reviewDraft.value = item.review_comment
  drawerOpen.value = true
}

async function transition(item: Rectification, payload: { status: RectifyStatus; resolution?: string; review_comment?: string }) {
  if (changing.value.has(item.id)) return false
  changing.value = new Set([...changing.value, item.id])
  try {
    await rectify.update(item.id, payload)
    return true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '状态更新失败，请重试')
    return false
  } finally {
    const next = new Set(changing.value)
    next.delete(item.id)
    changing.value = next
  }
}

async function start(item: Rectification) {
  if (await transition(item, { status: '处理中' })) ElMessage.success('已开始处理')
}

async function submitReview(item: Rectification) {
  const resolution = resolutionDraft.value.trim()
  if (!resolution) return void ElMessage.warning('请填写具体整改结果')
  if (await transition(item, { status: '待复核', resolution })) ElMessage.success('已提交复核')
}

async function approve(item: Rectification) {
  const reviewComment = reviewDraft.value.trim()
  if (!reviewComment) return void ElMessage.warning('请填写复核结论')
  if (await transition(item, { status: '已闭环', review_comment: reviewComment })) {
    ElMessage.success('复核通过，整改项已闭环')
  }
}

async function reject(item: Rectification) {
  const reviewComment = reviewDraft.value.trim()
  if (!reviewComment) return void ElMessage.warning('请填写退回原因')
  if (await transition(item, { status: '处理中', review_comment: reviewComment })) {
    ElMessage.success('已退回责任人继续整改')
  }
}

async function reopen(item: Rectification) {
  try {
    await ElMessageBox.confirm('重新开启后，该项将回到“待处理”，历史整改结果仍保留。', '重新开启整改项', {
      type: 'warning', confirmButtonText: '确认重新开启', cancelButtonText: '取消',
    })
  } catch { return }
  if (await transition(item, { status: '待处理' })) ElMessage.success('整改项已重新开启')
}

function formatTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
</script>

<template>
  <div class="rectify-page">
    <div class="toolbar">
      <div class="filters" role="tablist" aria-label="整改状态筛选">
        <button v-for="item in filters" :key="item" :class="{ active: filter === item }" @click="selectFilter(item)">
          {{ item }}
          <span v-if="filterCount(item) !== null" class="filter-count">{{ filterCount(item) }}</span>
        </button>
      </div>
      <div class="toolbar-right">
        <el-input v-model="keyword" placeholder="搜索合同、风险、责任人" :prefix-icon="'Search'" clearable @input="page = 1" />
        <span v-if="lastLoadedAt" class="freshness">本次加载 {{ lastLoadedAt }}</span>
        <el-button :icon="'RefreshRight'" :loading="rectify.loading" @click="refresh(true)">刷新</el-button>
      </div>
    </div>

    <el-result v-if="rectify.error" icon="error" title="整改任务加载失败" :sub-title="rectify.error">
      <template #extra><el-button type="primary" @click="refresh(true)">重新加载</el-button></template>
    </el-result>

    <template v-else>
      <section class="attention-strip" aria-label="需要关注的整改任务">
        <button class="metric danger" :class="{ selected: filter === '已逾期' }" @click="selectFilter('已逾期')"><span>已逾期</span><strong>{{ overdueCount }}</strong><small>需优先催办</small></button>
        <button class="metric amber" :class="{ selected: filter === '即将到期' }" @click="selectFilter('即将到期')"><span>3 天内到期</span><strong>{{ dueSoonCount }}</strong><small>提前跟进</small></button>
        <button class="metric blue" @click="selectFilter('待复核')"><span>待复核</span><strong>{{ rectify.countByStatus.待复核 }}</strong><small>等待验收</small></button>
        <button class="metric seal" :class="{ selected: filter === '高风险未闭环' }" @click="selectFilter('高风险未闭环')"><span>高风险未闭环</span><strong>{{ highOpenCount }}</strong><small>管理重点</small></button>
      </section>

      <section v-loading="rectify.loading" class="worklist">
        <header class="list-head"><div><h2>整改任务</h2><p>默认优先显示逾期与高风险任务</p></div><span class="count">共 {{ filtered.length }} 项</span></header>
        <div v-if="!rectify.loading && !filtered.length" class="empty-wrap">
          <el-empty :description="keyword ? '未找到匹配的整改任务' : '当前范围暂无整改任务'" />
        </div>
        <button v-for="item in paged" :key="item.id" class="task-row" :class="`level-${item.level}`" @click="openDetail(item)">
          <div class="task-identity">
            <div class="task-badges">
              <span class="task-id">{{ item.id }}</span>
              <el-tag :type="levelMeta[item.level].type" size="small">{{ levelMeta[item.level].label }}</el-tag>
              <el-tag :type="statusType[item.status]" size="small" effect="plain">{{ item.status }}</el-tag>
              <el-tag v-if="isOverdue(item)" type="danger" size="small" effect="dark">已逾期</el-tag>
            </div>
            <strong>{{ item.risk }}</strong><span class="contract-name">{{ item.contract }}</span>
          </div>
          <div class="task-owner"><span>责任人</span><strong>{{ item.owner || '未分派' }}</strong></div>
          <div class="task-date" :class="{ overdue: isOverdue(item) }"><span>截止日期</span><strong>{{ item.due }}</strong></div>
          <div class="task-action"><span>{{ item.status === '已闭环' ? '查看验收' : '查看并处理' }}</span><el-icon><ArrowRight /></el-icon></div>
        </button>
        <footer v-if="filtered.length > pageSize" class="pagination-bar">
          <el-pagination v-model:current-page="page" :page-size="pageSize" :total="filtered.length" layout="prev, pager, next, total" background />
        </footer>
      </section>
    </template>

    <el-drawer v-model="drawerOpen" size="520px" class="rectify-drawer">
      <template #header><div v-if="activeItem" class="drawer-title"><span>{{ activeItem.id }} · {{ activeItem.status }}</span><strong>{{ activeItem.risk }}</strong></div></template>
      <template v-if="activeItem">
        <section class="detail-section source-section">
          <div class="detail-label">来源审查</div><h3>{{ activeItem.contract }}</h3>
          <div class="source-meta"><el-tag :type="levelMeta[activeItem.level].type" size="small">{{ levelMeta[activeItem.level].label }}</el-tag><span v-if="activeItem.risk_id">风险编号 R{{ activeItem.risk_id }}</span><span>创建于 {{ activeItem.created }}</span></div>
          <p>{{ activeItem.note || '暂无整改建议' }}</p>
        </section>
        <section class="detail-section assignment-grid"><div><span>责任人</span><strong>{{ activeItem.owner || '未分派' }}</strong></div><div><span>截止日期</span><strong :class="{ overdue: isOverdue(activeItem) }">{{ activeItem.due }}</strong></div></section>
        <section class="detail-section">
          <label class="field-label" for="resolution">整改结果 <em v-if="activeItem.status === '处理中'">必填</em></label>
          <el-input id="resolution" v-model="resolutionDraft" type="textarea" :rows="5" maxlength="1000" show-word-limit :readonly="activeItem.status === '待复核' || activeItem.status === '已闭环'" placeholder="说明修改了什么、完成情况及可验收的结果" />
          <el-alert v-if="activeItem.status === '已闭环' && !activeItem.resolution" class="legacy-alert" type="warning" :closable="false" title="该历史记录未保存结构化整改结果" description="可重新开启后补充整改结果，再按新流程提交复核。" />
          <p v-if="activeItem.submitted_at" class="time-note">{{ activeItem.status === '待复核' || activeItem.status === '已闭环' ? '提交复核' : '上次提交复核' }}：{{ formatTime(activeItem.submitted_at) }}</p>
        </section>
        <section v-if="activeItem.status === '待复核' || activeItem.review_comment || activeItem.status === '已闭环'" class="detail-section">
          <label class="field-label" for="review-comment">复核意见</label>
          <el-input id="review-comment" v-model="reviewDraft" type="textarea" :rows="3" maxlength="500" show-word-limit :readonly="activeItem.status === '已闭环'" placeholder="通过时可记录验收结论；退回时必须说明原因" />
          <p v-if="activeItem.closed_at" class="time-note">闭环时间：{{ formatTime(activeItem.closed_at) }}</p>
        </section>
      </template>
      <template #footer><div v-if="activeItem" class="drawer-actions">
        <el-button @click="drawerOpen = false">关闭</el-button>
        <el-button v-if="activeItem.status === '待处理'" type="primary" :loading="changing.has(activeItem.id)" @click="start(activeItem)">开始处理</el-button>
        <el-button v-if="activeItem.status === '处理中'" type="primary" :loading="changing.has(activeItem.id)" @click="submitReview(activeItem)">提交复核</el-button>
        <template v-if="activeItem.status === '待复核'"><el-button :loading="changing.has(activeItem.id)" @click="reject(activeItem)">退回整改</el-button><el-button type="success" :loading="changing.has(activeItem.id)" @click="approve(activeItem)">通过并闭环</el-button></template>
        <el-button v-if="activeItem.status === '已闭环'" :loading="changing.has(activeItem.id)" @click="reopen(activeItem)">重新开启</el-button>
      </div></template>
    </el-drawer>
  </div>
</template>

<style scoped>
.rectify-page { min-width: 0; }
.toolbar { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.filters { display: flex; align-items: center; border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; background: var(--ink-2); }
.filters button { min-height: 38px; padding: 0 14px; border: 0; border-right: 1px solid var(--line); background: transparent; color: var(--ivory-dim); cursor: pointer; font-family: var(--font-body); font-size: var(--type-label); font-weight: 500; line-height: 1.4; }
.filters button:last-child { border-right: 0; }.filters button.active { background: var(--brass); color: var(--on-brass); font-weight: 600; }.filter-count { margin-left: 4px; opacity: .75; }
.toolbar-right { display: flex; align-items: center; gap: 12px; }.toolbar-right :deep(.el-input) { width: 280px; }.freshness { white-space: nowrap; font-family: var(--font-data); font-size: var(--type-caption); font-variant-numeric: tabular-nums; line-height: 1.4; color: var(--muted); }
.attention-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.metric { display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto; gap: 4px 12px; min-height: 86px; padding: 14px 16px; text-align: left; background: var(--ink-2); border: 1px solid var(--line); border-top: 3px solid var(--muted); border-radius: var(--r-sm); color: var(--ivory); cursor: pointer; font-family: var(--font-body); }
.metric span { font-size: var(--type-label); font-weight: 500; line-height: 1.4; color: var(--ivory-dim); }.metric strong { grid-row: 1 / 3; grid-column: 2; align-self: center; font-family: var(--font-data); font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums lining-nums; line-height: 1; }.metric small { font-size: var(--type-caption); line-height: 1.4; color: var(--muted); }
.metric.selected { box-shadow: inset 0 0 0 1px var(--brass); background: var(--brass-soft); }
.metric.danger,.metric.seal { border-top-color: var(--seal); }.metric.danger strong,.metric.seal strong { color: var(--seal); }.metric.amber { border-top-color: var(--amber); }.metric.amber strong { color: var(--amber); }.metric.blue { border-top-color: #527ca5; }.metric.blue strong { color: #527ca5; }
.worklist { background: var(--ink-2); border: 1px solid var(--line); border-radius: var(--r-sm); overflow: hidden; }.list-head { display: flex; justify-content: space-between; align-items: center; padding: 16px 18px; border-bottom: 1px solid var(--line); }
.list-head h2 { margin: 0; font-family: var(--font-body); font-size: var(--type-subtitle); font-weight: 650; line-height: 1.4; color: var(--ivory); }.list-head p { margin: 4px 0 0; font-size: var(--type-label); line-height: 1.5; color: var(--muted); }.count { font-family: var(--font-data); font-size: var(--type-caption); font-variant-numeric: tabular-nums; line-height: 1.4; color: var(--muted); }
.task-row { position: relative; display: grid; grid-template-columns: minmax(280px, 1fr) 130px 130px 120px; width: 100%; gap: 18px; align-items: center; min-height: 96px; padding: 15px 18px 15px 20px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: inherit; text-align: left; cursor: pointer; font-family: var(--font-body); }
.task-row::before { position: absolute; left: 0; top: 16px; bottom: 16px; width: 3px; content: ''; background: var(--sage); }.task-row.level-high::before { background: var(--seal); }.task-row.level-medium::before { background: var(--amber); }.task-row:hover { background: var(--brass-soft); }
.task-identity { min-width: 0; display: flex; flex-direction: column; gap: 6px; }.task-identity strong { overflow: hidden; color: var(--ivory); text-overflow: ellipsis; white-space: nowrap; font-size: 15px; font-weight: 650; line-height: 1.45; }.task-badges { display: flex; align-items: center; gap: 6px; }.task-id { font-family: var(--font-code); font-size: var(--type-caption); font-weight: 500; line-height: 1.35; color: var(--brass); }.contract-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--type-label); line-height: 1.5; color: var(--ivory-dim); }
.task-owner,.task-date { display: flex; flex-direction: column; gap: 5px; }.task-owner span,.task-date span { font-size: var(--type-caption); line-height: 1.35; color: var(--muted); }.task-owner strong,.task-date strong { font-size: var(--type-label); line-height: 1.45; color: var(--ivory-dim); font-weight: 500; }.task-date strong { font-family: var(--font-data); font-variant-numeric: tabular-nums; }.task-action { display: flex; justify-content: flex-end; align-items: center; gap: 5px; color: var(--brass); font-size: var(--type-label); font-weight: 500; line-height: 1.4; }.overdue { color: var(--seal) !important; font-weight: 600 !important; }
.empty-wrap { min-height: 260px; display: grid; place-items: center; }.pagination-bar { display: flex; justify-content: flex-end; padding: 14px 18px; }
.drawer-title { display: flex; flex-direction: column; gap: 5px; }.drawer-title span { font-family: var(--font-code); font-size: var(--type-caption); font-weight: 500; line-height: 1.35; color: var(--brass); }.drawer-title strong { font-family: var(--font-body); font-size: 18px; font-weight: 650; line-height: 1.45; color: var(--ivory); }
.detail-section { padding: 18px 0; border-bottom: 1px solid var(--line); }.detail-section:first-child { padding-top: 0; }.detail-label,.field-label { display: block; margin-bottom: 9px; font-size: var(--type-label); font-weight: 500; line-height: 1.45; color: var(--muted); }.field-label em { margin-left: 5px; color: var(--seal); font-style: normal; }
.source-section h3 { margin: 0 0 9px; font-family: var(--font-body); font-size: 15px; font-weight: 650; line-height: 1.5; color: var(--ivory); }.source-section p { margin: 12px 0 0; color: var(--ivory-dim); font-size: var(--type-body); line-height: var(--leading-body); }.source-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: var(--type-caption); line-height: 1.45; color: var(--muted); }
.assignment-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }.assignment-grid div { display: flex; flex-direction: column; gap: 5px; }.assignment-grid span { color: var(--muted); font-size: var(--type-caption); line-height: 1.35; }.assignment-grid strong { color: var(--ivory); font-size: var(--type-body); font-weight: 600; line-height: 1.45; }.time-note { margin: 8px 0 0; font-family: var(--font-data); font-size: var(--type-caption); font-variant-numeric: tabular-nums; line-height: 1.45; color: var(--muted); }.drawer-actions { display: flex; justify-content: flex-end; gap: 8px; }
.legacy-alert { margin-top: 10px; }
@media (max-width: 1180px) { .toolbar { flex-direction: column; }.toolbar-right { justify-content: space-between; }.attention-strip { grid-template-columns: 1fr 1fr; }.task-row { grid-template-columns: minmax(220px, 1fr) 110px 120px; }.task-action { display: none; } }
@media (max-width: 720px) { .filters { width: 100%; overflow-x: auto; }.filters button { flex: 0 0 auto; }.toolbar-right { align-items: stretch; flex-direction: column; }.toolbar-right :deep(.el-input) { width: 100%; }.attention-strip { grid-template-columns: 1fr 1fr; }.task-row { grid-template-columns: 1fr 1fr; gap: 12px; }.task-identity { grid-column: 1 / -1; }.task-date { align-items: flex-end; }.assignment-grid { grid-template-columns: 1fr; } }
</style>
