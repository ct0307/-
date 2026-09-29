<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { actOnHandoff, getHandoffs, type Handoff } from '@/api/handoffs'

const rows = ref<Handoff[]>([])
const state = ref('')
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const labels = { draft: '待提交', submitted: '待法务接收', accepted: '已接收', returned: '已退回' }
const visibleRows = computed(() => rows.value.filter(row => row.filename.includes(keyword.value)).slice(0, 20))
const emit = defineEmits<{ review: [row: Handoff] }>()
async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await getHandoffs()
    if (!Array.isArray(result?.items)) throw new Error('交接列表响应缺少合同列表')
    rows.value = result.items
    state.value = result.state
  }
  catch { error.value = '交接列表加载失败，请重试' }
  finally { loading.value = false }
}
async function act(row: Handoff, action: 'submit' | 'accept' | 'return') {
  let reason = ''
  if (action === 'return') {
    try { reason = (await ElMessageBox.prompt('请填写退回原因', '退回业务补充', { inputValidator: value => !!value?.trim() || '请输入原因' })).value }
    catch { return }
  }
  loading.value = true
  try { await actOnHandoff(row, action, reason); ElMessage.success('交接状态已更新'); await load() }
  catch (e) { ElMessage.error(e instanceof Error ? e.message : '操作失败，请刷新后重试') }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <el-card class="handoff-queue" shadow="never" v-loading="loading">
    <template #header><div class="queue-heading"><strong>合同交接</strong><el-button size="small" @click="load">刷新交接列表</el-button></div></template>
    <p class="hint">业务提交后，由已获该部门授权的法务接收。接收不改变合同解析和审查结果；管理员可配置法务部门范围。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-empty v-else-if="!rows.length && !loading" :description="state === 'NO_AUTH_SCOPE' ? '暂无授权部门，请联系管理员配置' : '暂无可交接合同，请先上传并确认类型'" />
    <template v-else>
      <el-input v-model="keyword" placeholder="搜索交接合同" clearable aria-label="搜索交接合同" />
      <div class="queue-rows">
        <article v-for="row in visibleRows" :key="row.contract_id" class="queue-row">
          <div><b>{{ row.filename }}</b><p>{{ row.department }} · {{ labels[row.state] }}<span v-if="row.assigned_to"> · 接收人编号 {{ row.assigned_to }}</span></p><p v-if="row.reason">退回说明：{{ row.reason }}</p></div>
          <div class="queue-actions">
            <el-button v-if="row.can_review && row.state === 'accepted'" size="small" type="primary" :disabled="['reviewing', 'validating'].includes(row.contract_status)" @click="emit('review', row)">{{ row.audit_job_id ? '打开审查结果' : '发起审查' }}</el-button>
            <el-button v-if="row.can_submit" size="small" @click="act(row, 'submit')">提交法务审查</el-button>
            <el-button v-if="row.can_accept" size="small" type="primary" @click="act(row, 'accept')">接收</el-button>
            <el-button v-if="row.can_return" size="small" @click="act(row, 'return')">退回</el-button>
          </div>
        </article>
      </div>
      <p v-if="rows.length > 20" class="hint">显示前 20 条匹配合同，可输入名称缩小范围。</p>
    </template>
  </el-card>
</template>

<style scoped>
.handoff-queue { margin: 16px 0; }
.queue-heading,.queue-row { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.queue-row { padding:12px 0; border-bottom:1px solid var(--line); flex-wrap:wrap; }
.queue-row b { overflow-wrap:anywhere; }
.queue-row p,.hint { color:var(--muted); font-size:12px; line-height:1.6; }
.queue-actions { display:flex; gap:8px; flex-wrap:wrap; }
</style>
