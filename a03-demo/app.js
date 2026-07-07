/* ============================================================
   合同智审 · 交互逻辑
   角色体系 / 工作台 / 批量队列 / 多智能体协同 / 全文批注
   纯前端演示，数据为模拟数据
   ============================================================ */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const state = {
  files: [],
  queue: [],          // 批量审查队列项
  currentId: null,    // 当前查看的合同 id
  activeView: "dashboard",
  role: "legal",
  range: "month",
  knowledgeCat: "全部",
  knowledgeKeyword: "",
  historyKeyword: "",
  historyLevel: "全部",
  historyPage: 1,
  pageSize: 6,
  lastRiskAction: null,
  rectifyFilter: "全部",
  drill: { type: "全部", amount: "全部", level: "全部" },
  auditKeyword: "",
  editingRuleId: null,
  editingTemplateId: null
};

/* ---------- 整改项 / 规则 / 模板 / 通知 / 审计（新增模块数据） ---------- */
// 整改项：由风险复核确认后生成，这里预置若干示例
let rectifyId = 0;
const rectifications = [
  { id: `RC${++rectifyId}`, contract: "服务器采购框架协议", risk: "违约责任覆盖不完整", level: "high", owner: "法务负责人", status: "处理中", created: "2026-07-05", due: "2026-07-12", note: "已起草补充协议，等待对方回签。" },
  { id: `RC${++rectifyId}`, contract: "数据中心机房建设合同", risk: "付款节点超预算 8%", level: "high", owner: "财务会计", status: "待处理", created: "2026-07-05", due: "2026-07-10", note: "需财务与采购重新核定付款计划。" },
  { id: `RC${++rectifyId}`, contract: "云平台年度订阅合同", risk: "发票前置规则缺失", level: "medium", owner: "财务会计", status: "已闭环", created: "2026-07-03", due: "2026-07-08", note: "已在补充条款中绑定发票与付款节点，双方确认。" },
  { id: `RC${++rectifyId}`, contract: "品牌视觉设计外包合同", risk: "知识产权归属未明确", level: "medium", owner: "法务负责人", status: "待处理", created: "2026-07-02", due: "2026-07-09", note: "待补充著作权归属与源文件交付范围。" }
];
const RECTIFY_STATUS = ["待处理", "处理中", "已闭环"];

// 审查规则库（可增删）
let ruleId = 0;
const auditRules = [
  { id: `R${++ruleId}`, name: "违约责任必须双向对等", dimension: "breach", level: "high", agent: "legal", desc: "合同违约责任若仅约束单方（如仅约束乙方延期），判定为高风险，须补充双方责任边界。", builtin: true },
  { id: `R${++ruleId}`, name: "付款节点须绑定发票与验收", dimension: "payment", level: "medium", agent: "finance", desc: "各付款节点应与验收确认单、增值税发票、里程碑绑定，否则提示财务风险。", builtin: true },
  { id: `R${++ruleId}`, name: "验收标准须可量化", dimension: "legal", level: "medium", agent: "legal", desc: "出现「甲方满意」等主观表述且无量化指标时，判定为履约风险。", builtin: true },
  { id: `R${++ruleId}`, name: "知识产权归属须书面约定", dimension: "ip", level: "medium", agent: "legal", desc: "定制开发类合同未约定著作权、源代码交付范围时提示合规风险。", builtin: true },
  { id: `R${++ruleId}`, name: "保密期限不得约定为永久", dimension: "confidentiality", level: "low", agent: "legal", desc: "保密期限缺失或约定永久时提示，建议 3-5 年或按核心秘密单列。", builtin: true },
  { id: `R${++ruleId}`, name: "违约金总额不宜超过标的 30%", dimension: "breach", level: "medium", agent: "finance", desc: "违约金累计上限超过合同总价 30% 时提示可能被法院酌减。", builtin: true }
];

// 合同模板库（可增删）
let templateId = 0;
const contractTemplateLib = [
  { id: `T${++templateId}`, name: "软件开发外包合同标准模板", type: "软件开发外包合同", clauses: ["合同标的与需求范围", "开发周期与里程碑", "付款方式与节点", "验收标准与异议处理", "知识产权归属", "保密条款", "违约责任", "争议解决"], builtin: true },
  { id: `T${++templateId}`, name: "采购合同标准模板", type: "采购合同", clauses: ["采购标的与规格", "价格与付款", "交付与验收", "质保与售后", "违约责任", "争议解决"], builtin: true },
  { id: `T${++templateId}`, name: "技术服务合同标准模板", type: "技术服务合同", clauses: ["服务内容与SLA", "服务期限", "费用与结算", "数据与保密", "责任限制", "争议解决"], builtin: true }
];

// 通知与预警
let notifyId = 0;
const notifications = [
  { id: `N${++notifyId}`, type: "alert", title: "高风险合同预警", text: "《服务器采购框架协议》检出 5 项风险，其中 2 项高风险待复核。", time: "10 分钟前", read: false },
  { id: `N${++notifyId}`, type: "alert", title: "付款超预算预警", text: "《数据中心机房建设合同》付款节点超预算 8%，请财务复核。", time: "25 分钟前", read: false },
  { id: `N${++notifyId}`, type: "rectify", title: "整改项即将到期", text: "《数据中心机房建设合同》整改项 RC2 将于 2026-07-10 到期。", time: "1 小时前", read: false },
  { id: `N${++notifyId}`, type: "info", title: "知识库已更新", text: "法规知识库同步《民法典》司法解释 3 条，可被 RAG 检索。", time: "半天前", read: true }
];

// 角色权限矩阵（RBAC 演示）
const accessModules = ["合同审查", "整改跟踪", "多维报表", "法规知识库", "规则与模板", "审查记录", "权限与审计"];
const accessMatrix = {
  legal:   { label: "法务主管", perms: { "合同审查": "读写", "整改跟踪": "读写", "多维报表": "只读", "法规知识库": "读写", "规则与模板": "只读", "审查记录": "只读", "权限与审计": "无" } },
  finance: { label: "财务主管", perms: { "合同审查": "读写", "整改跟踪": "读写", "多维报表": "读写", "法规知识库": "只读", "规则与模板": "无", "审查记录": "只读", "权限与审计": "无" } },
  admin:   { label: "系统管理员", perms: { "合同审查": "读写", "整改跟踪": "读写", "多维报表": "读写", "法规知识库": "读写", "规则与模板": "读写", "审查记录": "读写", "权限与审计": "读写" } }
};

// 操作审计日志
let auditSeq = 0;
const auditLog = [
  { id: `L${++auditSeq}`, user: "曾庆豪", role: "法务主管", action: "确认风险并生成整改项", target: "服务器采购框架协议", time: "2026-07-05 14:32", ip: "10.20.3.11" },
  { id: `L${++auditSeq}`, user: "陈嘉禾", role: "财务主管", action: "标记误报", target: "云平台年度订阅合同", time: "2026-07-05 11:20", ip: "10.20.3.24" },
  { id: `L${++auditSeq}`, user: "曾庆豪", role: "法务主管", action: "导出审查报告", target: "合同合规审查报告.csv", time: "2026-07-05 10:05", ip: "10.20.3.11" },
  { id: `L${++auditSeq}`, user: "王督政", role: "系统管理员", action: "新增审查规则", target: "违约金总额不宜超过标的 30%", time: "2026-07-04 17:40", ip: "10.20.3.2" },
  { id: `L${++auditSeq}`, user: "系统", role: "系统", action: "批量审查完成", target: "6 份合同", time: "2026-07-04 09:12", ip: "127.0.0.1" }
];
function pushAudit(action, target) {
  const r = roles[state.role];
  auditLog.unshift({ id: `L${++auditSeq}`, user: r.name, role: r.role, action, target, time: "2026-07-07 " + nowClock(), ip: "10.20.3.11" });
}
// 演示用递增时钟（避免使用真实 Date，保持可复现）
let clockMin = 0;
function nowClock() {
  clockMin += 7;
  const base = 9 * 60 + 15 + clockMin;
  const h = String(Math.floor(base / 60) % 24).padStart(2, "0");
  const m = String(base % 60).padStart(2, "0");
  return `${h}:${m}`;
}

// 合同修订版全文（用于版本比对；对照 contractFulltext 的原版）
const contractRevised = [
  { h: "第一条  合同标的", type: "same", p: "甲方委托乙方开发并部署「企业合同智能审查系统」，含合同解析、风险识别、多维报表与多智能体协同等模块，具体功能以附件一《需求规格说明书》为准。" },
  { h: "第五条  项目验收", type: "changed", old: "项目成果达到甲方满意后视为验收通过，验收周期与异议处理另行沟通。", p: "乙方交付后 10 个工作日内甲方按附件二《验收标准》完成验收，含功能清单、性能指标、缺陷等级与异议处理流程；逾期未提异议视为通过。" },
  { h: "第六条  合同价款与支付", type: "changed", old: "甲方在验收后 15 个工作日内支付验收款，付款方式为银行转账。", p: "各付款节点须以乙方开具合规增值税专用发票及验收确认单为前置条件；甲方于收票并审核通过后 15 个工作日内付款。" },
  { h: "第九条  违约责任", type: "changed", old: "乙方延期交付的，按合同总价 0.5%/日向甲方支付违约金，累计不超过合同总价的 20%。", p: "任一方违约的，违约方按合同总价 0.5%/日向守约方支付违约金，累计上限 20%；甲方付款逾期同样适用，双方责任对等。" },
  { h: "第十一条  保密条款", type: "changed", old: "双方应对合作过程中获悉的对方商业信息承担保密义务，未经许可不得向第三方披露。", p: "双方对合作中获悉的商业信息承担保密义务，合同终止后持续 3 年；源代码、技术方案等核心商业秘密长期有效。" },
  { h: "第十四条  争议解决", type: "same", p: "因本合同引起的争议，双方应友好协商解决；协商不成的，提交合同签订地人民法院诉讼解决。" },
  { h: "第十五条  知识产权归属", type: "added", p: "本合同定制开发的软件著作权、源代码及相关文档归甲方所有，乙方保证交付成果不侵犯第三方权利；使用的开源组件须书面声明许可类型。" }
];

/* ---------- 角色 ---------- */
const roles = {
  legal:   { name: "曾庆豪", role: "法务主管", avatar: "曾", eyebrow: "LEGAL WORKBENCH", todoView: "法务视角", dot: "legal" },
  finance: { name: "陈嘉禾", role: "财务主管", avatar: "陈", eyebrow: "FINANCE WORKBENCH", todoView: "财务视角", dot: "finance" },
  admin:   { name: "王督政", role: "系统管理员", avatar: "王", eyebrow: "ADMIN CONSOLE", todoView: "全域视角", dot: "admin" }
};

// 各角色工作台 KPI
const dashKpiByRole = {
  legal:   [["待我复核", "12", "seal"], ["本月已审", "148", "brass"], ["高风险条款", "23", "seal"], ["合规通过率", "87%", "sage"]],
  finance: [["待对账合同", "9", "amber"], ["涉及金额", "¥ 2,860万", "brass"], ["付款风险项", "15", "seal"], ["预算偏差", "-3.2%", "sage"]],
  admin:   [["今日审查量", "56", "brass"], ["在线用户", "18", "sage"], ["Agent 调用", "1,204", "brass"], ["系统可用率", "99.9%", "sage"]]
};

// 各角色待办
const todoByRole = {
  legal: [
    { c: "服务器采购框架协议", t: "5 项高风险待复核", lv: "high", time: "10 分钟前" },
    { c: "软件许可使用协议", t: "违约责任条款需确认", lv: "high", time: "1 小时前" },
    { c: "2026 年度销售代理协议", t: "争议解决条款待补充", lv: "medium", time: "3 小时前" },
    { c: "品牌视觉设计外包合同", t: "知识产权归属待核", lv: "medium", time: "昨天" }
  ],
  finance: [
    { c: "数据中心机房建设合同", t: "付款节点超预算 8%", lv: "high", time: "20 分钟前" },
    { c: "云平台年度订阅合同", t: "发票前置规则缺失", lv: "medium", time: "2 小时前" },
    { c: "服务器采购框架协议", t: "质保金比例待对账", lv: "medium", time: "半天前" },
    { c: "员工商业保险采购协议", t: "金额与预算已对齐", lv: "low", time: "昨天" }
  ],
  admin: [
    { c: "法务规则库 v2.6", t: "3 条新规待上线审批", lv: "medium", time: "30 分钟前" },
    { c: "财务 Agent 阈值配置", t: "预算联动参数待确认", lv: "medium", time: "2 小时前" },
    { c: "季度审查量报告", t: "待导出报送管理层", lv: "low", time: "今天" },
    { c: "用户权限盘点", t: "18 个账号例行复核", lv: "low", time: "昨天" }
  ]
};

