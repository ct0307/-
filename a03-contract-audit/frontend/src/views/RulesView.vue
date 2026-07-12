<script setup lang="ts">
// 规则与模板管理（仅 admin）：审查规则库 + 合同模板库，增删调 api。
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getRules,
  getTemplates,
  createRule,
  deleteRule,
  createTemplate,
  deleteTemplate,
} from '@/api/rules'
import type { AuditRule, ContractTemplate } from '@/mock/rules'
import DemoBadge from '@/components/common/DemoBadge.vue'

const rules = ref<AuditRule[]>([])
const templates = ref<ContractTemplate[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    ;[rules.value, templates.value] = await Promise.all([getRules(), getTemplates()])
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}

async function delRule(r: AuditRule) {
  await ElMessageBox.confirm(`确认删除规则「${r.name}」？`, '删除确认', { type: 'warning' })
  try {
    await deleteRule(r.id)
    rules.value = rules.value.filter((x) => x.id !== r.id)
    ElMessage.success('已删除')
  } catch {
    ElMessage.error('删除失败（内置规则不可删除）')
  }
}
async function delTemplate(t: ContractTemplate) {
  await ElMessageBox.confirm(`确认删除模板「${t.name}」？`, '删除确认', { type: 'warning' })
  try {
    await deleteTemplate(t.id)
    templates.value = templates.value.filter((x) => x.id !== t.id)
    ElMessage.success('已删除')
  } catch {
    ElMessage.error('删除失败（内置模板不可删除）')
  }
}

// 新增规则
const ruleOpen = ref(false)
const ruleSaving = ref(false)
const ruleForm = ref({ name: '', dimension: '法律条款合规性', level: 'medium' as AuditRule['level'], agent: '法务 Agent', desc: '' })
async function submitRule() {
  if (!ruleForm.value.name) return ElMessage.warning('请填写规则名称')
  ruleSaving.value = true
  try {
    const item = await createRule({ ...ruleForm.value })
    rules.value = [item, ...rules.value]
    ruleOpen.value = false
    ruleForm.value = { name: '', dimension: '法律条款合规性', level: 'medium', agent: '法务 Agent', desc: '' }
    ElMessage.success('已新增规则')
  } catch {
    ElMessage.error('新增失败（需管理员权限）')
  } finally {
    ruleSaving.value = false
  }
}

