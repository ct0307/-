<script setup lang="ts">
// 法规知识库(RAG)：搜索 + 分类 chip + 4 统计卡 + 卡片网格 + 关键词高亮 + 详情。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getKnowledgeCards, getKnowledgeStats, importKnowledge } from '@/api/knowledge'
import type { KnowledgeCard, KnowledgeCat } from '@/mock/knowledge'
import DemoBadge from '@/components/common/DemoBadge.vue'

const cards = ref<KnowledgeCard[]>([])
const stats = ref<{ cat: KnowledgeCat; count: number }[]>([])
const loading = ref(false)
const keyword = ref('')
const activeCat = ref<'全部' | KnowledgeCat>('全部')

const cats: ('全部' | KnowledgeCat)[] = ['全部', '法律法规', '标准条款', '风险规则', '典型案例']
const catType: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  法律法规: 'primary',
  标准条款: 'success',
  风险规则: 'danger',
  典型案例: 'warning',
}

async function load() {
  loading.value = true
  try {
    ;[cards.value, stats.value] = await Promise.all([getKnowledgeCards(), getKnowledgeStats()])
  } catch {
    ElMessage.error('知识库加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return cards.value.filter((c) => {
    const catOk = activeCat.value === '全部' || c.cat === activeCat.value
    const kwOk =
      !kw ||
      c.title.includes(kw) ||
      c.desc.includes(kw) ||
      c.chips.some((t) => t.includes(kw))
    return catOk && kwOk
  })
})

// 关键词命中高亮（RAG 检索体现）
function highlight(text: string): string {
  const kw = keyword.value.trim()
  if (!kw) return text
  return text.replace(new RegExp(`(${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'g'), '<mark>$1</mark>')
}

// 详情
const detailOpen = ref(false)
const active = ref<KnowledgeCard | null>(null)
function openDetail(c: KnowledgeCard) {
  active.value = c
  detailOpen.value = true
}

// 添加知识
const addOpen = ref(false)
const addSaving = ref(false)
const form = ref({ title: '', cat: '法律法规' as KnowledgeCat, desc: '' })

// 前端分类名 → 后端 category 英文键
const catKeyMap: Record<KnowledgeCat, string> = {
  法律法规: 'law',
  标准条款: 'template',
  风险规则: 'rule',
  典型案例: 'case',
}

async function submitAdd() {
  if (!form.value.title || !form.value.desc) {
    ElMessage.warning('请填写标题和摘要')
    return
  }
  addSaving.value = true
  try {
    await importKnowledge({
      category: catKeyMap[form.value.cat],
      source: form.value.title,
      content: form.value.desc,
    })
    // 导入成功后刷新卡片列表（后端已入库）
    await load()
    addOpen.value = false
    form.value = { title: '', cat: '法律法规', desc: '' }
    ElMessage.success('已入库')
  } catch {
    ElMessage.error('入库失败，请重试')
  } finally {
    addSaving.value = false
  }
}
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <div class="search-cats">
        <el-input v-model="keyword" placeholder="搜索法规、条款、案例..." :prefix-icon="'Search'" style="width: 260px" clearable />
        <div class="chips">
          <button v-for="c in cats" :key="c" :class="{ active: activeCat === c }" @click="activeCat = c">{{ c }}</button>
        </div>
      </div>
      <div class="tool-right">
        <DemoBadge module="knowledge" />
        <el-button type="primary" :icon="'Plus'" @click="addOpen = true">添加知识</el-button>
      </div>
    </div>

    <section class="stat-row">
      <article v-for="s in stats" :key="s.cat" class="stat-card">
        <span>{{ s.cat }}</span>
        <strong class="mono">{{ s.count.toLocaleString() }}</strong>
      </article>
    </section>

    <el-empty v-if="!filtered.length" description="未找到匹配的知识条目" />
    <section v-else class="card-grid">
      <article v-for="c in filtered" :key="c.id" class="k-card" @click="openDetail(c)">
        <div class="k-head">
          <el-tag :type="catType[c.cat]" size="small">{{ c.cat }}</el-tag>
          <span class="k-date mono">{{ c.date }}</span>
        </div>
        <h3 v-html="highlight(c.title)" />
        <p class="k-desc" v-html="highlight(c.desc)" />
        <div class="k-chips">
          <span v-for="t in c.chips" :key="t">{{ t }}</span>
        </div>
      </article>
    </section>

    <!-- 详情 -->
    <el-dialog v-model="detailOpen" :title="active?.title" width="620px">
      <template v-if="active">
        <el-tag :type="catType[active.cat]" size="small" style="margin-bottom: 12px">{{ active.cat }}</el-tag>
        <p class="detail-desc">{{ active.desc }}</p>
        <div class="k-chips">
          <span v-for="t in active.chips" :key="t">{{ t }}</span>
        </div>
      </template>
      <template #footer>
        <el-button @click="detailOpen = false">关闭</el-button>
        <el-button type="primary" @click="ElMessage.success('已复制为合同建议（演示）')">应用为合同建议</el-button>
      </template>
    </el-dialog>

    <!-- 添加 -->
    <el-dialog v-model="addOpen" title="添加知识" width="560px">
      <el-form label-width="72px">
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.cat" style="width: 100%">
            <el-option v-for="c in cats.filter((x) => x !== '全部')" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="摘要"><el-input v-model="form.desc" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addOpen = false">取消</el-button>
        <el-button type="primary" :loading="addSaving" @click="submitAdd">入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.search-cats {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.chips {
  display: flex;
  gap: 6px;
}
.chips button {
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--ink-2);
  color: var(--ivory-dim);
  cursor: pointer;
  font-size: 13px;
}
.chips button.active {
  background: var(--brass);
  color: #fff;
  border-color: var(--brass);
}
.tool-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  padding: 16px 20px;
  box-shadow: var(--shadow-sm);
}
.stat-card span {
  font-size: 13px;
  color: var(--ivory-dim);
}
.stat-card strong {
  display: block;
  font-size: 26px;
  color: var(--brass);
  margin-top: 6px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.k-card {
  background: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s var(--ease);
  box-shadow: var(--shadow-sm);
}
.k-card:hover {
  border-color: var(--brass);
  transform: translateY(-2px);
}
.k-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.k-date {
  font-size: 11px;
  color: var(--muted);
}
.k-card h3 {
  margin: 10px 0 6px;
  font-size: 15px;
  line-height: 1.4;
}
.k-desc {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--ivory-dim);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.k-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.k-chips span {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--brass-soft);
  color: var(--brass);
  font-family: var(--mono);
}
.detail-desc {
  line-height: 1.8;
  color: var(--ivory);
  margin: 0 0 14px;
}
:deep(mark) {
  background: var(--amber-soft);
  color: var(--amber);
  padding: 0 2px;
  border-radius: 2px;
}
@media (max-width: 1180px) {
  .stat-row {
    grid-template-columns: 1fr 1fr;
  }
  .card-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