const activityFeed = [
  { who: "法务 Agent", what: "完成《服务器采购框架协议》合规审查，发现 5 项风险", time: "10 分钟前", dot: "legal" },
  { who: "财务 Agent", what: "校验《数据中心机房建设合同》付款节点，标记超预算", time: "25 分钟前", dot: "finance" },
  { who: "陈嘉禾", what: "确认《云平台订阅合同》整改项 2 条", time: "1 小时前", dot: "finance" },
  { who: "曾庆豪", what: "导出《合同合规审查报告》风险台账", time: "2 小时前", dot: "legal" },
  { who: "系统", what: "法规知识库同步《民法典》司法解释 3 条", time: "半天前", dot: "admin" }
];

/* ---------- 合同模板（批量队列用） ---------- */
const contractTemplates = [
  { name: "企业合同智能审查系统开发外包合同", type: "软件开发外包合同", high: 1, mid: 2, low: 1 },
  { name: "服务器采购框架协议", type: "采购合同", high: 2, mid: 2, low: 1 },
  { name: "云平台年度订阅服务合同", type: "技术服务合同", high: 1, mid: 1, low: 2 },
  { name: "品牌视觉设计外包合同", type: "软件开发外包合同", high: 0, mid: 2, low: 2 },
  { name: "数据中心机房建设合同", type: "采购合同", high: 2, mid: 1, low: 1 },
  { name: "市场推广服务合同", type: "技术服务合同", high: 0, mid: 1, low: 1 }
];

const metadata = {
  甲方: { value: "杭州启明数字科技有限公司", warn: false },
  乙方: { value: "浙江云栖智能服务有限公司", warn: false },
  合同标的: { value: "企业合同智能审查系统开发与部署服务", warn: false },
  合同金额: { value: "¥ 860,000.00", warn: false },
  付款节点: { value: "30% 预付款 / 50% 验收款 / 20% 质保款", warn: false },
  履约期限: { value: "2026-08-01 至 2027-01-31", warn: false },
  违约责任: { value: "延期交付已约定，付款逾期责任缺失", warn: true }
};

const risks = [
  { title: "违约责任覆盖不完整", level: "high", label: "高风险", type: "合规风险", dimension: "breach", agent: "legal", owner: "法务负责人", status: "待复核",
    clause: "第 9 条：乙方延期交付按合同总价 0.5%/日支付违约金。",
    basis: "《民法典》合同编第 577 条：违约责任应明确责任承担方式、赔偿范围和履行边界。",
    description: "条款只覆盖乙方延期交付，未覆盖甲方付款逾期、验收拖延、资料泄露等关键违约场景。",
    suggestion: "补充双方违约责任边界、赔偿上限、违约金计算方式和免责条件。" },
  { title: "验收标准不可量化", level: "medium", label: "中风险", type: "履约风险", dimension: "legal", agent: "legal", owner: "项目经理", status: "待确认",
    clause: "第 5 条：项目成果达到甲方满意后视为验收通过。",
    basis: "企业标准条款：验收应包含交付物清单、量化指标、验收周期和异议处理流程。",
    description: "「甲方满意」属于主观表述，后续容易引发交付争议。",
    suggestion: "增加功能清单、性能指标、验收周期、缺陷等级和异议处理流程。" },
  { title: "付款条件缺少发票前置规则", level: "medium", label: "中风险", type: "财务风险", dimension: "payment", agent: "finance", owner: "财务会计", status: "待补充",
    clause: "第 6 条：甲方在验收后 15 个工作日内支付验收款。",
    basis: "企业财务制度：付款审批起算条件应与验收单、发票和账户信息绑定。",
    description: "付款条款未说明发票类型、开票时间和付款审批起算条件。",
    suggestion: "明确发票类型、开具时点、收票后付款周期和账户信息变更流程。" },
  { title: "保密义务期限不明确", level: "low", label: "低风险", type: "合规风险", dimension: "confidentiality", agent: "legal", owner: "法务负责人", status: "可优化",
    clause: "第 11 条：双方应对合作中获悉的商业信息承担保密义务。",
    basis: "保密条款模板：普通商业信息建议 3-5 年，核心商业秘密可长期有效。",
    description: "未说明合同终止后的保密持续期限。",
    suggestion: "补充合同终止后 3-5 年保密义务，核心商业秘密可约定长期有效。" },
  { title: "知识产权归属未明确", level: "medium", label: "中风险", type: "合规风险", dimension: "ip", agent: "legal", owner: "法务负责人", status: "待确认",
    clause: "附件一：乙方负责系统源代码开发、部署与培训服务。",
    basis: "软件外包合同标准条款：定制开发成果的著作权、源代码交付范围、第三方组件使用边界应书面约定。",
    description: "合同仅描述开发服务，未明确源代码、模型提示词、规则库和二次开发成果的权利归属。",
    suggestion: "补充交付成果清单、著作权归属、源代码授权范围、第三方开源组件声明和侵权责任。" },
  { title: "合同解除条件缺少触发边界", level: "medium", label: "中风险", type: "履约风险", dimension: "termination", agent: "legal", owner: "项目经理", status: "待补充",
    clause: "第 12 条：任一方严重违约时，守约方有权解除合同。",
    basis: "《民法典》第 562 条、第 563 条：约定解除和法定解除应具备明确触发事由、通知方式和后果安排。",
    description: "“严重违约”缺少量化边界，后续可能对解除条件、结算方式和资料返还产生争议。",
    suggestion: "明确可解除情形、整改宽限期、通知方式、已完成工作结算和资料/账号返还要求。" },
  { title: "争议解决管辖地表述不完整", level: "low", label: "低风险", type: "合规风险", dimension: "dispute", agent: "legal", owner: "法务负责人", status: "可优化",
    clause: "第 14 条：协商不成的，提交合同签订地人民法院诉讼解决。",
    basis: "争议解决条款模板：应明确诉讼或仲裁、管辖机构、适用法律和送达地址。",
    description: "条款已有诉讼路径，但缺少签订地定义、送达地址和电子送达约定。",
    suggestion: "补充合同签订地、管辖法院、送达地址确认和电子送达有效性。" }
];
risks.forEach((risk) => { risk.initialStatus = risk.status; });

// 合同全文（批注视图用）；{{n}} 为风险锚点占位
const contractFulltext = [
  { h: "第一条  合同标的", p: "甲方委托乙方开发并部署「企业合同智能审查系统」，含合同解析、风险识别、多维报表与多智能体协同等模块，具体功能以附件一《需求规格说明书》为准。" },
  { h: "第五条  项目验收", p: "乙方完成开发后提交甲方验收。{{1}}项目成果达到甲方满意后视为验收通过，验收周期与异议处理另行沟通。" },
  { h: "第六条  合同价款与支付", p: "合同总价为人民币捌拾陆万元整（¥860,000.00）。{{2}}甲方在验收后 15 个工作日内支付验收款，付款方式为银行转账。" },
  { h: "第九条  违约责任", p: "{{0}}乙方延期交付的，按合同总价 0.5%/日向甲方支付违约金，累计不超过合同总价的 20%。" },
  { h: "第十一条  保密条款", p: "{{3}}双方应对合作过程中获悉的对方商业信息承担保密义务，未经许可不得向第三方披露。" },
  { h: "第十四条  争议解决", p: "因本合同引起的争议，双方应友好协商解决；协商不成的，提交合同签订地人民法院诉讼解决。" }
];

/* ---------- 报表数据 ---------- */
const reportData = {
  month: { kpi: { total: "1,286", pass: "87.3%", risk: "326", time: "4.2min" },
    trend: { total: [820,910,1040,1120,1180,1240,1286], pass: [700,790,900,980,1030,1080,1122], risk: [96,88,80,72,66,58,52] },
    donut: [24,34,28,14],
    depts: [{name:"研发外包部",risk:98,money:"117.2 万"},{name:"采购中心",risk:85,money:"52.3 万"},{name:"市场运营部",risk:72,money:"18.0 万"},{name:"IT 运维部",risk:56,money:"44.6 万"}],
    tops: [["违约责任不对等",98],["付款条件不明确",85],["知识产权归属缺失",72],["验收标准不可量化",64],["保密期限缺失",58]] },
  quarter: { kpi: { total: "3,842", pass: "85.1%", risk: "1,024", time: "4.6min" },
    trend: { total: [2100,2480,2760,3050,3320,3600,3842], pass: [1740,2060,2320,2560,2790,3010,3270], risk: [320,290,262,234,210,186,168] },
    donut: [26,32,27,15],
    depts: [{name:"研发外包部",risk:94,money:"356.8 万"},{name:"采购中心",risk:88,money:"164.5 万"},{name:"市场运营部",risk:69,money:"58.2 万"},{name:"IT 运维部",risk:61,money:"132.7 万"}],
    tops: [["违约责任不对等",96],["付款条件不明确",90],["验收标准不可量化",78],["知识产权归属缺失",70],["保密期限缺失",62]] },
  year: { kpi: { total: "14,905", pass: "83.6%", risk: "3,918", time: "5.1min" },
    trend: { total: [6200,8100,9600,11200,12600,13800,14905], pass: [5000,6600,7900,9300,10500,11500,12461], risk: [1180,1060,960,862,770,690,618] },
    donut: [28,30,26,16],
    depts: [{name:"研发外包部",risk:91,money:"1,286 万"},{name:"采购中心",risk:84,money:"642 万"},{name:"IT 运维部",risk:66,money:"498 万"},{name:"市场运营部",risk:63,money:"224 万"}],
    tops: [["违约责任不对等",93],["付款条件不明确",88],["验收标准不可量化",82],["知识产权归属缺失",74],["保密期限缺失",66]] }
};

const donutMeta = [
  { key: "高风险", color: "var(--seal)", cls: "dot-red" },
  { key: "中风险", color: "var(--amber)", cls: "dot-gold" },
  { key: "低风险", color: "var(--sage)", cls: "dot-green" },
  { key: "无风险", color: "var(--ivory-dim)", cls: "dot-blue" }
];

const knowledgeCards = [
  { title: "《民法典》第五百七十七条 · 违约责任", tag: "法律法规", desc: "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。", chips: ["民法典","违约责任","第577条"], date: "2026-06-15" },
  { title: "《民法典》第五百八十五条 · 违约金调整", tag: "法律法规", desc: "约定的违约金低于造成损失的，可请求增加；过分高于造成损失的，可请求适当减少。约定违约金以实际损失为基础衡量。", chips: ["民法典","违约金","第585条"], date: "2026-06-12" },
  { title: "《民法典》第五百六十二条 · 合同解除", tag: "法律法规", desc: "当事人协商一致可以解除合同。当事人可以约定一方解除合同的事由，解除合同的事由发生时，解除权人可以解除合同。", chips: ["民法典","合同解除","第562条"], date: "2026-06-10" },
  { title: "《保障中小企业款项支付条例》· 付款期限", tag: "法律法规", desc: "机关、事业单位从中小企业采购货物、工程、服务，应当自交付之日起 30 日内支付款项；合同另有约定的，付款期限最长不得超过 60 日。", chips: ["支付条例","付款期限","中小企业"], date: "2026-06-03" },
  { title: "《技术合同示范文本》GF-2016-0301 · 验收条款", tag: "标准条款", desc: "研究开发成果的验收应约定验收标准、验收方法、验收期限及异议处理；未达到约定标准的，研究开发人应承担相应责任。", chips: ["技术合同","验收标准","示范文本"], date: "2026-05-28" },
  { title: "软件开发外包合同 · 知识产权归属条款", tag: "标准条款", desc: "定作方支付报酬取得的著作权归属应书面约定；未约定的，著作权归受托方，但定作方在约定范围内享有使用权。参照《著作权法》第十九条。", chips: ["软件外包","著作权","第19条"], date: "2026-05-25" },
  { title: "分阶段付款条款 · 发票前置模板", tag: "标准条款", desc: "各付款节点应与验收确认单、增值税专用发票、项目里程碑绑定；卖方开具合规发票并经审核后，买方于约定工作日内付款。", chips: ["付款节点","增值税发票","里程碑"], date: "2026-05-20" },
  { title: "保密期限设置规则 · 风险提示", tag: "风险规则", desc: "保密期限不宜约定为永久。普通商业信息建议 3-5 年，核心商业秘密（技术方案、源代码、客户名单）可约定长期有效。", chips: ["保密条款","期限","商业秘密"], date: "2026-05-18" },
  { title: "违约金上限规则 · 风险提示", tag: "风险规则", desc: "违约金总额不宜超过合同标的额的 30%。约定过高易被法院酌减，约定过低难以覆盖实际损失，建议设置合理区间与赔偿上限。", chips: ["违约金","30%上限","风险规则"], date: "2026-05-15" },
  { title: "争议解决条款缺失 · 风险规则", tag: "风险规则", desc: "合同应明确约定争议解决方式（诉讼或仲裁）及管辖地。约定不明将默认由被告住所地或合同履行地法院管辖，增加维权成本。", chips: ["争议解决","管辖","仲裁"], date: "2026-05-12" },
  { title: "最高法指导案例 · 违约金过高酌减纠纷", tag: "典型案例", desc: "合同约定违约金按日 0.5% 计算，法院认为明显高于实际损失，参照 LPR 的 1.3-1.5 倍调整，最终酌减违约金数额。", chips: ["指导案例","违约金酌减","LPR"], date: "2026-05-08" },
  { title: "软件外包成果归属纠纷 · 典型案例", tag: "典型案例", desc: "合同未约定开发成果著作权归属，交付后双方就源代码权属产生争议，法院依《著作权法》认定归受托方，定作方仅享使用权。", chips: ["典型案例","著作权","软件外包"], date: "2026-05-05" }
];

