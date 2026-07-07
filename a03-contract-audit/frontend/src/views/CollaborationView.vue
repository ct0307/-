<script setup lang="ts">
// 双 Agent 协作全景：展示法务/财务两个 Agent 的职责、协作流程与结果分析。
// 数据源：有真实审查会话（audit-session 有风险）→ 用真实数据；否则降级到 collaboration mock 演示数据。
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuditSessionStore } from '@/stores/audit-session'
import {
  AGENTS,
  COLLAB_CHAIN,
  CROSS_CHECKS,
  DEMO_CONTRACT,
  DEMO_RISKS,
  RISK_TIERS,
  type AgentKey,
  type ChainStage,
  type CrossCheck,
  type DemoRisk,
  type TierKey,
} from '@/mock/collaboration'
import type { RiskOut } from '@/api/types'

const router = useRouter()
const session = useAuditSessionStore()

// 是否有真实审查会话（已审查且有风险）
const isLive = computed(() => session.step >= 2 && session.risks.length > 0)

// 统一风险数据：真实会话优先，否则演示数据
const risks = computed<(RiskOut | DemoRisk)[]>(() =>
  isLive.value ? session.risks : DEMO_RISKS,
)
const contractName = computed(() => (isLive.value ? session.filename : DEMO_CONTRACT))

// 按 Agent 分组
function risksOf(agent: AgentKey) {
  return risks.value.filter((r) => r.agent === agent)
}

// 单个 Agent 的统计：检出数 / 高风险数 / 平均置信度
function statsOf(agent: AgentKey) {
  const list = risksOf(agent)
  const high = list.filter((r) => r.level === 'high').length
  const avg = list.length
    ? Math.round(list.reduce((s, r) => s + r.confidence, 0) / list.length)
    : 0
  return { count: list.length, high, avg }
}

// 协同总览统计
const overview = computed(() => {
  const total = risks.value.length
  const high = risks.value.filter((r) => r.level === 'high').length
  const confirmed = risks.value.filter((r) => r.review_status === 'confirmed').length
  const avg = total
    ? Math.round(risks.value.reduce((s, r) => s + r.confidence, 0) / total)
    : 0
  return { total, high, confirmed, avg }
})

const agentList = [AGENTS.legal, AGENTS.finance]

const levelMeta: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { label: '高', type: 'danger' },
  medium: { label: '中', type: 'warning' },
  low: { label: '低', type: 'info' },
}
const statusLabel: Record<string, string> = {
  pending: '待复核',
  confirmed: '已确认',
  ignored: '已忽略',
  to_modify: '需修改',
}

// 协作链路阶段归属方的视觉映射
const ownerMeta: Record<ChainStage['owner'], { label: string; accent: string; icon: string }> = {
  router: { label: '中央调度', accent: 'var(--ivory-dim)', icon: 'Connection' },
  legal: { label: '法务 Agent', accent: 'var(--brass)', icon: 'Stamp' },
  finance: { label: '财务 Agent', accent: 'var(--sage)', icon: 'Coin' },
  both: { label: '双 Agent 协同', accent: 'var(--seal)', icon: 'Connection' },
}

// 冲突消解裁定的视觉映射
const verdictMeta: Record<CrossCheck['verdict'], { label: string; type: 'danger' | 'warning' | 'success' }> = {
  conflict: { label: '冲突·高风险', type: 'danger' },
  watch: { label: '待观察', type: 'warning' },
  confirmed: { label: '已确认', type: 'success' },
}

const chain = COLLAB_CHAIN
// 冲突项：真实会话用后端返回（store.crossChecks），无会话降级到 mock 剧本。
// 后端字段 from_agent/to_agent 映射到 mock 的 from/to，模板统一消费。
const crossChecks = computed(() =>
  isLive.value && session.crossChecks.length
    ? session.crossChecks.map((c) => ({
        id: c.id,
        from: c.from_agent,
        to: c.to_agent,
        trigger: c.trigger,
        action: c.action,
        verdict: c.verdict,
        note: c.note,
      }))
    : CROSS_CHECKS,
)
const conflictCount = computed(() => crossChecks.value.filter((c) => c.verdict === 'conflict').length)

// —— 分级风险人工干预：把每条风险归入绿/黄/红档 ——
// 真实会话优先用后端权威分档（RiskOut.tier）；mock 演示数据无 tier，前端按同一口径推导。
const RED_KEYWORDS = ['关联交易', '关联方', '重大赔偿', '税法争议', '舞弊', '主体缺失']
function tierOf(r: RiskOut | DemoRisk): TierKey {
  if ('tier' in r && r.tier) return r.tier
  const sensitive = RED_KEYWORDS.some((k) => r.category.includes(k) || r.basis.includes(k))
  if (r.level === 'high' || sensitive) return 'red'
  if (r.level === 'low' && r.confidence > 95) return 'green'
  return 'yellow'
}