// 新增模板
const tplOpen = ref(false)
const tplSaving = ref(false)
const tplForm = ref({ name: '', type: '软件开发外包合同', clausesText: '' })
async function submitTpl() {
  if (!tplForm.value.name) return ElMessage.warning('请填写模板名称')
  tplSaving.value = true
  try {
    const clauses = tplForm.value.clausesText.split('\n').map((s) => s.trim()).filter(Boolean)
    const item = await createTemplate({ name: tplForm.value.name, type: tplForm.value.type, clauses })
    templates.value = [item, ...templates.value]
    tplOpen.value = false
    tplForm.value = { name: '', type: '软件开发外包合同', clausesText: '' }
    ElMessage.success('已新增模板')
  } catch {
    ElMessage.error('新增失败（需管理员权限）')
  } finally {
    tplSaving.value = false
  }
}
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <DemoBadge module="rules" />
      <div class="tool-btns">
        <el-button :icon="'EditPen'" @click="tplOpen = true">新增合同模板</el-button>
        <el-button type="primary" :icon="'Plus'" @click="ruleOpen = true">新增审查规则</el-button>
      </div>
    </div>

    <div class="rules-grid">
      <el-card shadow="never">
        <template #header>
          <div class="panel-head"><span>审查规则库</span><span class="count mono">{{ rules.length }} 条规则</span></div>
        </template>
        <article v-for="r in rules" :key="r.id" class="rule-item">
          <div class="rule-main">
            <div class="rule-head">
              <el-tag :type="levelMeta[r.level].type" size="small">{{ levelMeta[r.level].label }}风险</el-tag>
              <b>{{ r.name }}</b>
              <el-tag v-if="r.builtin" size="small" effect="plain">内置</el-tag>
              <el-tag v-else size="small" effect="plain" type="success">自定义</el-tag>
            </div>
            <p class="rule-desc">{{ r.desc }}</p>
            <div class="rule-tags mono"><span>{{ r.dimension }}</span><span>{{ r.agent }}</span></div>
          </div>
          <el-tooltip v-if="r.builtin" content="内置规则不可删除" placement="top">
            <span><el-button link type="danger" :icon="'Delete'" aria-label="删除规则" disabled /></span>
          </el-tooltip>
          <el-button v-else link type="danger" :icon="'Delete'" aria-label="删除规则" @click="delRule(r)" />
        </article>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="panel-head"><span>合同模板库</span><span class="count mono">{{ templates.length }} 个模板</span></div>
        </template>
        <article v-for="t in templates" :key="t.id" class="tpl-item">
          <div class="tpl-head">
            <b>{{ t.name }}</b>
            <el-tag size="small">{{ t.type }}</el-tag>
            <el-tooltip v-if="t.builtin" content="内置模板不可删除" placement="top">
              <span><el-button link type="danger" :icon="'Delete'" aria-label="删除模板" style="margin-left: auto" disabled /></span>
            </el-tooltip>
            <el-button v-else link type="danger" :icon="'Delete'" aria-label="删除模板" style="margin-left: auto" @click="delTemplate(t)" />
          </div>
          <ul class="clause-list">
            <li v-for="(c, i) in t.clauses" :key="i">§ {{ c }}</li>
          </ul>
        </article>
      </el-card>
    </div>

    <!-- 新增规则 -->
    <el-dialog v-model="ruleOpen" title="新增审查规则" width="560px">
      <el-form label-width="80px">
        <el-form-item label="规则名称"><el-input v-model="ruleForm.name" /></el-form-item>
        <el-form-item label="审查维度">
          <el-select v-model="ruleForm.dimension" style="width: 100%">
            <el-option label="法律条款合规性" value="法律条款合规性" />
            <el-option label="风险条款识别" value="风险条款识别" />
            <el-option label="金额与付款条款" value="金额与付款条款" />
            <el-option label="违约责任分析" value="违约责任分析" />
            <el-option label="知识产权条款" value="知识产权条款" />
            <el-option label="保密条款审查" value="保密条款审查" />
            <el-option label="终止与解除条款" value="终止与解除条款" />
            <el-option label="争议解决条款" value="争议解决条款" />
          </el-select>
        </el-form-item>
        <el-form-item label="风险等级">
          <el-select v-model="ruleForm.level" style="width: 100%">
            <el-option label="高风险" value="high" />
            <el-option label="中风险" value="medium" />
            <el-option label="低风险" value="low" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责 Agent">
          <el-select v-model="ruleForm.agent" style="width: 100%">
            <el-option label="法务 Agent" value="法务 Agent" />
            <el-option label="财务 Agent" value="财务 Agent" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则描述"><el-input v-model="ruleForm.desc" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleOpen = false">取消</el-button>
        <el-button type="primary" @click="submitRule">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新增模板 -->
    <el-dialog v-model="tplOpen" title="新增合同模板" width="560px">
      <el-form label-width="80px">
        <el-form-item label="模板名称"><el-input v-model="tplForm.name" /></el-form-item>
        <el-form-item label="合同类型">
          <el-select v-model="tplForm.type" style="width: 100%">
            <el-option label="软件开发外包合同" value="软件开发外包合同" />
            <el-option label="采购合同" value="采购合同" />
            <el-option label="技术服务合同" value="技术服务合同" />
          </el-select>
        </el-form-item>
        <el-form-item label="条款清单"><el-input v-model="tplForm.clausesText" type="textarea" :rows="5" placeholder="每行一条条款" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tplOpen = false">取消</el-button>
        <el-button type="primary" @click="submitTpl">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.tool-btns {
  display: flex;
  gap: 10px;
}
.rules-grid {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 20px;
  align-items: start;
}
.panel-head {
  display: flex;
  justify-content: space-between;
}
.count {
  font-size: 12px;
  color: var(--muted);
}
.rule-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 4px;
  border-bottom: 1px solid var(--line);
}
.rule-item:last-child {
  border-bottom: none;
}
.rule-main {
  flex: 1;
}
.rule-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rule-head b {
  color: var(--ivory);
  font-size: 14px;
}
.rule-desc {
  margin: 6px 0;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.5;
}
.rule-tags {
  display: flex;
  gap: 8px;
}
.rule-tags span {
  font-size: 11px;
  color: var(--muted);
  padding: 2px 8px;
  background: var(--ink-3);
  border-radius: 4px;
}
.tpl-item {
  padding: 12px 4px;
  border-bottom: 1px solid var(--line);
}
.tpl-item:last-child {
  border-bottom: none;
}
.tpl-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tpl-head b {
  color: var(--ivory);
  font-size: 14px;
}
.clause-list {
  margin: 8px 0 0;
  padding-left: 4px;
  list-style: none;
}
.clause-list li {
  font-size: 12px;
  color: var(--ivory-dim);
  padding: 3px 0;
}
@media (max-width: 1180px) {
  .rules-grid {
    grid-template-columns: 1fr;
  }
}
</style>