const historyRows = [
  ["CT202607001","华为云服务器年度采购框架协议","采购合同","曾庆豪","2026-07-05 14:30","高风险","5","待整改"],
  ["CT202607002","阿里云 ECS 运维服务合同（续签）","技术服务合同","陈嘉禾","2026-07-04 10:15","低风险","1","已通过"],
  ["CT202607003","杭州启明 × 浙江云栖 软件开发外包合同","软件开发外包合同","曾庆豪","2026-07-04 09:00","高风险","4","待整改"],
  ["CT202607004","写字楼物业租赁续约合同（2026-2028）","租赁合同","王督政","2026-07-03 16:45","低风险","0","已通过"],
  ["CT202607005","AI 算法工程师竞业限制协议","劳动合同","曾庆豪","2026-07-03 11:20","中风险","2","待整改"],
  ["CT202607006","Oracle 数据库许可及维保协议","技术服务合同","陈嘉禾","2026-07-02 15:10","高风险","6","未通过"],
  ["CT202607007","抖音企业号代运营服务合同","技术服务合同","王督政","2026-07-01 09:30","低风险","1","已通过"],
  ["CT202607008","联想 ThinkPad 笔记本批量采购合同","采购合同","陈嘉禾","2026-07-01 08:00","低风险","0","已通过"],
  ["CT202606009","腾讯云安全服务年度订阅合同","技术服务合同","曾庆豪","2026-06-30 17:20","中风险","3","待整改"],
  ["CT202606010","数据中心机柜托管及网络接入合同","采购合同","陈嘉禾","2026-06-29 13:05","高风险","5","未通过"],
  ["CT202606011","员工补充医疗保险集体投保合同","采购合同","王督政","2026-06-28 10:40","低风险","0","已通过"],
  ["CT202606012","品牌 VI 视觉设计外包合同","软件开发外包合同","曾庆豪","2026-06-27 15:55","中风险","2","待整改"],
  ["CT202606013","SAP ERP 实施与定制开发合同","软件开发外包合同","曾庆豪","2026-06-25 14:00","高风险","7","未通过"],
  ["CT202606014","快递物流合作框架协议（顺丰）","技术服务合同","陈嘉禾","2026-06-24 09:30","低风险","1","已通过"]
];

/* ---------- 工具函数 ---------- */
function showToast(message) {
  nodes.toast.textContent = message;
  nodes.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { nodes.toast.hidden = true; }, 2800);
}

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function downloadFile(filename, content, type) {
  const blob = new Blob(["﻿" + content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function levelLabel(lv) { return lv === "high" ? "高风险" : lv === "medium" ? "中风险" : "低风险"; }
function checkedDimensions() {
  return $$("[data-dimension]:checked").map((input) => input.dataset.dimension);
}
function visibleRisks() {
  const dims = checkedDimensions();
  if (!dims.length) return [];
  return risks.filter((risk) => dims.includes(risk.dimension) || risk.dimension === "risk");
}
function pendingRiskCount(list = visibleRisks()) {
  return list.filter((risk) => !["已确认", "已忽略"].includes(risk.status)).length;
}
function updateAuditSummary() {
  if (nodes.auditResult.hidden) return;
  const list = visibleRisks();
  nodes.riskCount.textContent = String(list.length);
  nodes.reviewCount.textContent = String(pendingRiskCount(list));
  if (state.currentId) {
    const item = state.queue.find((q) => q.id === state.currentId);
    if (item) {
      item.total = list.length;
      item.counts = {
        high: list.filter((risk) => risk.level === "high").length,
        mid: list.filter((risk) => risk.level === "medium").length,
        low: list.filter((risk) => risk.level === "low").length
      };
      renderQueue();
    }
  }
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]));
}

/* ---------- DOM 引用 ---------- */
const nodes = {
  toast: $("#toast"),
  // 角色
  userCard: $("#userCard"), userAvatar: $("#userAvatar"), userName: $("#userName"), userRole: $("#userRole"), roleMenu: $("#roleMenu"),
  // 工作台
  dashEyebrow: $("#dashEyebrow"), dashGreeting: $("#dashGreeting"), dashKpis: $("#dashKpis"),
  todoTitle: $("#todoTitle"), todoRole: $("#todoRole"), todoList: $("#todoList"), activityList: $("#activityList"),
  // 审查
  fileInput: $("#contractFile"), fileName: $("#fileName"), fileList: $("#fileList"), dropZone: $(".drop-zone"),
  loadSample: $("#loadSample"), runAudit: $("#runAudit"), resetDemo: $("#resetDemo"),
  queuePanel: $("#queuePanel"), queueList: $("#queueList"), queueSummary: $("#queueSummary"),
  emptyState: $("#emptyState"), auditResult: $("#auditResult"), currentContract: $("#currentContract"),
  openFulltext: $("#openFulltext"), exportReport: $("#exportReport"),
  auditStatus: $("#auditStatus"), riskCount: $("#riskCount"), reviewCount: $("#reviewCount"), accuracy: $("#accuracy"),
  runtimeStatus: $("#runtimeStatus"), collabStatus: $("#collabStatus"),
  laneLegal: $("#laneLegal"), laneFinance: $("#laneFinance"),
  riskList: $("#riskList"), metadataList: $("#metadataList"),
  // 报表
  lineChart: $("#lineChart"), donut: $("#donut"), donutTotal: $("#donutTotal"), donutLegend: $("#donutLegend"),
  departmentList: $("#departmentList"), topRiskList: $("#topRiskList"),
  // 知识库 / 历史
  knowledgeList: $("#knowledgeList"), historyTable: $("#historyTable"), historyCount: $("#historyCount"), pagination: $("#pagination"),
  // 抽屉 / 模态
  drawer: $("#riskDrawer"), drawerMask: $("#drawerMask"), drawerTitle: $("#drawerTitle"), drawerBody: $("#drawerBody"),
  fulltextMask: $("#fulltextMask"), fulltextTitle: $("#fulltextTitle"), fulltextDoc: $("#fulltextDoc"),
  annList: $("#annList"), annCount: $("#annCount")
  ,
  // 知识入库
  knowledgeMask: $("#knowledgeMask"), knowledgeForm: $("#knowledgeForm"), knowledgeClose: $("#knowledgeClose"), knowledgeCancel: $("#knowledgeCancel"),
  knowledgeTitle: $("#knowledgeTitle"), knowledgeTag: $("#knowledgeTag"), knowledgeDesc: $("#knowledgeDesc"), knowledgeChips: $("#knowledgeChips"),
  // 历史详情
  historyMask: $("#historyMask"), historyClose: $("#historyClose"), historyDetailTitle: $("#historyDetailTitle"), historyDetailBody: $("#historyDetailBody"),
  // 通知
  notifyBtn: $("#notifyBtn"), notifyDot: $("#notifyDot"), notifyPanel: $("#notifyPanel"), notifyList: $("#notifyList"), notifyReadAll: $("#notifyReadAll"),
  // 整改跟踪
  navRectifyCount: $("#navRectifyCount"), rectifyKpis: $("#rectifyKpis"), rectifyList: $("#rectifyList"), rectifySummary: $("#rectifySummary"), exportRectify: $("#exportRectify"),
  // 批量报告
  openBatchReport: $("#openBatchReport"), batchMask: $("#batchMask"), batchBody: $("#batchBody"), batchClose: $("#batchClose"), exportBatch: $("#exportBatch"),
  // 版本比对
  openCompare: $("#openCompare"), compareMask: $("#compareMask"), compareTitle: $("#compareTitle"), compareToolbar: $("#compareToolbar"), compareDoc: $("#compareDoc"), compareClose: $("#compareClose"),
  // 报表钻取
  drillType: $("#drillType"), drillAmount: $("#drillAmount"), drillLevel: $("#drillLevel"), drillReset: $("#drillReset"), drillHint: $("#drillHint"),
  // 规则与模板
  ruleList: $("#ruleList"), ruleSummary: $("#ruleSummary"), templateList: $("#templateList"), templateSummary: $("#templateSummary"),
  addRule: $("#addRule"), addTemplate: $("#addTemplate"),
  ruleMask: $("#ruleMask"), ruleForm: $("#ruleForm"), ruleModalTitle: $("#ruleModalTitle"), ruleClose: $("#ruleClose"), ruleCancel: $("#ruleCancel"),
  ruleName: $("#ruleName"), ruleDimension: $("#ruleDimension"), ruleLevel: $("#ruleLevel"), ruleAgent: $("#ruleAgent"), ruleDesc: $("#ruleDesc"),
  templateMask: $("#templateMask"), templateForm: $("#templateForm"), templateModalTitle: $("#templateModalTitle"), templateClose: $("#templateClose"), templateCancel: $("#templateCancel"),
  templateName: $("#templateName"), templateType: $("#templateType"), templateClauses: $("#templateClauses"),
  // 权限与审计
  accessTable: $("#accessTable"), auditLogList: $("#auditLogList"), auditSearch: $("#auditSearch"), exportAudit: $("#exportAudit")
};

/* ---------- 视图切换 ---------- */
function switchView(view) {
  state.activeView = view;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach((section) => section.classList.toggle("active", section.id === `view-${view}`));
  if (view === "rectify") renderRectify();
  if (view === "rules") renderRules();
  if (view === "admin") renderAdmin();
  if (view === "reports") renderReports();
}

/* ---------- 角色切换 ---------- */
function applyRole(roleKey) {
  state.role = roleKey;
  const r = roles[roleKey];
  nodes.userName.textContent = r.name;
  nodes.userRole.textContent = r.role;
  nodes.userAvatar.textContent = r.avatar;
  renderDashboard();
  showToast(`已切换到「${r.name} · ${r.role}」视角。`);
}

function renderDashboard() {
  const r = roles[state.role];
  const hour = 14; // 演示固定“下午好”
  const greet = hour < 12 ? "上午好" : hour < 18 ? "下午好" : "晚上好";
  const activeRiskRows = risks.filter((risk) => risk.status !== "已忽略");
  const pendingLegal = activeRiskRows.filter((risk) => risk.agent === "legal" && risk.status !== "已确认").length;
  const pendingFinance = activeRiskRows.filter((risk) => risk.agent === "finance" && risk.status !== "已确认").length;
  const highRiskCount = activeRiskRows.filter((risk) => risk.level === "high").length;
  const dynamicKpis = {
    legal: [["待我复核", String(pendingLegal), "seal"], ["本月已审", "148", "brass"], ["高风险条款", String(highRiskCount), "seal"], ["合规通过率", "87%", "sage"]],
    finance: [["待对账合同", String(pendingFinance), "amber"], ["涉及金额", "¥ 2,860万", "brass"], ["付款风险项", String(pendingFinance), "seal"], ["预算偏差", "-3.2%", "sage"]],
    admin: dashKpiByRole.admin
  };
  nodes.dashEyebrow.textContent = r.eyebrow;
  nodes.dashGreeting.textContent = `${greet}，${r.name}`;
  nodes.todoRole.textContent = r.todoView;

  nodes.dashKpis.innerHTML = dynamicKpis[state.role]
    .map(([label, val, tone]) => `
      <article class="dash-kpi tone-${tone}">
        <span>${label}</span><strong>${val}</strong>
      </article>`).join("");

  nodes.todoList.innerHTML = todoByRole[state.role]
    .map((t) => `
      <div class="todo-item lv-${t.lv}">
        <div class="todo-main">
          <strong>${t.c}</strong>
          <span>${t.t}</span>
        </div>
        <div class="todo-meta">
          <i class="risk-badge ${t.lv}">${levelLabel(t.lv)}</i>
          <small>${t.time}</small>
        </div>
      </div>`).join("");

  nodes.activityList.innerHTML = activityFeed
    .map((a) => `
      <div class="activity-item">
        <span class="role-dot ${a.dot}"></span>
        <div><b>${a.who}</b> ${a.what}<small>${a.time}</small></div>
      </div>`).join("");
}