// 各档统计：命中数 + 归入该档的风险清单。红档再叠加跨 Agent 冲突项数量。
const tierList = computed(() =>
  (Object.keys(RISK_TIERS) as TierKey[]).map((key) => {
    const items = risks.value.filter((r) => tierOf(r) === key)
    const extraConflicts = key === 'red' ? conflictCount.value : 0
    return { meta: RISK_TIERS[key], items, count: items.length + extraConflicts }
  }),
)

function onTierAction(key: TierKey) {
  const label = RISK_TIERS[key].actionLabel
  if (key === 'red') {
    ElMessage.warning(`已${label}：需法务、财务、合规总监三员共同进入协同界面`)
  } else {
    ElMessage.success(`演示：已执行「${label}」`)
  }
}

function goAudit() {
  router.push('/audit')
}
</script>

<template>
  <div class="collab-page">
    <!-- 顶部：数据源状态 + 当前合同 -->
    <div class="page-head">
      <div class="src-badge" :class="{ live: isLive }">
        <span class="dot" />
        {{ isLive ? '真实审查会话' : '演示数据 · 未开始审查' }}
      </div>
      <div class="head-right">
        <span class="mono contract-name">{{ contractName }}</span>
        <el-button v-if="!isLive" size="small" :icon="'MagicStick'" @click="goAudit">
          去上传合同并审查
        </el-button>
      </div>
    </div>

    <!-- Agent 名片：两个 Agent 的职责 / RAG 主题 / prompt 侧重 -->
    <div class="agent-cards">
      <el-card
        v-for="a in agentList"
        :key="a.key"
        shadow="never"
        class="agent-card"
        :style="{ '--accent': a.accent }"
      >
        <div class="agent-card-head">
          <div class="agent-title">
            <el-icon :size="22"><component :is="a.icon" /></el-icon>
            <div>
              <b>{{ a.name }}</b>
              <small>{{ a.role }}</small>
            </div>
          </div>
          <div class="agent-stat mono">
            <span>{{ statsOf(a.key).count }}</span>
            <em>检出</em>
          </div>
        </div>

        <div class="agent-section">
          <h4>关注维度</h4>
          <div class="chip-row">
            <span v-for="f in a.focus" :key="f" class="chip">{{ f }}</span>
          </div>
        </div>

        <div class="agent-section">
          <h4>定向 RAG 检索主题</h4>
          <ul class="topic-list mono">
            <li v-for="t in a.ragTopics" :key="t">{{ t }}</li>
          </ul>
        </div>

        <div class="agent-section">
          <h4>Prompt 侧重</h4>
          <p class="bias">{{ a.promptBias }}</p>
        </div>

        <div class="agent-mini-kpis">
          <div><span>高风险</span><strong class="seal-num">{{ statsOf(a.key).high }}</strong></div>
          <div><span>平均置信度</span><strong>{{ statsOf(a.key).avg }}%</strong></div>
        </div>
      </el-card>
    </div>

    <!-- 协作链路：主从串行 SOP（法务先行 → 共享上下文 → 财务二次加工 → 交叉验证 → 统一决策）-->
    <el-card shadow="never" class="chain-card">
      <template #header>
        <div class="card-head">
          <span>协作链路 · 主从协同工作流</span>
          <span class="mono status-note">{{ isLive ? '协同完成' : '流程示意' }}</span>
        </div>
      </template>
      <div class="chain">
        <template v-for="(s, i) in chain" :key="s.key">
          <div class="chain-stage" :style="{ '--accent': ownerMeta[s.owner].accent }">
            <div class="stage-badge">
              <el-icon :size="15"><component :is="ownerMeta[s.owner].icon" /></el-icon>
              {{ ownerMeta[s.owner].label }}
            </div>
            <h4>{{ s.title }}</h4>
            <p class="stage-desc">{{ s.desc }}</p>
            <div v-if="s.output" class="stage-output mono">
              <span class="output-label">↳ 传递</span>{{ s.output }}
            </div>
          </div>
          <div v-if="i < chain.length - 1" class="chain-arrow" aria-hidden="true">→</div>
        </template>
      </div>
      <p class="disclaimer">
        与"各跑各的"不同：法务 Agent 先行给出合规结论并写入<b>共享记忆窗口</b>，财务 Agent
        直接读取而不重复解析；两者冲突时进入联合思维链推理，最终由中央节点统一决策。
        结论仅供参考，以人工复核为准。
      </p>
    </el-card>

    <!-- 交叉验证 / 冲突消解：协同核心，展示跨 Agent 触发 -->
    <el-card shadow="never" class="cross-card">
      <template #header>
        <div class="card-head">
          <span>交叉验证 · 冲突消解</span>
          <el-tag v-if="conflictCount" type="danger" size="small">{{ conflictCount }} 项冲突需会审</el-tag>
        </div>
      </template>
      <div class="cross-list">
        <article
          v-for="c in crossChecks"
          :key="c.id"
          class="cross-item"
          :class="`v-${c.verdict}`"
        >
          <div class="cross-flow">
            <span class="cross-agent" :style="{ '--accent': AGENTS[c.from].accent }">
              <el-icon><component :is="AGENTS[c.from].icon" /></el-icon>{{ AGENTS[c.from].name }}
            </span>
            <span class="cross-dir mono">触发 →</span>
            <span class="cross-agent" :style="{ '--accent': AGENTS[c.to].accent }">
              <el-icon><component :is="AGENTS[c.to].icon" /></el-icon>{{ AGENTS[c.to].name }}
            </span>
            <el-tag :type="verdictMeta[c.verdict].type" size="small" class="cross-verdict">
              {{ verdictMeta[c.verdict].label }}
            </el-tag>
          </div>
          <div class="cross-body">
            <p><b>触发条件</b>{{ c.trigger }}</p>
            <p><b>协同动作</b>{{ c.action }}</p>
            <p class="cross-note"><b>联合推理</b>{{ c.note }}</p>
          </div>
        </article>
      </div>
    </el-card>

    <!-- 分级风险人工干预：绿/黄/红三档看板，动态决定人工介入深度 -->
    <el-card shadow="never" class="tier-card">
      <template #header>
        <div class="card-head">
          <span>分级风险 · 人工干预策略</span>
          <span class="mono status-note tier-note">按 AI 置信度 + 风险等级 + 冲突动态分档</span>
        </div>
      </template>
      <div class="tier-board">
        <section
          v-for="t in tierList"
          :key="t.meta.key"
          class="tier-col"
          :class="`tier-${t.meta.key}`"
          :style="{ '--accent': t.meta.accent }"
        >
          <div class="tier-head">
            <span class="tier-dot" />
            <b>{{ t.meta.label }}</b>
            <span class="tier-count mono">{{ t.count }}</span>
          </div>
          <dl class="tier-meta">
            <dt>判定标准</dt>
            <dd>{{ t.meta.criteria }}</dd>
            <dt>介入策略</dt>
            <dd>{{ t.meta.intervention }}</dd>
            <dt>审批人</dt>
            <dd>{{ t.meta.approvers }}</dd>
          </dl>
          <ul v-if="t.items.length" class="tier-items">
            <li v-for="r in t.items" :key="r.id">
              <span class="ti-cat">{{ r.category }}</span>
              <span class="ti-conf mono">{{ r.confidence }}%</span>
            </li>
            <li v-if="t.meta.key === 'red' && conflictCount" class="ti-extra">
              + {{ conflictCount }} 项跨 Agent 冲突
            </li>
          </ul>
          <p v-else class="tier-empty">本档暂无风险项</p>
          <el-button
            class="tier-btn"
            :disabled="t.count === 0"
            :type="t.meta.key === 'red' ? 'danger' : 'default'"
            size="small"
            @click="onTierAction(t.meta.key)"
          >
            {{ t.meta.actionLabel }}
          </el-button>
        </section>
      </div>
      <p class="disclaimer">
        系统不盲目要求人工审核全部合同：绿档 AI 高置信自动过、黄档逐条核实、红档强制三员会审。
        分档结果由 AI 辅助，最终以人工复核为准。
      </p>
    </el-card>

    <!-- 协同总览 KPI -->
    <div class="overview-kpis">
      <div class="kpi"><span>协同检出</span><strong class="mono">{{ overview.total }}</strong></div>
      <div class="kpi"><span>高风险</span><strong class="mono seal-num">{{ overview.high }}</strong></div>
      <div class="kpi"><span>已确认</span><strong class="mono">{{ overview.confirmed }}</strong></div>
      <div class="kpi"><span>平均置信度</span><strong class="mono">{{ overview.avg }}%</strong></div>
    </div>

    <!-- 结果分析：按 Agent 分栏的风险清单对比 -->
    <div class="result-lanes">
      <section
        v-for="a in agentList"
        :key="a.key"
        class="result-lane"
        :style="{ '--accent': a.accent }"
      >
        <div class="result-lane-head">
          <el-icon><component :is="a.icon" /></el-icon>
          <b>{{ a.name }}</b>
          <el-tag size="small" effect="plain">{{ statsOf(a.key).count }} 条</el-tag>
        </div>

        <el-empty
          v-if="risksOf(a.key).length === 0"
          :image-size="60"
          description="该 Agent 未检出风险"
        />
        <div v-else class="risk-list">
          <article
            v-for="r in risksOf(a.key)"
            :key="r.id"
            class="risk-card"
            :class="`lvl-${r.level}`"
          >
            <div class="risk-head">
              <el-tag :type="levelMeta[r.level].type" size="small">
                {{ levelMeta[r.level].label }}风险
              </el-tag>
              <span class="risk-cat">{{ r.category }}</span>
              <el-tag size="small" effect="plain" class="status-tag">
                {{ statusLabel[r.review_status] }}
              </el-tag>
            </div>
            <p class="risk-line">{{ r.suggestion }}</p>
            <div class="risk-foot">
              <span class="basis mono">{{ r.basis }}</span>
              <span class="conf mono">置信度 {{ r.confidence }}%</span>
            </div>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.collab-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.src-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-family: var(--mono);
  color: var(--amber);
  background: var(--amber-soft);
}
.src-badge.live {
  color: var(--sage);
  background: var(--sage-soft);
}
.src-badge .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.head-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.contract-name {
  font-size: 12px;
  color: var(--ivory-dim);
}