/* ---------- 文件上传 ---------- */
function addFiles(fileArr) {
  fileArr.forEach((f) => {
    if (state.files.some((x) => x.name === f.name && x.size === f.size)) return;
    // 真实上传：超大文件（>20MB）或非法扩展名标记为异常，演示容错
    const okExt = /\.(pdf|docx?|txt)$/i.test(f.name);
    const tooBig = f.size > 20 * 1024 * 1024;
    const entry = { name: f.name, size: f.size };
    if (!okExt) { entry.bad = true; entry.failReason = "不支持的文件格式"; }
    else if (tooBig) { entry.bad = true; entry.failReason = "文件超过 20MB 上限"; }
    state.files.push(entry);
  });
  renderFileList();
}

function loadSampleFiles() {
  contractTemplates.forEach((t, i) => {
    if (!state.files.some((x) => x.name === `${t.name}.pdf`)) {
      state.files.push({ name: `${t.name}.pdf`, size: 420000 + i * 63000 });
    }
  });
  // 追加一份异常样例，用于演示解析失败 / 格式不支持的容错处理
  if (!state.files.some((x) => x.name === "加密扫描件_补充协议.pdf")) {
    state.files.push({ name: "加密扫描件_补充协议.pdf", size: 12800000, bad: true, failReason: "文件为加密扫描件，无法提取文本层" });
  }
  renderFileList();
  showToast(`已载入 ${contractTemplates.length + 1} 份示例合同（含 1 份异常样例），点击「启动批量审查」。`);
}

function renderFileList() {
  const count = state.files.length;
  nodes.fileName.textContent = count ? `已选择 ${count} 份合同` : "上传合同文件";
  nodes.runtimeStatus.textContent = count ? `类脑推理链路 · 待处理 ${count} 份` : "类脑推理链路 · 就绪";
  if (!count) { nodes.fileList.hidden = true; nodes.fileList.innerHTML = ""; return; }
  nodes.fileList.hidden = false;
  nodes.fileList.innerHTML = state.files
    .map((f, i) => `
      <div class="file-item ${f.bad ? "bad" : ""}">
        <svg class="ic sm"><use href="#${f.bad ? "i-alert" : "i-doc"}"/></svg>
        <span class="fname">${f.name}${f.bad ? `<em class="file-warn">${f.failReason}</em>` : ""}</span>
        <span class="fsize">${formatSize(f.size)}</span>
        <button class="fdel" type="button" data-del="${i}" title="移除"><svg class="ic sm"><use href="#i-close"/></svg></button>
      </div>`).join("");
  $$("[data-del]").forEach((btn) => btn.addEventListener("click", () => {
    state.files.splice(Number(btn.dataset.del), 1); renderFileList();
  }));
}

/* ---------- 批量审查队列 ---------- */
function startBatch() {
  if (!state.files.length) { showToast("请先上传合同文件或载入示例。"); return; }

  // 建立队列项：用模板补齐信息（文件名匹配不上就循环取模板）
  state.queue = state.files.map((f, i) => {
    const tpl = contractTemplates.find((t) => f.name.includes(t.name)) || contractTemplates[i % contractTemplates.length];
    return {
      id: `Q${i + 1}`,
      name: f.name.replace(/\.(pdf|docx?|txt)$/i, ""),
      type: tpl.type,
      counts: { high: tpl.high, mid: tpl.mid, low: tpl.low },
      total: tpl.high + tpl.mid + tpl.low,
      progress: 0,
      status: "queued", // queued -> parsing -> legal -> finance -> done | error
      willFail: !!f.bad,
      failReason: f.failReason || "解析失败"
    };
  });

  nodes.queuePanel.hidden = false;
  nodes.emptyState.hidden = true;
  nodes.auditResult.hidden = true;
  nodes.runAudit.disabled = true;
  nodes.openBatchReport.disabled = true;
  renderQueue();
  runQueueSequential(0);
}

const QUEUE_STAGES = [
  { key: "parsing", p: 25, label: "解析中" },
  { key: "legal", p: 55, label: "法务审查" },
  { key: "finance", p: 85, label: "财务对账" },
  { key: "done", p: 100, label: "已完成" }
];

function runQueueSequential(index) {
  // 异常态演示：文件名标记为损坏 / 空文件的合同在解析阶段失败
  if (index < state.queue.length) {
    const cur = state.queue[index];
    if (cur.willFail) {
      cur.status = "parsing"; cur.progress = 25; renderQueue();
      window.setTimeout(() => {
        cur.status = "error"; cur.progress = 100; cur.errorMsg = cur.failReason;
        renderQueue();
        pushNotify("alert", "合同解析失败", `《${cur.name}》${cur.failReason}，已跳过。`);
        window.setTimeout(() => runQueueSequential(index + 1), 240);
      }, 500);
      return;
    }
  }
  if (index >= state.queue.length) {
    nodes.runAudit.disabled = false;
    nodes.runtimeStatus.textContent = `类脑推理链路 · 完成 ${state.queue.length} 份`;
    nodes.openBatchReport.disabled = false;
    const highTotal = state.queue.reduce((s, q) => s + q.counts.high, 0);
    if (highTotal > 0) pushNotify("alert", "批量审查高风险预警", `本批 ${state.queue.length} 份合同共检出 ${highTotal} 项高风险条款，建议优先复核。`);
    pushAudit("批量审查完成", `${state.queue.length} 份合同`);
    showToast(`批量审查完成：${state.queue.length} 份合同已生成报告。`);
    // 自动展示第一份
    if (state.queue[0]) openContract(state.queue[0].id);
    return;
  }
  const item = state.queue[index];
  let stageIdx = 0;
  const tick = () => {
    const stage = QUEUE_STAGES[stageIdx];
    item.status = stage.key;
    item.progress = stage.p;
    renderQueue();
    stageIdx++;
    if (stageIdx <= QUEUE_STAGES.length - 1) {
      window.setTimeout(tick, 360);
    } else {
      window.setTimeout(() => runQueueSequential(index + 1), 240);
    }
  };
  tick();
}

function renderQueue() {
  const done = state.queue.filter((q) => q.status === "done").length;
  const failed = state.queue.filter((q) => q.status === "error").length;
  nodes.queueSummary.textContent = failed
    ? `${done} / ${state.queue.length} 完成 · ${failed} 失败`
    : `${done} / ${state.queue.length} 完成`;
  nodes.queueList.innerHTML = state.queue
    .map((q) => {
      const stage = QUEUE_STAGES.find((s) => s.key === q.status);
      const stageLabel = q.status === "queued" ? "排队中" : stage ? stage.label : "";
      const isDone = q.status === "done";
      const isError = q.status === "error";
      const active = q.id === state.currentId ? "active" : "";
      return `
        <button class="queue-item ${active} ${isError ? "error" : ""}" type="button" data-qid="${q.id}" ${isDone ? "" : "disabled"}>
          <div class="q-top">
            <span class="q-name"><svg class="ic sm"><use href="#${isError ? "i-alert" : "i-doc"}"/></svg>${q.name}</span>
            ${isDone
              ? `<span class="q-risks">
                   ${q.counts.high ? `<i class="risk-badge high">${q.counts.high} 高</i>` : ""}
                   ${q.counts.mid ? `<i class="risk-badge medium">${q.counts.mid} 中</i>` : ""}
                   ${q.counts.low ? `<i class="risk-badge low">${q.counts.low} 低</i>` : ""}
                 </span>`
              : isError
                ? `<span class="q-stage err">解析失败</span>`
                : `<span class="q-stage">${stageLabel}</span>`}
          </div>
          ${isError
            ? `<div class="q-error">${escapeHtml(q.errorMsg || "解析失败")}，已跳过并计入异常</div>`
            : `<div class="q-bar"><i style="width:${q.progress}%"></i></div>`}
        </button>`;
    }).join("");
  $$("[data-qid]").forEach((btn) => btn.addEventListener("click", () => openContract(btn.dataset.qid)));
}

/* ---------- 打开某份合同详情 ---------- */
function openContract(qid) {
  const item = state.queue.find((q) => q.id === qid);
  if (!item || item.status !== "done") return;
  state.currentId = qid;
  renderQueue();

  nodes.auditResult.hidden = false;
  nodes.currentContract.textContent = item.name;
  nodes.auditStatus.textContent = "已完成";
  nodes.accuracy.textContent = "92.4%";

  renderCollab();
  renderMetadata();
  renderRisks();
  updateAuditSummary();
  nodes.exportReport.disabled = false;
}

/* ---------- 多智能体协同时间线 ---------- */
const collabSteps = {
  legal: [
    { t: "接收解析后的合同文本", s: "done" },
    { t: "检索《民法典》与企业规则库", s: "done" },
    { t: "比对违约 / 验收 / 保密条款", s: "done" },
    { t: "标注 3 项合规风险 →", s: "done", handoff: true }
  ],
  finance: [
    { t: "← 接收法务标注与金额要素", s: "done" },
    { t: "校验付款节点与发票规则", s: "done" },
    { t: "联动预算库核算偏差", s: "done" },
    { t: "汇总生成协同审查报告", s: "done" }
  ]
};

function renderCollab() {
  nodes.collabStatus.textContent = "协同完成";
  const build = (steps) => steps.map((st, i) => `
    <div class="collab-step ${st.s} ${st.handoff ? "handoff" : ""}" style="animation-delay:${i * 90}ms">
      <span class="cs-dot"></span>
      <span class="cs-text">${st.t}</span>
    </div>`).join("");
  nodes.laneLegal.innerHTML = build(collabSteps.legal);
  nodes.laneFinance.innerHTML = build(collabSteps.finance);
}

function renderMetadata() {
  nodes.metadataList.innerHTML = Object.entries(metadata)
    .map(([key, v]) => `<div><dt>${key}</dt><dd class="${v.warn ? "warn" : ""}">${v.value}</dd></div>`).join("");
}

function renderRisks() {
  const list = visibleRisks();
  if (!list.length) {
    nodes.riskList.innerHTML = `
      <div class="risk-empty">
        <strong>当前审查维度未命中风险</strong>
        <span>请至少勾选一个审查维度，或在知识库中补充对应规则后重新审查。</span>
      </div>`;
    updateAuditSummary();
    return;
  }
  nodes.riskList.innerHTML = list.map((risk) => {
    const index = risks.indexOf(risk);
    const agentTag = risk.agent === "finance" ? "财务 Agent" : "法务 Agent";
    const statusClass = risk.status === "已确认" ? "confirmed" : risk.status === "已忽略" ? "ignored" : "";
    return `
      <article class="risk-card ${risk.level} ${statusClass}" style="animation-delay:${index * 80}ms">
        <button class="risk-toggle" type="button" data-risk="${index}">
          <span>
            <strong>${risk.title}</strong>
            <em>${risk.type} · ${agentTag} · ${risk.status}</em>
          </span>
          <i class="risk-badge ${risk.level}">${risk.label}</i>
        </button>
        <div class="risk-detail" ${index === 0 ? "" : "hidden"}>
          <p><b>命中原文：</b></p>
          <p class="clause-quote">${risk.clause}</p>
          <p><b>依据来源：</b>${risk.basis}</p>
          <p><b>问题说明：</b>${risk.description}</p>
          <p><b>修改建议：</b>${risk.suggestion}</p>
          ${risk.auditTrail ? `<p><b>复核记录：</b>${risk.auditTrail}</p>` : ""}
          <div class="detail-actions">
            <button class="ghost-button compact" type="button" data-review="${index}">${risk.status === "已确认" ? "查看复核" : "进入复核"}</button>
          </div>
        </div>
      </article>`;
  }).join("");
  $$(".risk-toggle").forEach((button) => button.addEventListener("click", () => {
    const detail = button.parentElement.querySelector(".risk-detail");
    detail.hidden = !detail.hidden;
  }));
  $$("[data-review]").forEach((btn) => btn.addEventListener("click", () => openDrawer(Number(btn.dataset.review))));
  updateAuditSummary();
}