/* —— Agent 名片 —— */
.agent-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.agent-card {
  border-top: 3px solid var(--accent);
}
.agent-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.agent-title {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--accent);
}
.agent-title b {
  display: block;
  font-size: 15px;
  color: var(--ivory);
}
.agent-title small {
  font-size: 12px;
  color: var(--muted);
}
.agent-stat {
  text-align: center;
  color: var(--accent);
}
.agent-stat span {
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
}
.agent-stat em {
  display: block;
  font-size: 11px;
  font-style: normal;
  color: var(--muted);
}
.agent-section {
  margin-bottom: 14px;
}
.agent-section h4 {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--ivory-dim);
  font-weight: 600;
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 4px;
  background: var(--ink-3);
  color: var(--ivory-dim);
}
.topic-list {
  margin: 0;
  padding-left: 16px;
  list-style: none;
}
.topic-list li {
  position: relative;
  font-size: 11px;
  color: var(--muted);
  padding: 2px 0;
}
.topic-list li::before {
  content: '›';
  position: absolute;
  left: -14px;
  color: var(--accent);
}
.bias {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ivory-dim);
}
.agent-mini-kpis {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.agent-mini-kpis div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.agent-mini-kpis span {
  font-size: 11px;
  color: var(--muted);
}
.agent-mini-kpis strong {
  font-size: 18px;
  color: var(--ivory);
}
.seal-num {
  color: var(--seal);
}

/* —— 协作链路（主从串行）—— */
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.status-note {
  font-size: 12px;
  color: var(--sage);
}
.chain {
  display: flex;
  align-items: stretch;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.chain-stage {
  flex: 1 1 0;
  min-width: 168px;
  border: 1px solid var(--line);
  border-top: 3px solid var(--accent);
  border-radius: var(--r-md);
  padding: 12px 12px 14px;
  background: var(--ink-3);
  display: flex;
  flex-direction: column;
}
.stage-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  align-self: flex-start;
  font-size: 11px;
  color: var(--accent);
  font-weight: 600;
  margin-bottom: 6px;
}
.chain-stage h4 {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--ivory);
}
.stage-desc {
  margin: 0 0 10px;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--ivory-dim);
  flex: 1;
}
.stage-output {
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--muted);
  background: var(--brass-soft);
  border-radius: var(--r-sm);
  padding: 6px 8px;
}
.output-label {
  color: var(--brass);
  margin-right: 4px;
  font-weight: 600;
}
.chain-arrow {
  display: flex;
  align-items: center;
  color: var(--muted);
  font-size: 18px;
  flex: none;
}

/* —— 交叉验证 / 冲突消解 —— */
.cross-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cross-item {
  border: 1px solid var(--line);
  border-left: 3px solid var(--muted);
  border-radius: var(--r-md);
  padding: 12px 14px;
  background: var(--ink-3);
}
.cross-item.v-conflict {
  border-left-color: var(--seal);
  background: var(--seal-soft);
}
.cross-item.v-watch {
  border-left-color: var(--amber);
}
.cross-item.v-confirmed {
  border-left-color: var(--sage);
}
.cross-flow {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.cross-agent {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
}
.cross-dir {
  font-size: 12px;
  color: var(--muted);
}
.cross-verdict {
  margin-left: auto;
}
.cross-body p {
  margin: 4px 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ivory-dim);
}
.cross-body b {
  display: inline-block;
  min-width: 60px;
  color: var(--muted);
  font-weight: 600;
  margin-right: 6px;
}
.cross-note {
  padding-top: 6px;
  margin-top: 6px !important;
  border-top: 1px dashed var(--line);
}
.cross-note b {
  color: var(--seal);
}

/* —— 分级风险三档看板 —— */
.tier-note {
  color: var(--muted);
}
.tier-board {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.tier-col {
  border: 1px solid var(--line);
  border-top: 3px solid var(--accent);
  border-radius: var(--r-md);
  padding: 14px;
  background: var(--ink-3);
  display: flex;
  flex-direction: column;
}
.tier-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.tier-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--accent);
  flex: none;
}
.tier-head b {
  color: var(--ivory);
  font-size: 14px;
}
.tier-count {
  margin-left: auto;
  font-size: 20px;
  font-weight: 700;
  color: var(--accent);
}
.tier-meta {
  margin: 0 0 12px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 10px;
  font-size: 11.5px;
}
.tier-meta dt {
  color: var(--muted);
  white-space: nowrap;
}
.tier-meta dd {
  margin: 0;
  color: var(--ivory-dim);
  line-height: 1.5;
}
.tier-items {
  margin: 0 0 12px;
  padding: 10px;
  list-style: none;
  background: var(--bg-soft, rgba(0, 0, 0, 0.02));
  border-radius: var(--r-sm);
  border: 1px dashed var(--line);
  flex: 1;
}
.tier-items li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ivory-dim);
  padding: 3px 0;
}
.ti-cat {
  flex: 1;
}
.ti-conf {
  color: var(--accent);
  font-size: 11px;
}
.ti-extra {
  color: var(--seal);
  font-weight: 600;
  padding-top: 6px !important;
  margin-top: 4px;
  border-top: 1px dashed var(--line);
}
.tier-empty {
  margin: 0 0 12px;
  padding: 14px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
  background: var(--bg-soft, rgba(0, 0, 0, 0.02));
  border-radius: var(--r-sm);
  flex: 1;
}
.tier-btn {
  width: 100%;
}
.disclaimer {
  margin: 14px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--muted);
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}