function resetDemo() {
  nodes.fileInput.value = "";
  state.files = []; state.queue = []; state.currentId = null;
  risks.forEach((risk) => { risk.status = risk.initialStatus; delete risk.auditTrail; });
  renderFileList();
  nodes.queuePanel.hidden = true;
  nodes.emptyState.hidden = false;
  nodes.auditResult.hidden = true;
  nodes.exportReport.disabled = true;
  nodes.openBatchReport.disabled = true;
  nodes.runAudit.disabled = false;
  nodes.runtimeStatus.textContent = "类脑推理链路 · 就绪";
  showToast("演示已重置。");
}

function exportAuditReport() {
  const header = ["风险标题", "风险等级", "审查维度", "风险类型", "负责 Agent", "状态", "命中原文", "依据来源", "修改建议"];
  const lines = visibleRisks().map((r) =>
    [r.title, r.label, r.dimension, r.type, r.agent === "finance" ? "财务 Agent" : "法务 Agent", r.status, r.clause, r.basis, r.suggestion]
      .map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","));
  downloadFile("合同合规审查报告.csv", [header.join(","), ...lines].join("\n"), "text/csv;charset=utf-8");
  showToast("已导出《合同合规审查报告》风险台账（CSV）。");
}

/* ---------- 复核抽屉 ---------- */
function openDrawer(index) {
  const r = risks[index];
  nodes.drawerTitle.textContent = r.title;
  nodes.drawerBody.innerHTML = `
    <div class="drawer-badge-row">
      <span class="risk-badge ${r.level}">${r.label}</span>
      <span class="tag">${r.type}</span>
      <span class="tag status-tag">${r.status}</span>
    </div>
    <div class="drawer-field"><div class="df-label">命中原文</div><div class="df-value quote">${r.clause}</div></div>
    <div class="drawer-field"><div class="df-label">依据来源</div><div class="df-value">${r.basis}</div></div>
    <div class="drawer-field"><div class="df-label">问题说明</div><div class="df-value">${r.description}</div></div>
    <div class="drawer-field"><div class="df-label">修改建议</div><div class="df-value"><b>${r.suggestion}</b></div></div>
    <div class="drawer-field"><div class="df-label">建议责任人</div><div class="df-value">${r.owner}</div></div>
    ${r.auditTrail ? `<div class="drawer-field"><div class="df-label">复核记录</div><div class="df-value">${r.auditTrail}</div></div>` : ""}`;
  nodes.drawer.hidden = false;
  nodes.drawerMask.hidden = false;
  nodes.drawer.dataset.current = index;
}
function closeDrawer() { nodes.drawer.hidden = true; nodes.drawerMask.hidden = true; }
function applyRiskDecision(decision) {
  const index = Number(nodes.drawer.dataset.current);
  const risk = risks[index];
  if (!risk) return;
  const operator = roles[state.role].name;
  if (decision === "confirm") {
    risk.status = "已确认";
    risk.auditTrail = `${operator} 已确认风险，并生成整改项给 ${risk.owner}。`;
    state.lastRiskAction = risk.title;
    // 生成整改项并入跟踪列表
    const contractName = state.currentId
      ? (state.queue.find((q) => q.id === state.currentId)?.name || "当前合同")
      : "当前合同";
    if (!rectifications.some((rc) => rc.risk === risk.title && rc.contract === contractName)) {
      rectifications.unshift({
        id: `RC${++rectifyId}`, contract: contractName, risk: risk.title, level: risk.level,
        owner: risk.owner, status: "待处理", created: "2026-07-07", due: "2026-07-14",
        note: `${operator} 确认后生成，建议：${risk.suggestion}`
      });
    }
    pushAudit("确认风险并生成整改项", `${contractName} · ${risk.title}`);
    pushNotify("rectify", "新整改项待处理", `${contractName}「${risk.title}」已生成整改项，负责人：${risk.owner}。`);
    updateRectifyBadge();
    showToast(`已确认「${risk.title}」，整改项已生成并进入整改跟踪。`);
  } else {
    risk.status = "已忽略";
    risk.auditTrail = `${operator} 标记为误报，后续回流优化规则库。`;
    state.lastRiskAction = risk.title;
    pushAudit("标记风险为误报", `${risk.title}`);
    showToast(`已将「${risk.title}」标记为误报。`);
  }
  closeDrawer();
  renderRisks();
  renderDashboard();
}

/* ---------- 合同全文批注视图 ---------- */
function openFulltext() {
  if (!state.currentId) { showToast("请先在队列中选择一份已完成的合同。"); return; }
  const item = state.queue.find((q) => q.id === state.currentId);
  nodes.fulltextTitle.textContent = item ? item.name : "合同全文";

  // 渲染正文，把 {{n}} 占位替换成可定位的风险标注 span
  nodes.fulltextDoc.innerHTML = contractFulltext.map((sec) => {
    const body = sec.p.replace(/\{\{(\d+)\}\}/g, (_, n) => {
      const r = risks[Number(n)];
      if (!r) return "";
      return `<mark class="ann-mark ${r.level}" id="mark-${n}" data-mark="${n}"></mark>`;
    });
    // 让被标注的整句带下划：将紧跟标注后的句子包起来
    return `<section class="ft-sec"><h4>${sec.h}</h4><p>${wrapAnnotated(body)}</p></section>`;
  }).join("");

  // 右侧批注列表
  nodes.annCount.textContent = String(risks.length);
  nodes.annList.innerHTML = risks.map((r, i) => `
    <button class="ann-item ${r.level}" type="button" data-ann="${i}">
      <div class="ann-top"><i class="risk-badge ${r.level}">${r.label}</i><small>${r.agent === "finance" ? "财务" : "法务"} Agent</small></div>
      <strong>${r.title}</strong>
      <span>${r.suggestion}</span>
    </button>`).join("");

  $$("[data-ann]").forEach((btn) => btn.addEventListener("click", () => {
    const i = btn.dataset.ann;
    const mark = document.getElementById(`mark-${i}`);
    if (mark) {
      mark.scrollIntoView({ behavior: "smooth", block: "center" });
      mark.classList.add("flash");
      window.setTimeout(() => mark.classList.remove("flash"), 1400);
    } else {
      showToast("该风险属于扩展维度，当前示例合同未配置全文锚点。");
    }
    $$(".ann-item").forEach((x) => x.classList.toggle("active", x === btn));
  }));

  nodes.fulltextMask.hidden = false;
  document.body.style.overflow = "hidden";
}
// 把含标注锚点的句子用波浪下划线包裹
function wrapAnnotated(html) {
  return html.replace(/(<mark[^>]*><\/mark>)([^。]*。)/g, '$1<span class="ann-sentence">$2</span>');
}
function closeFulltext() { nodes.fulltextMask.hidden = true; document.body.style.overflow = ""; }

/* ---------- 报表 ---------- */
function renderLineChart() {
  const d = reportData[state.range].trend;
  const W = 720, H = 260, padL = 40, padR = 20, padT = 20, padB = 30;
  const labels = ["一","二","三","四","五","六","七"];
  const niceMax = Math.ceil(Math.max(...d.total) / 200) * 200;
  const x = (i) => padL + (i * (W - padL - padR)) / (labels.length - 1);
  const y = (v) => padT + (1 - v / niceMax) * (H - padT - padB);
  const gridLines = [0,0.25,0.5,0.75,1].map((t) => {
    const gy = padT + t * (H - padT - padB);
    return `<line class="grid-line" x1="${padL}" y1="${gy}" x2="${W-padR}" y2="${gy}"/><text class="axis-label" x="${padL-8}" y="${gy+4}" text-anchor="end">${Math.round(niceMax*(1-t))}</text>`;
  }).join("");
  const xLabels = labels.map((l,i) => `<text class="axis-label" x="${x(i)}" y="${H-8}" text-anchor="middle">${l}月</text>`).join("");
  const series = [
    { data: d.total, color: "#b8912f", fill: "rgba(184,145,47,0.14)" },
    { data: d.pass, color: "#3e7a5c", fill: "rgba(62,122,92,0.12)" },
    { data: d.risk, color: "#b23a2c", fill: "none" }
  ];
  const paths = series.map((s, si) => {
    const pts = s.data.map((v,i) => `${x(i)},${y(v)}`).join(" ");
    const area = s.fill === "none" ? "" : `<polygon class="area" points="${padL},${H-padB} ${pts} ${W-padR},${H-padB}" fill="${s.fill}"/>`;
    const dots = s.data.map((v,i) => `<circle class="pt" cx="${x(i)}" cy="${y(v)}" r="3.5" fill="${s.color}"><title>${v}</title></circle>`).join("");
    return `${area}<polyline class="series" points="${pts}" stroke="${s.color}" style="animation-delay:${si*0.2}s"/>${dots}`;
  }).join("");
  nodes.lineChart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="合同审查趋势">${gridLines}${xLabels}${paths}</svg>`;
}

function renderDonut() {
  const seg = reportData[state.range].donut;
  let acc = 0;
  const stops = donutMeta.map((m,i) => { const s = acc; acc += seg[i]; return `${m.color} ${s}% ${acc}%`; }).join(", ");
  nodes.donut.style.background = `conic-gradient(${stops})`;
  nodes.donutTotal.textContent = reportData[state.range].kpi.total;
  nodes.donutLegend.innerHTML = donutMeta.map((m,i) => `<span><i class="${m.cls}"></i>${m.key}<b>${seg[i]}%</b></span>`).join("");
}

function animateBars() { requestAnimationFrame(() => $$(".bar-fill").forEach((el) => { el.style.width = `${el.dataset.w}%`; })); }

function renderDepartments() {
  const list = reportData[state.range].depts;
  const max = Math.max(...list.map((d) => d.risk));
  nodes.departmentList.innerHTML = list.map((item) => `
    <div class="department-item">
      <div><span class="dep-name">${item.name}</span><span class="dep-money">${item.money} 合同额</span></div>
      <div class="bar-track"><i class="bar-fill" data-w="${Math.round((item.risk/max)*100)}"></i></div>
      <b>${item.risk}</b>
    </div>`).join("");
  animateBars();
}

function renderTopRisks() {
  const list = reportData[state.range].tops;
  const max = Math.max(...list.map((t) => t[1]));
  nodes.topRiskList.innerHTML = list.map(([name, value]) => `
    <div class="top-risk-row">
      <span>${name}</span>
      <div class="bar-track"><i class="bar-fill" data-w="${Math.round((value/max)*100)}"></i></div>
      <b>${value}</b>
    </div>`).join("");
  animateBars();
}

function scaleNum(str, factor) {
  // 把 "1,286" / "87.3%" / "4.2min" 按 factor 缩放（百分比与耗时不缩放）
  if (factor === 1) return str;
  if (/[%]|min/.test(str)) return str;
  const n = Number(String(str).replace(/,/g, ""));
  if (!isFinite(n)) return str;
  return Math.round(n * factor).toLocaleString("en-US");
}
function renderKpi(factor = 1) {
  const k = reportData[state.range].kpi;
  $("#kpiTotal").textContent = scaleNum(k.total, factor); $("#kpiPass").textContent = k.pass;
  $("#kpiRisk").textContent = scaleNum(k.risk, factor); $("#kpiTime").textContent = k.time;
}

function renderReports(factor = 1) { renderKpi(factor); renderLineChart(); renderDonut(); renderDepartments(); renderTopRisks(); }

/* ---------- 知识库 ---------- */
function renderKnowledge() {
  const kw = state.knowledgeKeyword.toLowerCase();
  const cards = knowledgeCards.filter((c) => {
    const matchCat = state.knowledgeCat === "全部" || c.tag === state.knowledgeCat;
    const matchKw = !kw || `${c.title}${c.desc}${c.chips.join("")}`.toLowerCase().includes(kw);
    return matchCat && matchKw;
  });
  renderKnowledgeStats();
  if (!cards.length) { nodes.knowledgeList.innerHTML = `<div class="knowledge-empty">未找到匹配的知识条目，试试其它关键词或分类。</div>`; return; }
  nodes.knowledgeList.innerHTML = cards.map((card, i) => {
    const index = knowledgeCards.indexOf(card);
    return `
    <article class="knowledge-card" style="animation-delay:${i*60}ms">
      <div class="kc-head"><h2>${card.title}</h2><span class="tag">${card.tag}</span></div>
      <p>${card.desc}</p>
      <div class="chips">${card.chips.map((chip) => `<span>${chip}</span>`).join("")}</div>
      <footer><small>更新于 ${card.date}</small><button type="button" data-knowledge="${index}">查看详情 →</button></footer>
    </article>`;
  }).join("");
  $$("[data-knowledge]").forEach((b) => b.addEventListener("click", () => openKnowledgeDetail(Number(b.dataset.knowledge))));
}
function renderKnowledgeStats() {
  const stats = { 法律法规: 0, 标准条款: 0, 典型案例: 0, 风险规则: 0 };
  knowledgeCards.forEach((card) => { if (stats[card.tag] !== undefined) stats[card.tag] += 1; });
  $$(".knowledge-stats article").forEach((item) => {
    const label = item.querySelector("span")?.textContent;
    const value = item.querySelector("strong");
    if (value && stats[label] !== undefined) value.textContent = String(stats[label]);
  });
}
function openKnowledgeModal() {
  nodes.knowledgeMask.hidden = false;
  document.body.style.overflow = "hidden";
  nodes.knowledgeTitle.focus();
}
function closeKnowledgeModal() {
  nodes.knowledgeMask.hidden = true;
  document.body.style.overflow = "";
}
function addKnowledgeItem() {
  const title = nodes.knowledgeTitle.value.trim();
  const tag = nodes.knowledgeTag.value;
  const desc = nodes.knowledgeDesc.value.trim();
  const chips = nodes.knowledgeChips.value.split(/[,，]/).map((chip) => chip.trim()).filter(Boolean);
  if (!title || !desc) {
    showToast("请补全知识标题和内容摘要。");
    return;
  }
  knowledgeCards.unshift({ title, tag, desc, chips: chips.length ? chips : [tag], date: "2026-07-07" });
  state.knowledgeCat = "全部";
  state.knowledgeKeyword = "";
  $("#knowledgeSearch").value = "";
  $$("#knowledgeFilter button").forEach((b) => b.classList.toggle("active", b.dataset.cat === "全部"));
  closeKnowledgeModal();
  renderKnowledge();
  showToast("新审查依据已入库，并可被 RAG 检索。");
}
function openKnowledgeDetail(index) {
  const card = knowledgeCards[index];
  if (!card) return;
  nodes.historyDetailTitle.textContent = card.title;
  nodes.historyDetailBody.innerHTML = `
    <div class="drawer-badge-row"><span class="tag">${card.tag}</span>${card.chips.map((chip) => `<span class="tag">${chip}</span>`).join("")}</div>
    <div class="drawer-field"><div class="df-label">依据摘要</div><div class="df-value">${card.desc}</div></div>
    <div class="drawer-field"><div class="df-label">建议用途</div><div class="df-value">用于合同审查时的风险解释、条款对照和修改建议生成。</div></div>
    <div class="drawer-field"><div class="df-label">推荐标准条款</div><div class="df-value quote">${recommendClause(card)}</div></div>
    <div class="drawer-field"><div class="df-label">更新时间</div><div class="df-value">${card.date}</div></div>
    <footer class="modal-actions"><button class="ghost-button" type="button" id="copyClause">复制标准条款</button><button class="primary-button" type="button" id="applyClause">应用为合同建议</button></footer>`;
  nodes.historyMask.hidden = false;
  document.body.style.overflow = "hidden";
  const clauseText = recommendClause(card);
  $("#copyClause")?.addEventListener("click", () => {
    if (navigator.clipboard) navigator.clipboard.writeText(clauseText).catch(() => {});
    showToast("标准条款已复制，可粘贴到合同修订稿。");
  });
  $("#applyClause")?.addEventListener("click", () => {
    pushAudit("应用知识库条款推荐", card.title);
    showToast(`已将「${card.title}」推荐为合同修改建议。`);
    closeHistoryModal();
  });
}
// 依据知识卡片生成一条可套用的标准条款文本（条款推荐）
function recommendClause(card) {
  return `参照《${card.title.replace(/^《|》.*$/g, "")}》：${card.desc}建议在合同中据此补充或修订对应条款，明确权利义务边界。`;
}

/* ---------- 历史 ---------- */
function filteredHistory() {
  const kw = state.historyKeyword.toLowerCase();
  return historyRows.filter((row) => {
    const matchKw = !kw || `${row[0]}${row[1]}`.toLowerCase().includes(kw);
    const matchLevel = state.historyLevel === "全部" || row[5] === state.historyLevel;
    return matchKw && matchLevel;
  });
}
function riskLevelClass(v) { return v === "高风险" ? "risk-badge high" : v === "中风险" ? "risk-badge medium" : "risk-badge low"; }
function statusClass(v) { return v === "未通过" ? "status-text danger" : v === "待整改" ? "status-text warn" : "status-text ok"; }

function renderHistory() {
  const rows = filteredHistory();
  nodes.historyCount.textContent = String(rows.length);
  const totalPages = Math.max(1, Math.ceil(rows.length / state.pageSize));
  if (state.historyPage > totalPages) state.historyPage = totalPages;
  const start = (state.historyPage - 1) * state.pageSize;
  const pageRows = rows.slice(start, start + state.pageSize);
  const head = `<div class="history-row table-head"><span>合同编号</span><span>合同名称</span><span>合同类型</span><span>提交人</span><span>审查时间</span><span>风险等级</span><span>风险条款</span><span>合规状态</span><span>操作</span></div>`;
  const body = pageRows.length
    ? pageRows.map((row) => {
        const index = historyRows.indexOf(row);
        return `
        <div class="history-row">
          <span>${row[0]}</span><span class="cname">${row[1]}</span><span>${row[2]}</span><span>${row[3]}</span><span>${row[4]}</span>
          <span><i class="${riskLevelClass(row[5])}">${row[5]}</i></span><span>${row[6]}</span>
          <span class="${statusClass(row[7])}">${row[7]}</span>
          <span class="history-actions"><button type="button" data-history-view="${index}">查看</button><button type="button" data-history-download="${index}">下载</button></span>
        </div>`;
      }).join("")
    : `<div class="history-empty">未找到匹配的审查记录。</div>`;
  nodes.historyTable.innerHTML = head + body;
  $$("[data-history-view]").forEach((b) => b.addEventListener("click", () => openHistoryDetail(Number(b.dataset.historyView))));
  $$("[data-history-download]").forEach((b) => b.addEventListener("click", () => exportHistoryRecord(Number(b.dataset.historyDownload))));
  renderPagination(totalPages);
}
function renderPagination(totalPages) {
  const p = state.historyPage;
  let html = `<button type="button" data-page="${p-1}" ${p===1?"disabled":""}>‹</button>`;
  for (let i = 1; i <= totalPages; i++) html += `<button type="button" data-page="${i}" class="${i===p?"active":""}">${i}</button>`;
  html += `<button type="button" data-page="${p+1}" ${p===totalPages?"disabled":""}>›</button>`;
  nodes.pagination.innerHTML = html;
  $$("#pagination button[data-page]").forEach((b) => b.addEventListener("click", () => {
    const target = Number(b.dataset.page);
    if (target < 1 || target > totalPages) return;
    state.historyPage = target; renderHistory();
  }));
}

function exportBoard() {
  const k = reportData[state.range].kpi;
  const rangeLabel = { month: "本月", quarter: "本季度", year: "本年" }[state.range];
  const lines = [["统计周期",rangeLabel],["审查合同总数",k.total],["合规通过率",k.pass],["高风险条款",k.risk],["平均审查耗时",k.time]]
    .map((r) => r.map((c) => `"${c}"`).join(","));
  downloadFile(`多维数据报表_${rangeLabel}.csv`, [["指标","数值"].join(","), ...lines].join("\n"), "text/csv;charset=utf-8");
  showToast(`已导出${rangeLabel}多维数据报表（CSV）。`);
}
function closeHistoryModal() {
  nodes.historyMask.hidden = true;
  document.body.style.overflow = "";
}
function openHistoryDetail(index) {
  const row = historyRows[index];
  if (!row) return;
  nodes.historyDetailTitle.textContent = row[1];
  const relatedRisks = risks.slice(0, Math.max(1, Math.min(Number(row[6]) || 1, 4)));
  nodes.historyDetailBody.innerHTML = `
    <div class="detail-grid">
      <div><span>合同编号</span><strong>${row[0]}</strong></div>
      <div><span>合同类型</span><strong>${row[2]}</strong></div>
      <div><span>提交人</span><strong>${row[3]}</strong></div>
      <div><span>审查时间</span><strong>${row[4]}</strong></div>
      <div><span>风险等级</span><strong>${row[5]}</strong></div>
      <div><span>合规状态</span><strong>${row[7]}</strong></div>
    </div>
    <div class="drawer-field"><div class="df-label">风险摘要</div><div class="df-value">${relatedRisks.map((risk) => `【${risk.label}】${risk.title}`).join("<br>")}</div></div>
    <div class="drawer-field"><div class="df-label">处理建议</div><div class="df-value">优先复核高风险条款，确认后生成整改项；低风险条款进入模板优化池。</div></div>
    <footer class="modal-actions"><button class="ghost-button" type="button" data-export-history="${index}">导出本记录</button></footer>`;
  nodes.historyMask.hidden = false;
  document.body.style.overflow = "hidden";
  $("[data-export-history]")?.addEventListener("click", () => exportHistoryRecord(index));
}
function exportHistoryRecord(index) {
  const row = historyRows[index];
  if (!row) return;
  const header = ["合同编号", "合同名称", "合同类型", "提交人", "审查时间", "风险等级", "风险条款数", "合规状态"];
  const line = row.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",");
  downloadFile(`${row[0]}_审查记录.csv`, [header.join(","), line].join("\n"), "text/csv;charset=utf-8");
  showToast(`已导出 ${row[0]} 审查记录。`);
}

/* ============================================================
   新增模块逻辑：整改跟踪 / 批量报告 / 版本比对 / 报表钻取
   规则模板 / 通知预警 / 权限审计
   ============================================================ */

/* ---------- 整改项跟踪 ---------- */
function updateRectifyBadge() {
  const open = rectifications.filter((rc) => rc.status !== "已闭环").length;
  if (open) { nodes.navRectifyCount.hidden = false; nodes.navRectifyCount.textContent = String(open); }
  else nodes.navRectifyCount.hidden = true;
}
function renderRectify() {
  const kpis = [
    ["整改项总数", String(rectifications.length), "brass"],
    ["待处理", String(rectifications.filter((r) => r.status === "待处理").length), "seal"],
    ["处理中", String(rectifications.filter((r) => r.status === "处理中").length), "amber"],
    ["已闭环", String(rectifications.filter((r) => r.status === "已闭环").length), "sage"]
  ];
  nodes.rectifyKpis.innerHTML = kpis.map(([label, val, tone]) => `
    <article class="dash-kpi tone-${tone}"><span>${label}</span><strong>${val}</strong></article>`).join("");

  const list = state.rectifyFilter === "全部"
    ? rectifications
    : rectifications.filter((r) => r.status === state.rectifyFilter);
  nodes.rectifySummary.textContent = `共 ${list.length} 项`;

  if (!list.length) {
    nodes.rectifyList.innerHTML = `<div class="risk-empty"><strong>暂无整改项</strong><span>在合同审查中确认风险后，会自动生成整改项进入此处跟踪。</span></div>`;
    return;
  }
  const stObj = { "待处理": "todo", "处理中": "doing", "已闭环": "done" };
  nodes.rectifyList.innerHTML = list.map((rc) => `
    <article class="rectify-item ${rc.level}" data-rc="${rc.id}">
      <div class="rc-main">
        <div class="rc-title">
          <i class="risk-badge ${rc.level}">${levelLabel(rc.level)}</i>
          <strong>${escapeHtml(rc.risk)}</strong>
        </div>
        <div class="rc-sub"><svg class="ic sm"><use href="#i-doc"/></svg>${escapeHtml(rc.contract)}</div>
        <p class="rc-note">${escapeHtml(rc.note)}</p>
      </div>
      <div class="rc-meta">
        <span class="rc-status st-${stObj[rc.status]}">${rc.status}</span>
        <small>负责人：${escapeHtml(rc.owner)}</small>
        <small>截止：${rc.due}</small>
      </div>
      <div class="rc-actions">
        ${rc.status !== "已闭环"
          ? `<button class="ghost-button compact" data-rc-advance="${rc.id}">${rc.status === "待处理" ? "开始处理" : "标记闭环"}</button>`
          : `<span class="rc-done-mark"><svg class="ic sm"><use href="#i-check"/></svg>已闭环</span>`}
      </div>
    </article>`).join("");
  $$("[data-rc-advance]").forEach((btn) => btn.addEventListener("click", () => advanceRectify(btn.dataset.rcAdvance)));
}
function advanceRectify(id) {
  const rc = rectifications.find((r) => r.id === id);
  if (!rc) return;
  const idx = RECTIFY_STATUS.indexOf(rc.status);
  if (idx < RECTIFY_STATUS.length - 1) {
    rc.status = RECTIFY_STATUS[idx + 1];
    pushAudit("推进整改项状态", `${rc.contract} · ${rc.risk} → ${rc.status}`);
    if (rc.status === "已闭环") pushNotify("rectify", "整改项已闭环", `${rc.contract}「${rc.risk}」整改完成并闭环。`);
    updateRectifyBadge();
    renderRectify();
    showToast(`整改项「${rc.risk}」已更新为「${rc.status}」。`);
  }
}
function exportRectify() {
  const header = ["整改编号", "合同", "风险项", "风险等级", "负责人", "状态", "创建日期", "截止日期", "整改说明"];
  const lines = rectifications.map((rc) =>
    [rc.id, rc.contract, rc.risk, levelLabel(rc.level), rc.owner, rc.status, rc.created, rc.due, rc.note]
      .map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","));
  downloadFile("整改项跟踪台账.csv", [header.join(","), ...lines].join("\n"), "text/csv;charset=utf-8");
  showToast("已导出《整改项跟踪台账》。");
}

/* ---------- 批量总览报告 ---------- */
function openBatchReport() {
  const done = state.queue.filter((q) => q.status === "done");
  if (!done.length) { showToast("请先完成批量审查。"); return; }
  const totalRisk = done.reduce((s, q) => s + q.total, 0);
  const highSum = done.reduce((s, q) => s + q.counts.high, 0);
  const midSum = done.reduce((s, q) => s + q.counts.mid, 0);
  const lowSum = done.reduce((s, q) => s + q.counts.low, 0);
  const highContracts = done.filter((q) => q.counts.high > 0).length;
  const ranked = [...done].sort((a, b) => (b.counts.high * 100 + b.counts.mid * 10 + b.counts.low) - (a.counts.high * 100 + a.counts.mid * 10 + a.counts.low));

  const kpiHtml = [
    ["合同份数", String(done.length), "brass"],
    ["风险总数", String(totalRisk), "seal"],
    ["高危合同", String(highContracts), "amber"],
    ["平均要素准确率", "92.4%", "sage"]
  ].map(([l, v, t]) => `<article class="dash-kpi tone-${t}"><span>${l}</span><strong>${v}</strong></article>`).join("");

  const maxRisk = Math.max(1, ...ranked.map((q) => q.total));
  const rankHtml = ranked.map((q, i) => `
    <div class="batch-rank-row">
      <span class="br-idx">${i + 1}</span>
      <span class="br-name">${escapeHtml(q.name)}</span>
      <div class="bar-track"><i class="bar-fill" style="width:${Math.round((q.total / maxRisk) * 100)}%"></i></div>
      <span class="br-badges">
        ${q.counts.high ? `<i class="risk-badge high">${q.counts.high}高</i>` : ""}
        ${q.counts.mid ? `<i class="risk-badge medium">${q.counts.mid}中</i>` : ""}
        ${q.counts.low ? `<i class="risk-badge low">${q.counts.low}低</i>` : ""}
      </span>
      <b>${q.total}</b>
    </div>`).join("");

  nodes.batchBody.innerHTML = `
    <section class="batch-kpis">${kpiHtml}</section>
    <section class="batch-dist">
      <div class="section-head"><h3>风险等级分布</h3></div>
      <div class="batch-dist-bars">
        <div class="bdist"><span>高风险</span><div class="bar-track"><i class="bar-fill seal" style="width:${pct(highSum, totalRisk)}%"></i></div><b>${highSum}</b></div>
        <div class="bdist"><span>中风险</span><div class="bar-track"><i class="bar-fill amber" style="width:${pct(midSum, totalRisk)}%"></i></div><b>${midSum}</b></div>
        <div class="bdist"><span>低风险</span><div class="bar-track"><i class="bar-fill sage" style="width:${pct(lowSum, totalRisk)}%"></i></div><b>${lowSum}</b></div>
      </div>
    </section>
    <section class="batch-rank">
      <div class="section-head"><h3>高危合同排序</h3><span class="badge-soft">按风险加权</span></div>
      <div class="batch-rank-list">${rankHtml}</div>
    </section>`;
  nodes.batchMask.hidden = false;
  document.body.style.overflow = "hidden";
}
function pct(v, total) { return total ? Math.round((v / total) * 100) : 0; }
function closeBatchReport() { nodes.batchMask.hidden = true; document.body.style.overflow = ""; }
function exportBatchReport() {
  const done = state.queue.filter((q) => q.status === "done");
  const header = ["序号", "合同名称", "合同类型", "高风险", "中风险", "低风险", "风险合计"];
  const lines = done.map((q, i) =>
    [i + 1, q.name, q.type, q.counts.high, q.counts.mid, q.counts.low, q.total]
      .map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","));
  downloadFile("批量审查汇总表.csv", [header.join(","), ...lines].join("\n"), "text/csv;charset=utf-8");
  showToast("已导出《批量审查汇总表》。");
}

/* ---------- 合同版本比对 ---------- */
function openCompare() {
  if (!state.currentId) { showToast("请先在队列中选择一份已完成的合同。"); return; }
  const item = state.queue.find((q) => q.id === state.currentId);
  nodes.compareTitle.textContent = `${item ? item.name : "合同"} · 版本比对`;
  const stats = { added: 0, changed: 0, same: 0 };
  contractRevised.forEach((s) => { stats[s.type] = (stats[s.type] || 0) + 1; });
  nodes.compareToolbar.innerHTML = `
    <span class="cmp-legend"><i class="cmp-dot changed"></i>修改 ${stats.changed}</span>
    <span class="cmp-legend"><i class="cmp-dot added"></i>新增 ${stats.added}</span>
    <span class="cmp-legend"><i class="cmp-dot same"></i>未变 ${stats.same}</span>
    <span class="cmp-note">左：原版 V1　·　右：修订版 V2（AI 已重新审查差异条款）</span>`;
  nodes.compareDoc.innerHTML = contractRevised.map((sec) => {
    if (sec.type === "same") {
      return `<div class="cmp-row same">
        <h4>${sec.h}</h4>
        <div class="cmp-cols"><div class="cmp-cell">${sec.p}</div><div class="cmp-cell">${sec.p}</div></div>
      </div>`;
    }
    if (sec.type === "added") {
      return `<div class="cmp-row added">
        <h4>${sec.h}<i class="cmp-tag added">新增条款</i></h4>
        <div class="cmp-cols"><div class="cmp-cell empty">— 原版无此条款 —</div><div class="cmp-cell ins">${sec.p}</div></div>
      </div>`;
    }
    return `<div class="cmp-row changed">
      <h4>${sec.h}<i class="cmp-tag changed">已修改</i></h4>
      <div class="cmp-cols"><div class="cmp-cell del">${sec.old}</div><div class="cmp-cell ins">${sec.p}</div></div>
    </div>`;
  }).join("");
  nodes.compareMask.hidden = false;
  document.body.style.overflow = "hidden";
}
function closeCompare() { nodes.compareMask.hidden = true; document.body.style.overflow = ""; }

/* ---------- 报表多维钻取 ---------- */
function applyDrill() {
  const { type, amount, level } = state.drill;
  const parts = [];
  if (type !== "全部") parts.push(type);
  if (amount !== "全部") parts.push({ low: "50万以下", mid: "50-200万", high: "200万以上" }[amount]);
  if (level !== "全部") parts.push(level);
  // 演示：钻取时对基础 KPI 施加一个确定性系数，模拟维度过滤后的子集统计
  const active = parts.length > 0;
  let factor = 1;
  if (type !== "全部") factor *= 0.42;
  if (amount === "high") factor *= 0.3; else if (amount === "mid") factor *= 0.45; else if (amount === "low") factor *= 0.55;
  if (level === "高风险") factor *= 0.28; else if (level === "中风险") factor *= 0.4; else if (level === "低风险") factor *= 0.5;
  nodes.drillHint.textContent = active
    ? `已按 ${parts.join(" / ")} 钻取，命中约 ${Math.round(100 * factor)}% 合同`
    : "";
  renderReports(active ? factor : 1);
}
function resetDrill() {
  state.drill = { type: "全部", amount: "全部", level: "全部" };
  nodes.drillType.value = "全部"; nodes.drillAmount.value = "全部"; nodes.drillLevel.value = "全部";
  nodes.drillHint.textContent = "";
  renderReports(1);
  showToast("已重置报表钻取维度。");
}

/* ---------- 规则与模板管理 ---------- */
const dimensionLabel = {
  legal: "法律条款合规性", risk: "风险条款识别", payment: "金额与付款条款", breach: "违约责任分析",
  ip: "知识产权条款", confidentiality: "保密条款审查", termination: "终止与解除条款", dispute: "争议解决条款"
};
function renderRules() {
  nodes.ruleSummary.textContent = `${auditRules.length} 条规则`;
  nodes.ruleList.innerHTML = auditRules.map((r) => `
    <article class="rule-item ${r.level}">
      <div class="rule-main">
        <div class="rule-title"><i class="risk-badge ${r.level}">${levelLabel(r.level)}</i><strong>${escapeHtml(r.name)}</strong></div>
        <p>${escapeHtml(r.desc)}</p>
        <div class="rule-tags"><span class="tag">${dimensionLabel[r.dimension] || r.dimension}</span><span class="tag">${r.agent === "finance" ? "财务 Agent" : "法务 Agent"}</span>${r.builtin ? `<span class="tag muted">内置</span>` : `<span class="tag muted">自定义</span>`}</div>
      </div>
      <button class="fdel" type="button" data-rule-del="${r.id}" title="删除规则"><svg class="ic sm"><use href="#i-close"/></svg></button>
    </article>`).join("");
  $$("[data-rule-del]").forEach((btn) => btn.addEventListener("click", () => deleteRule(btn.dataset.ruleDel)));

  nodes.templateSummary.textContent = `${contractTemplateLib.length} 个模板`;
  nodes.templateList.innerHTML = contractTemplateLib.map((t) => `
    <article class="template-item">
      <div class="tpl-head"><strong>${escapeHtml(t.name)}</strong><button class="fdel" type="button" data-tpl-del="${t.id}" title="删除模板"><svg class="ic sm"><use href="#i-close"/></svg></button></div>
      <span class="tag">${escapeHtml(t.type)}</span>
      <ul class="tpl-clauses">${t.clauses.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>
    </article>`).join("");
  $$("[data-tpl-del]").forEach((btn) => btn.addEventListener("click", () => deleteTemplate(btn.dataset.tplDel)));
}
function deleteRule(id) {
  const i = auditRules.findIndex((r) => r.id === id);
  if (i < 0) return;
  const name = auditRules[i].name;
  auditRules.splice(i, 1);
  pushAudit("删除审查规则", name);
  renderRules();
  showToast(`已删除规则「${name}」。`);
}
function deleteTemplate(id) {
  const i = contractTemplateLib.findIndex((t) => t.id === id);
  if (i < 0) return;
  const name = contractTemplateLib[i].name;
  contractTemplateLib.splice(i, 1);
  pushAudit("删除合同模板", name);
  renderRules();
  showToast(`已删除模板「${name}」。`);
}
function openRuleModal() {
  nodes.ruleForm.reset();
  nodes.ruleLevel.value = "medium";
  nodes.ruleMask.hidden = false;
  document.body.style.overflow = "hidden";
  nodes.ruleName.focus();
}
function closeRuleModal() { nodes.ruleMask.hidden = true; document.body.style.overflow = ""; }
function saveRule() {
  const name = nodes.ruleName.value.trim();
  const desc = nodes.ruleDesc.value.trim();
  if (!name || !desc) { showToast("请补全规则名称和描述。"); return; }
  auditRules.unshift({ id: `R${++ruleId}`, name, dimension: nodes.ruleDimension.value, level: nodes.ruleLevel.value, agent: nodes.ruleAgent.value, desc, builtin: false });
  pushAudit("新增审查规则", name);
  closeRuleModal();
  renderRules();
  showToast(`审查规则「${name}」已保存，将用于后续审查。`);
}
function openTemplateModal() {
  nodes.templateForm.reset();
  nodes.templateMask.hidden = false;
  document.body.style.overflow = "hidden";
  nodes.templateName.focus();
}
function closeTemplateModal() { nodes.templateMask.hidden = true; document.body.style.overflow = ""; }
function saveTemplate() {
  const name = nodes.templateName.value.trim();
  const clauses = nodes.templateClauses.value.split("\n").map((c) => c.trim()).filter(Boolean);
  if (!name || !clauses.length) { showToast("请补全模板名称和条款。"); return; }
  contractTemplateLib.unshift({ id: `T${++templateId}`, name, type: nodes.templateType.value, clauses, builtin: false });
  pushAudit("新增合同模板", name);
  closeTemplateModal();
  renderRules();
  showToast(`合同模板「${name}」已保存。`);
}

/* ---------- 通知与预警 ---------- */
function pushNotify(type, title, text) {
  notifications.unshift({ id: `N${++notifyId}`, type, title, text, time: "刚刚", read: false });
  renderNotify();
}
function unreadCount() { return notifications.filter((n) => !n.read).length; }
function renderNotify() {
  const unread = unreadCount();
  nodes.notifyDot.hidden = unread === 0;
  const iconByType = { alert: "i-alert", rectify: "i-rectify", info: "i-bell" };
  nodes.notifyList.innerHTML = notifications.length
    ? notifications.map((n) => `
      <button class="notify-item ${n.read ? "" : "unread"} nt-${n.type}" type="button" data-notify="${n.id}">
        <span class="nt-ic"><svg class="ic sm"><use href="#${iconByType[n.type] || "i-bell"}"/></svg></span>
        <span class="nt-text"><strong>${escapeHtml(n.title)}</strong><span>${escapeHtml(n.text)}</span><small>${n.time}</small></span>
      </button>`).join("")
    : `<div class="notify-empty">暂无通知</div>`;
  $$("[data-notify]").forEach((btn) => btn.addEventListener("click", () => {
    const n = notifications.find((x) => x.id === btn.dataset.notify);
    if (n) { n.read = true; renderNotify(); }
    if (n && n.type === "rectify") { switchView("rectify"); nodes.notifyPanel.hidden = true; }
  }));
}
function toggleNotify() { nodes.notifyPanel.hidden = !nodes.notifyPanel.hidden; }
function markAllRead() { notifications.forEach((n) => (n.read = true)); renderNotify(); showToast("已将全部通知标记为已读。"); }

/* ---------- 权限与审计 ---------- */
function renderAdmin() {
  const permClass = { "读写": "rw", "只读": "ro", "无": "none" };
  const head = `<div class="access-row head"><span>功能模块</span>${Object.values(accessMatrix).map((r) => `<span>${r.label}</span>`).join("")}</div>`;
  const body = accessModules.map((mod) => `
    <div class="access-row">
      <span class="am-mod">${mod}</span>
      ${Object.keys(accessMatrix).map((k) => {
        const p = accessMatrix[k].perms[mod];
        return `<span class="am-perm ${permClass[p]}">${p}</span>`;
      }).join("")}
    </div>`).join("");
  nodes.accessTable.innerHTML = head + body;
  renderAuditLog();
}
function renderAuditLog() {
  const kw = state.auditKeyword.toLowerCase();
  const rows = auditLog.filter((l) => !kw || `${l.user}${l.action}${l.target}`.toLowerCase().includes(kw));
  nodes.auditLogList.innerHTML = rows.length
    ? rows.map((l) => `
      <div class="audit-log-row">
        <span class="al-time">${l.time}</span>
        <span class="al-user"><b>${escapeHtml(l.user)}</b><small>${escapeHtml(l.role)}</small></span>
        <span class="al-action">${escapeHtml(l.action)}</span>
        <span class="al-target">${escapeHtml(l.target)}</span>
        <span class="al-ip">${l.ip}</span>
      </div>`).join("")
    : `<div class="history-empty">未找到匹配的日志。</div>`;
}
function exportAuditLog() {
  const header = ["时间", "用户", "角色", "操作", "对象", "IP"];
  const lines = auditLog.map((l) =>
    [l.time, l.user, l.role, l.action, l.target, l.ip].map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","));
  downloadFile("操作审计日志.csv", [header.join(","), ...lines].join("\n"), "text/csv;charset=utf-8");
  showToast("已导出《操作审计日志》。");
}

/* ---------- 事件绑定 ---------- */
function bindEvents() {
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => switchView(item.dataset.view)));
  $$("[data-goto]").forEach((btn) => btn.addEventListener("click", () => switchView(btn.dataset.goto)));

  // 角色切换
  const toggleRoleMenu = () => { nodes.roleMenu.hidden = !nodes.roleMenu.hidden; };
  nodes.userCard.addEventListener("click", toggleRoleMenu);
  nodes.userCard.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleRoleMenu(); } });
  $$("#roleMenu button").forEach((b) => b.addEventListener("click", () => { applyRole(b.dataset.role); nodes.roleMenu.hidden = true; }));
  document.addEventListener("click", (e) => {
    if (!nodes.roleMenu.hidden && !nodes.roleMenu.contains(e.target) && !nodes.userCard.contains(e.target)) nodes.roleMenu.hidden = true;
  });

  // 上传 / 审查
  nodes.fileInput.addEventListener("change", () => addFiles(Array.from(nodes.fileInput.files)));
  nodes.loadSample.addEventListener("click", loadSampleFiles);
  nodes.runAudit.addEventListener("click", startBatch);
  nodes.resetDemo.addEventListener("click", resetDemo);
  nodes.exportReport.addEventListener("click", exportAuditReport);
  nodes.openFulltext.addEventListener("click", openFulltext);
  $$("[data-dimension]").forEach((input) => input.addEventListener("change", () => {
    if (!nodes.auditResult.hidden) {
      renderRisks();
      showToast("审查维度已更新，风险清单已重新筛选。");
    }
  }));
  nodes.dropZone.addEventListener("dragover", (e) => { e.preventDefault(); nodes.dropZone.classList.add("dragging"); });
  nodes.dropZone.addEventListener("dragleave", () => nodes.dropZone.classList.remove("dragging"));
  nodes.dropZone.addEventListener("drop", (e) => { e.preventDefault(); nodes.dropZone.classList.remove("dragging"); addFiles(Array.from(e.dataTransfer.files)); });

  // 报表
  $("#rangeSeg").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-range]"); if (!btn) return;
    state.range = btn.dataset.range;
    $$("#rangeSeg button").forEach((b) => b.classList.toggle("active", b === btn));
    renderReports();
  });
  $("#exportBoard").addEventListener("click", exportBoard);

  // 知识库
  $("#knowledgeSearch").addEventListener("input", (e) => { state.knowledgeKeyword = e.target.value.trim(); renderKnowledge(); });
  $("#knowledgeFilter").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-cat]"); if (!btn) return;
    state.knowledgeCat = btn.dataset.cat;
    $$("#knowledgeFilter button").forEach((b) => b.classList.toggle("active", b === btn));
    renderKnowledge();
  });
  $("#addKnowledge").addEventListener("click", openKnowledgeModal);
  nodes.knowledgeClose.addEventListener("click", closeKnowledgeModal);
  nodes.knowledgeCancel.addEventListener("click", closeKnowledgeModal);
  nodes.knowledgeMask.addEventListener("click", (e) => { if (e.target === nodes.knowledgeMask) closeKnowledgeModal(); });
  nodes.knowledgeForm.addEventListener("submit", (e) => { e.preventDefault(); addKnowledgeItem(); });

  // 历史
  $("#historySearch").addEventListener("input", (e) => { state.historyKeyword = e.target.value.trim(); state.historyPage = 1; renderHistory(); });
  $("#historyFilter").addEventListener("change", (e) => { state.historyLevel = e.target.value; state.historyPage = 1; renderHistory(); });

  // 抽屉 / 模态
  $("#drawerClose").addEventListener("click", closeDrawer);
  nodes.drawerMask.addEventListener("click", closeDrawer);
  $("#drawerConfirm").addEventListener("click", () => applyRiskDecision("confirm"));
  $("#drawerReject").addEventListener("click", () => applyRiskDecision("reject"));
  $("#fulltextClose").addEventListener("click", closeFulltext);
  nodes.fulltextMask.addEventListener("click", (e) => { if (e.target === nodes.fulltextMask) closeFulltext(); });
  nodes.historyClose.addEventListener("click", closeHistoryModal);
  nodes.historyMask.addEventListener("click", (e) => { if (e.target === nodes.historyMask) closeHistoryModal(); });
  // 通知预警
  nodes.notifyBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleNotify(); });
  nodes.notifyReadAll.addEventListener("click", markAllRead);
  document.addEventListener("click", (e) => {
    if (!nodes.notifyPanel.hidden && !nodes.notifyPanel.contains(e.target) && !nodes.notifyBtn.contains(e.target)) nodes.notifyPanel.hidden = true;
  });

  // 整改跟踪
  $("#rectifySeg").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-rstatus]"); if (!btn) return;
    state.rectifyFilter = btn.dataset.rstatus;
    $$("#rectifySeg button").forEach((b) => b.classList.toggle("active", b === btn));
    renderRectify();
  });
  nodes.exportRectify.addEventListener("click", exportRectify);

  // 批量报告
  nodes.openBatchReport.addEventListener("click", openBatchReport);
  nodes.batchClose.addEventListener("click", closeBatchReport);
  nodes.exportBatch.addEventListener("click", exportBatchReport);
  nodes.batchMask.addEventListener("click", (e) => { if (e.target === nodes.batchMask) closeBatchReport(); });

  // 版本比对
  nodes.openCompare.addEventListener("click", openCompare);
  nodes.compareClose.addEventListener("click", closeCompare);
  nodes.compareMask.addEventListener("click", (e) => { if (e.target === nodes.compareMask) closeCompare(); });

  // 报表钻取
  nodes.drillType.addEventListener("change", (e) => { state.drill.type = e.target.value; applyDrill(); });
  nodes.drillAmount.addEventListener("change", (e) => { state.drill.amount = e.target.value; applyDrill(); });
  nodes.drillLevel.addEventListener("change", (e) => { state.drill.level = e.target.value; applyDrill(); });
  nodes.drillReset.addEventListener("click", resetDrill);

  // 规则与模板
  nodes.addRule.addEventListener("click", openRuleModal);
  nodes.ruleClose.addEventListener("click", closeRuleModal);
  nodes.ruleCancel.addEventListener("click", closeRuleModal);
  nodes.ruleForm.addEventListener("submit", (e) => { e.preventDefault(); saveRule(); });
  nodes.ruleMask.addEventListener("click", (e) => { if (e.target === nodes.ruleMask) closeRuleModal(); });
  nodes.addTemplate.addEventListener("click", openTemplateModal);
  nodes.templateClose.addEventListener("click", closeTemplateModal);
  nodes.templateCancel.addEventListener("click", closeTemplateModal);
  nodes.templateForm.addEventListener("submit", (e) => { e.preventDefault(); saveTemplate(); });
  nodes.templateMask.addEventListener("click", (e) => { if (e.target === nodes.templateMask) closeTemplateModal(); });

  // 权限与审计
  nodes.auditSearch.addEventListener("input", (e) => { state.auditKeyword = e.target.value.trim(); renderAuditLog(); });
  nodes.exportAudit.addEventListener("click", exportAuditLog);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeDrawer();
      closeFulltext();
      closeKnowledgeModal();
      closeHistoryModal();
      closeBatchReport();
      closeCompare();
      closeRuleModal();
      closeTemplateModal();
    }
  });
}

function init() {
  bindEvents();
  applyRole("legal");
  renderReports();
  renderKnowledge();
  renderHistory();
  renderNotify();
  updateRectifyBadge();
}

init();