/* —— 协同总览 KPI —— */
.overview-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.kpi {
  background: var(--ink-3);
  border-radius: var(--r-md);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kpi span {
  font-size: 12px;
  color: var(--muted);
}
.kpi strong {
  font-size: 24px;
  color: var(--ivory);
}

/* —— 结果分栏对比 —— */
.result-lanes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  align-items: start;
}
.result-lane {
  border: 1px solid var(--line);
  border-top: 3px solid var(--accent);
  border-radius: var(--r-md);
  padding: 16px;
  background: var(--bg, transparent);
}
.result-lane-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  color: var(--accent);
}
.result-lane-head b {
  color: var(--ivory);
  font-size: 14px;
}
.risk-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.risk-card {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 12px 14px;
  position: relative;
}
.risk-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: var(--r-sm) 0 0 var(--r-sm);
}
.risk-card.lvl-high::before {
  background: var(--seal);
}
.risk-card.lvl-medium::before {
  background: var(--amber);
}
.risk-card.lvl-low::before {
  background: var(--sage);
}
.risk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.risk-cat {
  font-weight: 600;
  color: var(--ivory);
  font-size: 13px;
}
.status-tag {
  margin-left: auto;
}
.risk-line {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--ivory-dim);
  line-height: 1.6;
}
.risk-foot {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
}
.basis {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.5;
}
.conf {
  font-size: 11px;
  color: var(--accent);
  align-self: flex-end;
}
@media (max-width: 1180px) {
  .agent-cards,
  .result-lanes,
  .tier-board {
    grid-template-columns: 1fr;
  }
  .overview-kpis {
    grid-template-columns: 1fr 1fr;
  }
  /* 链路在窄屏纵向堆叠，箭头转向下 */
  .chain {
    flex-direction: column;
  }
  .chain-arrow {
    justify-content: center;
    transform: rotate(90deg);
  }
}
</style>
