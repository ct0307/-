const fs = require("fs");
const os = require("os");
const path = require("path");
const sharp = require("sharp");

const OUTPUT_DIR = path.resolve(__dirname, "../assets/diagrams");

const C = {
  bg: "#FFFFFF",
  primary: "#245B78",
  secondary: "#4C7A92",
  accent: "#C48A2C",
  text: "#1F2933",
  muted: "#52616B",
  border: "#C9D4DC",
  panel: "#F5F8FA",
  accentPanel: "#FFF7E8",
  success: "#2F725D",
  danger: "#A64B45",
};

const FONT = "Microsoft YaHei, Noto Sans CJK SC, sans-serif";

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function text(x, y, value, options = {}) {
  const {
    size = 26,
    weight = 400,
    fill = C.text,
    anchor = "start",
    opacity = 1,
  } = options;
  return `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" opacity="${opacity}">${esc(value)}</text>`;
}

function multiline(x, y, lines, options = {}) {
  const { size = 24, lineHeight = 38, anchor = "start", ...rest } = options;
  return lines
    .map((line, index) => text(x, y + index * lineHeight, line, { size, anchor, ...rest }))
    .join("");
}

function box(x, y, width, height, options = {}) {
  const {
    fill = C.bg,
    stroke = C.border,
    strokeWidth = 2,
    radius = 8,
    shadow = false,
  } = options;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${shadow ? ' filter="url(#shadow)"' : ""}/>`;
}

function card(x, y, width, height, title, lines, options = {}) {
  const { fill = C.bg, stripe = C.primary, titleSize = 25, bodySize = 21 } = options;
  return [
    box(x, y, width, height, { fill, shadow: options.shadow ?? true }),
    `<rect x="${x}" y="${y}" width="8" height="${height}" rx="4" fill="${stripe}"/>`,
    text(x + 30, y + 44, title, { size: titleSize, weight: 700, fill: stripe }),
    multiline(x + 30, y + 82, lines, { size: bodySize, lineHeight: 34, fill: C.muted }),
  ].join("");
}

function pill(x, y, width, value, options = {}) {
  const { fill = C.panel, color = C.primary, stroke = C.border } = options;
  return [
    box(x, y, width, 48, { fill, stroke, radius: 8 }),
    text(x + width / 2, y + 32, value, { size: 20, weight: 600, fill: color, anchor: "middle" }),
  ].join("");
}

function line(x1, y1, x2, y2, options = {}) {
  const { color = C.secondary, width = 3, dashed = false, arrow = true } = options;
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="${width}"${dashed ? ' stroke-dasharray="10 8"' : ""}${arrow ? ' marker-end="url(#arrow)"' : ""}/>`;
}

function pathLine(d, options = {}) {
  const { color = C.secondary, width = 3, dashed = false, arrow = true } = options;
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}"${dashed ? ' stroke-dasharray="10 8"' : ""}${arrow ? ' marker-end="url(#arrow)"' : ""}/>`;
}

function circle(cx, cy, radius, options = {}) {
  const { fill = C.bg, stroke = C.primary, width = 3 } = options;
  return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${width}"/>`;
}

function defs() {
  return `<defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">
      <feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#1F2933" flood-opacity="0.10"/>
    </filter>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M 0 0 L 12 6 L 0 12 z" fill="${C.secondary}"/>
    </marker>
    <marker id="arrowAccent" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M 0 0 L 12 6 L 0 12 z" fill="${C.accent}"/>
    </marker>
  </defs>`;
}

function header(title, subtitle, width) {
  return [
    text(72, 72, title, { size: 38, weight: 700 }),
    text(72, 112, subtitle, { size: 21, fill: C.muted }),
    `<line x1="72" y1="138" x2="${width - 72}" y2="138" stroke="${C.border}" stroke-width="2"/>`,
  ].join("");
}

function stageBadge(x, y, number, label) {
  return [
    circle(x, y, 27, { fill: C.primary, stroke: C.primary }),
    text(x, y + 9, number, { size: 22, weight: 700, fill: C.bg, anchor: "middle" }),
    text(x + 44, y + 9, label, { size: 23, weight: 700 }),
  ].join("");
}

async function renderDiagram({ name, width = 2000, height = 1200, title, subtitle, bodySvg }) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    ${defs()}
    <rect width="100%" height="100%" fill="${C.bg}"/>
    ${header(title, subtitle, width)}
    ${bodySvg}
  </svg>`;
  await sharp(Buffer.from(svg)).png({ compressionLevel: 9 }).toFile(path.join(OUTPUT_DIR, `${name}.png`));
}

function problemSolution() {
  const problems = [
    ["审查耗时", "文件预检与字段摘录重复", "跨部门等待造成积压"],
    ["尺度不一", "经验分散且规则口径不统一", "相同风险结论难复现"],
    ["证据薄弱", "意见脱离原文与适用依据", "复核和审计成本高"],
    ["数据割裂", "合同、风险、整改各自成表", "管理分析缺少可信明细"],
  ];
  const mechanisms = ["双 Agent 专业分工", "逐风险 RAG 证据链", "人机责任闭环", "统一合同数据模型"];
  const outcomes = ["重复作业自动化", "高风险更早暴露", "结论可核验追溯", "数据可治理复用"];
  let svg = "";
  problems.forEach((item, i) => {
    const y = 190 + i * 220;
    svg += card(80, y, 510, 172, item[0], item.slice(1), { stripe: C.danger });
    svg += card(745, y, 510, 172, mechanisms[i], ["以明确输入输出契约运行", "失败降级并保留人工门禁"], { stripe: C.primary, fill: C.panel });
    svg += card(1410, y, 510, 172, outcomes[i], ["使用量化指标验证", "不以模型替代专业判断"], { stripe: C.success });
    svg += line(610, y + 86, 725, y + 86);
    svg += line(1275, y + 86, 1390, y + 86);
  });
  svg += multiline(335, 1080, ["业务问题"], { size: 24, weight: 700, fill: C.danger, anchor: "middle" });
  svg += multiline(1000, 1080, ["可信机制"], { size: 24, weight: 700, fill: C.primary, anchor: "middle" });
  svg += multiline(1665, 1080, ["目标价值"], { size: 24, weight: 700, fill: C.success, anchor: "middle" });
  return svg;
}

function userCollaboration() {
  const users = [
    [100, 210, "业务人员", ["提交背景与合同", "执行整改与反馈"]],
    [100, 750, "系统管理员", ["配置权限与系统", "保障运行与审计"]],
    [1390, 210, "法务 / 财务主管", ["专业复核与裁决", "维护规则与口径"]],
    [1390, 750, "管理层", ["查看聚合趋势", "下钻可信明细"]],
  ];
  let svg = "";
  svg += box(700, 365, 600, 390, { fill: C.panel, stroke: C.primary, strokeWidth: 3, shadow: true });
  svg += text(1000, 432, "统一合同任务", { size: 34, weight: 700, fill: C.primary, anchor: "middle" });
  svg += pill(790, 478, 420, "合同版本 + 原文定位");
  svg += pill(790, 546, 420, "风险 + 依据 + 置信度", { fill: C.accentPanel, color: C.accent });
  svg += pill(790, 614, 420, "复核 + 整改 + 审计事件");
  svg += text(1000, 704, "同一对象 · 分工协同 · 权责留痕", { size: 22, fill: C.muted, anchor: "middle" });
  users.forEach(([x, y, titleValue, lines]) => {
    svg += card(x, y, 510, 190, titleValue, lines, { stripe: titleValue === "管理层" ? C.accent : C.primary });
  });
  svg += pathLine("M 610 305 H 660 V 440 H 690");
  svg += pathLine("M 610 845 H 660 V 680 H 690");
  svg += pathLine("M 1390 305 H 1340 V 440 H 1310");
  svg += pathLine("M 1390 845 H 1340 V 680 H 1310");
  svg += card(745, 890, 510, 160, "知识管理员", ["核验来源、适用范围与版本", "发布变更触发影响分析"], { stripe: C.success });
  svg += line(1000, 870, 1000, 770, { arrow: true });
  return svg;
}

function functionalArchitecture() {
  const domains = [
    ["01", "合同接入", "上传 · 预检 · 版本"],
    ["02", "智能审查", "抽取 · 双 Agent · 证据"],
    ["03", "人工复核", "冲突 · 采纳 · 责任"],
    ["04", "整改闭环", "任务 · 反馈 · 关闭"],
    ["05", "知识治理", "来源 · 版本 · 发布"],
    ["06", "报表分析", "指标 · 下钻 · 导出"],
    ["07", "系统治理", "身份 · 配置 · 审计"],
  ];
  let svg = "";
  svg += box(80, 180, 1840, 110, { fill: C.primary, stroke: C.primary });
  svg += text(1000, 248, "企业合同风险作业平台", { size: 34, weight: 700, fill: C.bg, anchor: "middle" });
  domains.forEach((domain, i) => {
    const col = i % 4;
    const row = Math.floor(i / 4);
    const x = 80 + col * 470;
    const y = 345 + row * 260;
    svg += box(x, y, 405, 205, { fill: row === 0 ? C.bg : C.panel, shadow: true });
    svg += circle(x + 52, y + 52, 27, { fill: C.primary, stroke: C.primary });
    svg += text(x + 52, y + 60, domain[0], { size: 18, weight: 700, fill: C.bg, anchor: "middle" });
    svg += text(x + 94, y + 62, domain[1], { size: 28, weight: 700, fill: C.primary });
    svg += text(x + 34, y + 126, domain[2], { size: 21, fill: C.muted });
    svg += text(x + 34, y + 166, "输入、输出、异常与责任明确", { size: 19, fill: C.muted });
  });
  svg += box(1490, 605, 430, 205, { fill: C.accentPanel, stroke: C.accent, shadow: true });
  svg += text(1705, 670, "跨域共享基座", { size: 28, weight: 700, fill: C.accent, anchor: "middle" });
  svg += multiline(1705, 720, ["组织权限 · 数据字典", "任务状态 · 统一审计"], { size: 21, lineHeight: 38, fill: C.muted, anchor: "middle" });
  svg += box(80, 890, 1840, 135, { fill: C.panel, stroke: C.border });
  svg += text(1000, 940, "贯穿原则", { size: 24, weight: 700, fill: C.primary, anchor: "middle" });
  ["原文可定位", "依据可核验", "人工可接管", "过程可审计", "组件可替换"].forEach((item, i) => {
    svg += pill(160 + i * 350, 962, 290, item);
  });
  return svg;
}

function contractReviewFlow() {
  const steps = [
    ["01", "上传预检", "格式、大小、病毒"],
    ["02", "加密存储", "版本与文件哈希"],
    ["03", "文本解析", "段落、表格、页码"],
    ["04", "要素抽取", "字段、置信度、定位"],
    ["05", "双 Agent", "法务与财务候选风险"],
    ["06", "RAG 取证", "可靠性与适用性"],
    ["07", "人工复核", "采纳、调整或忽略"],
    ["08", "整改协同", "责任、期限与版本"],
    ["09", "归档关闭", "状态门禁与审计"],
    ["10", "报表更新", "聚合、下钻、导出"],
  ];
  let svg = "";
  steps.forEach((step, i) => {
    const row = i < 5 ? 0 : 1;
    const col = row === 0 ? i : 9 - i;
    const x = 80 + col * 380;
    const y = 220 + row * 410;
    svg += box(x, y, 320, 210, { fill: step[0] === "07" ? C.accentPanel : C.bg, stroke: step[0] === "07" ? C.accent : C.border, shadow: true });
    svg += text(x + 28, y + 45, step[0], { size: 21, weight: 700, fill: C.secondary });
    svg += text(x + 28, y + 92, step[1], { size: 27, weight: 700, fill: step[0] === "07" ? C.accent : C.primary });
    svg += multiline(x + 28, y + 135, [step[2], step[0] === "07" ? "高影响结论责任门禁" : "异常时停止或降级"], { size: 19, lineHeight: 34, fill: C.muted });
    if (row === 0 && i < 4) svg += line(x + 325, y + 105, x + 370, y + 105);
    if (row === 1 && i < 9) svg += line(x - 10, y + 105, x - 55, y + 105);
  });
  svg += pathLine("M 1840 430 V 520 Q 1840 560 1800 560 H 1740 V 620");
  svg += box(150, 940, 1700, 100, { fill: C.panel });
  svg += text(1000, 1000, "异常原则：单文件隔离 · 有限重试 · 不确定性显式呈现 · 历史结果不覆盖", { size: 25, weight: 600, fill: C.primary, anchor: "middle" });
  return svg;
}

function technicalArchitecture() {
  const layers = [
    ["交互层", "浏览器端 · 响应式工作台 · 可访问状态反馈", C.primary],
    ["应用服务层", "认证授权 · 合同任务 · 复核整改 · 报表知识", C.secondary],
    ["智能编排层", "任务编排 · 双 Agent · 契约校验 · 超时降级", C.primary],
    ["知识检索层", "BM25 + 向量召回 · RRF 融合 · 适用性门禁", C.accent],
    ["数据持久层", "关系数据库 · 对象存储 · 向量索引 · 审计事件", C.secondary],
    ["基础设施层", "Nginx · 队列 · 模型服务 · 监控 · 备份恢复", C.primary],
  ];
  let svg = "";
  layers.forEach(([name, detail, color], i) => {
    const y = 185 + i * 145;
    svg += box(160, y, 1680, 112, { fill: i % 2 === 0 ? C.bg : C.panel, stroke: color, strokeWidth: 2, shadow: true });
    svg += `<rect x="160" y="${y}" width="260" height="112" rx="8" fill="${color}"/>`;
    svg += text(290, y + 69, name, { size: 26, weight: 700, fill: C.bg, anchor: "middle" });
    svg += text(470, y + 67, detail, { size: 24, fill: C.text });
    if (i < layers.length - 1) svg += line(1000, y + 116, 1000, y + 137, { width: 2 });
  });
  svg += box(160, 1065, 1680, 70, { fill: C.accentPanel, stroke: C.accent });
  svg += text(1000, 1111, "横切能力：身份与权限 · 配置与密钥 · 可观测性 · 数据生命周期 · 供应链安全", { size: 22, weight: 600, fill: C.accent, anchor: "middle" });
  return svg;
}

function privateDeployment() {
  let svg = "";
  svg += box(70, 190, 410, 780, { fill: C.panel, stroke: C.border });
  svg += text(275, 240, "用户接入区", { size: 27, weight: 700, fill: C.primary, anchor: "middle" });
  svg += card(115, 300, 320, 150, "企业浏览器", ["统一身份 · TLS", "最小化本地缓存"], { stripe: C.primary });
  svg += card(115, 560, 320, 150, "外部系统", ["OA / ERP / 电子签约", "版本化接口与幂等"], { stripe: C.secondary });
  svg += box(550, 190, 550, 780, { fill: C.bg, stroke: C.primary, strokeWidth: 3 });
  svg += text(825, 240, "应用与智能区", { size: 27, weight: 700, fill: C.primary, anchor: "middle" });
  svg += card(610, 290, 430, 140, "Nginx / API 服务", ["认证、授权、限流、路由"], { stripe: C.primary });
  svg += card(610, 490, 430, 140, "异步任务与编排", ["队列、幂等、双 Agent、降级"], { stripe: C.secondary });
  svg += card(610, 690, 430, 140, "本地模型服务", ["模型适配器、资源隔离、审计"], { stripe: C.accent });
  svg += box(1170, 190, 760, 780, { fill: C.panel, stroke: C.border });
  svg += text(1550, 240, "受控数据区", { size: 27, weight: 700, fill: C.primary, anchor: "middle" });
  svg += card(1225, 300, 300, 150, "关系数据库", ["业务实体、状态、权限", "事务与时间点恢复"], { stripe: C.primary });
  svg += card(1580, 300, 300, 150, "对象存储", ["合同密文、版本、哈希", "保留与删除策略"], { stripe: C.primary });
  svg += card(1225, 560, 300, 150, "向量 / 关键词索引", ["知识切片与版本", "发布后原子切换"], { stripe: C.secondary });
  svg += card(1580, 560, 300, 150, "监控与审计", ["指标、日志、告警", "证据留存与脱敏"], { stripe: C.accent });
  svg += line(480, 375, 595, 375);
  svg += line(1045, 360, 1210, 360);
  svg += line(1045, 560, 1210, 625);
  svg += line(1045, 760, 1565, 650);
  svg += pathLine("M 480 635 H 520 V 550 H 595");
  svg += box(350, 1030, 1300, 84, { fill: C.accentPanel, stroke: C.accent });
  svg += text(1000, 1083, "信任边界：合同原文与专业知识默认不出企业受控网络", { size: 25, weight: 700, fill: C.accent, anchor: "middle" });
  return svg;
}

function agentSequence() {
  const lanes = ["用户 / 应用", "编排器", "法务 Agent", "财务 Agent", "RAG / 知识", "人工复核"];
  const xs = [150, 490, 830, 1170, 1510, 1850];
  let svg = "";
  lanes.forEach((lane, i) => {
    svg += box(xs[i] - 125, 180, 250, 70, { fill: i === 5 ? C.accentPanel : C.panel, stroke: i === 5 ? C.accent : C.border });
    svg += text(xs[i], 225, lane, { size: 21, weight: 700, fill: i === 5 ? C.accent : C.primary, anchor: "middle" });
    svg += line(xs[i], 250, xs[i], 1090, { color: C.border, width: 2, dashed: true, arrow: false });
  });
  const msgs = [
    [0, 1, 310, "提交合同版本与上下文"],
    [1, 2, 395, "并行审查：法律风险"],
    [1, 3, 480, "并行审查：财务风险"],
    [2, 4, 565, "按候选风险检索依据"],
    [3, 4, 650, "按候选风险检索依据"],
    [4, 1, 735, "来源、适用性与证据片段"],
    [1, 2, 820, "交叉检查财务相关结论"],
    [1, 3, 905, "交叉检查法律相关结论"],
    [1, 5, 990, "冲突 / 低置信度 / 高影响事项"],
  ];
  msgs.forEach(([from, to, y, label], i) => {
    const start = xs[from];
    const end = xs[to];
    const color = i === msgs.length - 1 ? C.accent : C.secondary;
    svg += `<line x1="${start}" y1="${y}" x2="${end + (end > start ? -14 : 14)}" y2="${y}" stroke="${color}" stroke-width="3" marker-end="url(#${color === C.accent ? "arrowAccent" : "arrow"})"/>`;
    svg += box((start + end) / 2 - 145, y - 31, 290, 42, { fill: C.bg, stroke: C.bg, radius: 0 });
    svg += text((start + end) / 2, y - 4, label, { size: 17, weight: 600, fill: color, anchor: "middle" });
  });
  svg += text(1000, 1140, "输出契约统一：风险分类 · 原文定位 · 依据 · 置信度 · 建议 · 责任状态", { size: 23, weight: 600, fill: C.primary, anchor: "middle" });
  return svg;
}

function ragEvidenceFlow() {
  const nodes = [
    [80, "候选风险", ["风险分类", "合同原文"]],
    [390, "混合查询", ["语义查询", "关键词查询"]],
    [700, "双路召回", ["向量 Top-K", "BM25 Top-K"]],
    [1010, "融合过滤", ["RRF 排名", "类型 / 有效期"]],
    [1320, "证据门禁", ["来源可靠", "适用范围匹配"]],
    [1630, "风险结论", ["引用片段", "版本与置信度"]],
  ];
  let svg = "";
  nodes.forEach(([x, titleValue, lines], i) => {
    const y = 330;
    svg += card(x, y, 250, 210, titleValue, lines, { stripe: i === 4 ? C.accent : C.primary, fill: i === 4 ? C.accentPanel : C.bg });
    if (i < nodes.length - 1) svg += line(x + 255, y + 105, x + 300, y + 105);
  });
  svg += box(550, 710, 900, 170, { fill: C.panel, stroke: C.border });
  svg += text(1000, 760, "知识发布与版本治理", { size: 28, weight: 700, fill: C.primary, anchor: "middle" });
  ["权威来源", "正文哈希", "切片元数据", "替换链", "缓存失效"].forEach((item, i) => {
    svg += pill(590 + i * 170, 800, 150, item);
  });
  svg += line(1000, 700, 1000, 560, { dashed: true });
  svg += box(1320, 930, 560, 110, { fill: C.accentPanel, stroke: C.accent });
  svg += text(1600, 973, "无可靠来源", { size: 24, weight: 700, fill: C.accent, anchor: "middle" });
  svg += text(1600, 1010, "限制置信度并转人工复核，不生成伪依据", { size: 20, fill: C.muted, anchor: "middle" });
  svg += pathLine("M 1445 545 V 910 H 1510", { color: C.accent });
  svg += box(120, 930, 930, 110, { fill: C.panel, stroke: C.border });
  svg += text(585, 974, "可验证证据链", { size: 24, weight: 700, fill: C.primary, anchor: "middle" });
  svg += text(585, 1010, "风险 → 原文 → 来源 → 适用版本 → 专业复核", { size: 21, fill: C.muted, anchor: "middle" });
  return svg;
}

function parsingDataFlow() {
  const sources = [["PDF", "文本 / 表格"], ["DOCX", "段落 / 表格"], ["TXT", "编码规范化"], ["扫描件", "OCR 扩展"]];
  let svg = "";
  sources.forEach(([name, detail], i) => {
    svg += card(75, 190 + i * 210, 350, 150, name, [detail, "保留文件版本与哈希"], { stripe: i === 3 ? C.accent : C.primary });
    svg += line(435, 265 + i * 210, 535, 265 + i * 210);
  });
  svg += box(550, 190, 440, 780, { fill: C.panel, stroke: C.border });
  svg += text(770, 245, "解析与质量门禁", { size: 28, weight: 700, fill: C.primary, anchor: "middle" });
  ["格式与病毒预检", "正文和表格解析", "页码 / 段落定位", "乱码与空文本检测", "备用解析或人工补件"].forEach((item, i) => {
    svg += pill(615, 310 + i * 115, 310, item, { fill: i === 4 ? C.accentPanel : C.bg, color: i === 4 ? C.accent : C.primary });
    if (i < 4) svg += line(770, 363 + i * 115, 770, 414 + i * 115);
  });
  svg += line(1005, 570, 1115, 570);
  svg += box(1130, 190, 790, 780, { fill: C.bg, stroke: C.primary, strokeWidth: 3 });
  svg += text(1525, 245, "结构化抽取与风险契约", { size: 28, weight: 700, fill: C.primary, anchor: "middle" });
  svg += card(1190, 310, 310, 190, "要素抽取", ["正则初提 + LLM 精抽", "类型 / 数值一致性校验", "字段置信度与原文定位"], { stripe: C.primary });
  svg += card(1550, 310, 310, 190, "标准化字段", ["主体 · 金额 · 日期", "期限 · 付款 · 履约节点", "未经确认保留质量标记"], { stripe: C.secondary });
  svg += card(1190, 620, 310, 190, "风险 JSON", ["分类 · 等级 · 说明", "原文 · 依据 · 建议", "状态 · 责任 · 版本"], { stripe: C.accent });
  svg += card(1550, 620, 310, 190, "失败处理", ["字段级错误不吞没", "低质量阻断审查通过", "历史结果保持可追溯"], { stripe: C.danger });
  svg += line(1505, 405, 1540, 405);
  svg += line(1345, 515, 1345, 605);
  svg += line(1705, 515, 1705, 605);
  svg += text(1000, 1080, "基本原则：解析质量不足不等于合同无风险", { size: 27, weight: 700, fill: C.accent, anchor: "middle" });
  return svg;
}

function coreEr() {
  const entities = [
    [90, 220, "组织 / 用户", ["organization_id", "user_id · role_id"]],
    [620, 190, "合同 / 版本", ["contract_id", "version_id · file_hash"]],
    [1220, 190, "风险 / 依据", ["risk_id · category", "source_id · chunk_id"]],
    [1590, 220, "知识 / 版本", ["knowledge_id", "valid_from / valid_to"]],
    [260, 720, "审计事件", ["event_id · actor", "object · before / after"]],
    [740, 720, "复核 / 整改", ["review_id", "remediation_id · status"]],
    [1280, 720, "模型调用", ["call_id · model", "prompt / output hash"]],
    [1650, 720, "规则 / 模板", ["rule_id", "template_id · version"]],
  ];
  let svg = "";
  svg += pathLine("M 490 330 H 610", { arrow: false });
  svg += pathLine("M 1030 330 H 1210", { arrow: false });
  svg += pathLine("M 1510 330 H 1580", { arrow: false });
  svg += pathLine("M 830 430 V 690", { arrow: false });
  svg += pathLine("M 1390 430 V 690", { arrow: false });
  svg += pathLine("M 950 820 H 1270", { arrow: false });
  svg += pathLine("M 490 770 H 720", { arrow: false });
  svg += pathLine("M 1480 820 H 1640", { arrow: false });
  svg += pathLine("M 280 430 V 700", { arrow: false });
  svg += pathLine("M 1750 430 V 700", { arrow: false });
  entities.forEach(([x, y, name, fields], i) => {
    svg += card(x, y, 320, 210, name, fields, { stripe: i === 2 ? C.accent : C.primary, fill: i === 2 ? C.accentPanel : C.bg });
  });
  svg += text(550, 310, "1 : N", { size: 18, weight: 700, fill: C.secondary, anchor: "middle" });
  svg += text(1120, 310, "1 : N", { size: 18, weight: 700, fill: C.secondary, anchor: "middle" });
  svg += text(1545, 310, "N : 1", { size: 18, weight: 700, fill: C.secondary, anchor: "middle" });
  svg += box(410, 1030, 1180, 80, { fill: C.panel, stroke: C.border });
  svg += text(1000, 1080, "主链：组织 → 合同版本 → 风险 → 证据 → 复核整改 → 审计事件", { size: 24, weight: 700, fill: C.primary, anchor: "middle" });
  return svg;
}

function securityLayers() {
  const layers = [
    ["身份与访问", "统一身份 · MFA 扩展 · RBAC · 部门隔离 · 最小权限"],
    ["应用与接口", "输入校验 · 上传白名单 · 限流 · 幂等 · 提示注入防护"],
    ["数据与密钥", "传输加密 · 文件加密 · 字段脱敏 · 密钥轮换 · 数据最小化"],
    ["模型与知识", "本地优先 · 出域门禁 · 来源准入 · 版本审核 · 供应商可替换"],
    ["运行与恢复", "镜像基线 · 依赖清单 · 监控告警 · 备份还原 · 灾难演练"],
    ["审计与治理", "全链路事件 · 日志脱敏 · 异常检测 · 保留删除 · 责任追踪"],
  ];
  let svg = "";
  layers.forEach(([name, detail], i) => {
    const inset = i * 55;
    const y = 190 + i * 140;
    const color = i === 2 || i === 3 ? C.accent : i % 2 === 0 ? C.primary : C.secondary;
    svg += box(110 + inset, y, 1780 - inset * 2, 105, { fill: i % 2 === 0 ? C.bg : C.panel, stroke: color, strokeWidth: 3, shadow: true });
    svg += text(155 + inset, y + 65, name, { size: 26, weight: 700, fill: color });
    svg += text(430 + inset, y + 64, detail, { size: 21, fill: C.text });
  });
  svg += box(540, 1050, 920, 80, { fill: C.accentPanel, stroke: C.accent });
  svg += text(1000, 1100, "安全不是单一功能，而是覆盖数据全生命周期的交付基线", { size: 24, weight: 700, fill: C.accent, anchor: "middle" });
  return svg;
}

function implementationRoadmap() {
  const stages = [
    ["1", "业务闭环", "完成高频合同端到端作业", ["P1 任务流", "字段与风险定位", "人工责任门禁"], "端到端验收"],
    ["2", "可信增强", "让结论可核验、知识可治理", ["混合检索", "证据链与评测", "安全审计"], "质量门禁"],
    ["3", "企业交付", "形成可部署、迁移和恢复能力", ["生产数据层", "统一身份与密钥", "监控备份"], "交付演练"],
    ["4", "规模化运营", "支持多组织与持续治理", ["组织隔离", "行业知识包", "标准集成"], "运营门禁"],
  ];
  let svg = "";
  stages.forEach(([number, name, goal, items, gate], i) => {
    const x = 80 + i * 480;
    svg += box(x, 270, 410, 570, { fill: i % 2 === 0 ? C.bg : C.panel, stroke: i === 1 ? C.accent : C.border, strokeWidth: i === 1 ? 3 : 2, shadow: true });
    svg += circle(x + 55, 330, 31, { fill: i === 1 ? C.accent : C.primary, stroke: i === 1 ? C.accent : C.primary });
    svg += text(x + 55, 340, number, { size: 23, weight: 700, fill: C.bg, anchor: "middle" });
    svg += text(x + 105, 341, name, { size: 29, weight: 700, fill: i === 1 ? C.accent : C.primary });
    svg += multiline(x + 35, 415, [goal], { size: 20, fill: C.muted });
    items.forEach((item, j) => {
      svg += pill(x + 35, 490 + j * 78, 340, item, { fill: C.bg });
    });
    svg += box(x + 35, 740, 340, 64, { fill: C.accentPanel, stroke: C.accent });
    svg += text(x + 205, 781, gate, { size: 22, weight: 700, fill: C.accent, anchor: "middle" });
    if (i < 3) svg += line(x + 420, 555, x + 470, 555);
  });
  svg += line(150, 940, 1850, 940, { color: C.primary, width: 4, arrow: true });
  stages.forEach((stage, i) => {
    const x = 285 + i * 480;
    svg += circle(x, 940, 12, { fill: C.primary, stroke: C.primary });
    svg += text(x, 990, `阶段 ${i + 1}`, { size: 20, weight: 600, fill: C.muted, anchor: "middle" });
  });
  svg += text(1000, 1090, "每阶段由交付物、量化指标和退出标准共同决定是否进入下一阶段", { size: 25, weight: 700, fill: C.primary, anchor: "middle" });
  return svg;
}

function testingLoop() {
  const nodes = [
    [1000, 265, "01", "冻结范围", ["版本 · 配置 · 环境"]],
    [1510, 440, "02", "构造证据", ["样本 · 日志 · 请求响应"]],
    [1510, 800, "03", "执行测量", ["公式 · 分层 · 置信区间"]],
    [1000, 970, "04", "判定门禁", ["阈值 · 阻断缺陷"]],
    [490, 800, "05", "缺陷复测", ["根因 · 修复 · 回归"]],
    [490, 440, "06", "发布基线", ["报告 · 残余风险"]],
  ];
  let svg = "";
  const route = [[1000, 265, 1510, 440], [1510, 440, 1510, 800], [1510, 800, 1000, 970], [1000, 970, 490, 800], [490, 800, 490, 440], [490, 440, 1000, 265]];
  route.forEach(([x1, y1, x2, y2]) => svg += line(x1, y1, x2, y2));
  svg += circle(1000, 620, 215, { fill: C.panel, stroke: C.border, width: 3 });
  svg += text(1000, 575, "质量闭环", { size: 36, weight: 700, fill: C.primary, anchor: "middle" });
  svg += multiline(1000, 630, ["功能 · AI · RAG · 性能", "安全 · 可靠性 · 兼容性 · 体验"], { size: 22, lineHeight: 42, fill: C.muted, anchor: "middle" });
  nodes.forEach(([x, y, number, name, lines], i) => {
    svg += box(x - 185, y - 90, 370, 180, { fill: C.bg, stroke: i === 3 ? C.accent : C.border, strokeWidth: i === 3 ? 3 : 2, shadow: true });
    svg += circle(x - 130, y - 35, 25, { fill: i === 3 ? C.accent : C.primary, stroke: i === 3 ? C.accent : C.primary });
    svg += text(x - 130, y - 27, number, { size: 17, weight: 700, fill: C.bg, anchor: "middle" });
    svg += text(x - 90, y - 25, name, { size: 26, weight: 700, fill: i === 3 ? C.accent : C.primary });
    svg += multiline(x, y + 34, lines, { size: 19, fill: C.muted, anchor: "middle" });
  });
  return svg;
}

function productRoadmap() {
  const tracks = [
    ["业务能力", ["高频合同闭环", "跨专业证据链", "多组织运营", "行业解决方案"]],
    ["技术能力", ["模块化单体", "模型与检索评测", "弹性任务平台", "开放能力生态"]],
    ["治理能力", ["责任与审计", "知识版本治理", "安全运营", "持续合规评估"]],
  ];
  const phases = ["业务闭环期", "可信增强期", "企业交付期", "规模运营期"];
  let svg = "";
  phases.forEach((phase, i) => {
    const x = 440 + i * 375;
    svg += box(x, 185, 320, 70, { fill: i === 1 ? C.accentPanel : C.panel, stroke: i === 1 ? C.accent : C.border });
    svg += text(x + 160, 230, phase, { size: 23, weight: 700, fill: i === 1 ? C.accent : C.primary, anchor: "middle" });
  });
  tracks.forEach(([track, items], row) => {
    const y = 330 + row * 235;
    svg += box(80, y, 280, 170, { fill: C.primary, stroke: C.primary });
    svg += text(220, y + 98, track, { size: 28, weight: 700, fill: C.bg, anchor: "middle" });
    items.forEach((item, col) => {
      const x = 440 + col * 375;
      svg += box(x, y, 320, 170, { fill: (row + col) % 2 === 0 ? C.bg : C.panel, stroke: col === 1 ? C.accent : C.border, shadow: true });
      svg += text(x + 160, y + 78, item, { size: 22, weight: 700, fill: col === 1 ? C.accent : C.primary, anchor: "middle" });
      svg += text(x + 160, y + 118, col < 2 ? "夯实质量与责任边界" : "在门禁通过后扩展", { size: 18, fill: C.muted, anchor: "middle" });
      if (col < 3) svg += line(x + 325, y + 85, x + 365, y + 85);
    });
  });
  svg += box(250, 1065, 1500, 70, { fill: C.accentPanel, stroke: C.accent });
  svg += text(1000, 1110, "演进原则：以质量稳定、数据边界和组织责任为扩展前提", { size: 24, weight: 700, fill: C.accent, anchor: "middle" });
  return svg;
}

const diagrams = [
  ["01-problem-solution", "问题—机制—价值映射", "从企业合同作业痛点到可验证目标价值", problemSolution],
  ["02-user-collaboration", "多角色协作模型", "围绕统一合同任务对象建立职责清晰的人机协同", userCollaboration],
  ["03-functional-architecture", "七大功能域架构", "业务闭环与系统治理共同支撑企业合同风险作业", functionalArchitecture],
  ["04-contract-review-flow", "合同审查端到端流程", "从文件接入到整改关闭与管理分析的完整链路", contractReviewFlow],
  ["05-technical-architecture", "六层目标技术架构", "模块化、可替换、可演进的企业级技术体系", technicalArchitecture],
  ["06-private-deployment", "企业私有化部署拓扑", "明确网络路径、数据落点、信任边界与运维组件", privateDeployment],
  ["07-agent-sequence", "双 Agent 协同时序", "并行专业审查、逐风险取证、交叉验证与人工裁决", agentSequence],
  ["08-rag-evidence-flow", "RAG 逐风险证据链", "混合检索、融合过滤、适用性门禁与无依据降级", ragEvidenceFlow],
  ["09-parsing-data-flow", "合同解析与结构化数据流", "从多格式文件到可定位字段与标准风险契约", parsingDataFlow],
  ["10-core-er", "核心数据实体关系", "合同版本、风险证据、知识版本与责任事件一体化", coreEr],
  ["11-security-layers", "纵深安全防护体系", "从身份、应用、数据到模型、运行和审计的分层控制", securityLayers],
  ["12-implementation-roadmap", "四阶段实施路线", "业务闭环、可信增强、企业交付与规模运营逐级推进", implementationRoadmap],
  ["13-testing-loop", "测试与验收闭环", "冻结基线、量化测量、门禁判定与缺陷复测", testingLoop],
  ["14-product-roadmap", "产品演进路线", "业务、技术与治理能力同步演进", productRoadmap],
];

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  for (const [name, title, subtitle, createBody] of diagrams) {
    await renderDiagram({ name, title, subtitle, bodySvg: createBody() });
    process.stdout.write(`generated ${name}.png\n`);
  }

  const files = fs.readdirSync(OUTPUT_DIR).filter((file) => file.endsWith(".png")).sort();
  if (files.length !== diagrams.length) {
    throw new Error(`expected ${diagrams.length} PNG files, found ${files.length}`);
  }

  const contactLayers = [];
  for (const [index, file] of files.entries()) {
    const filePath = path.join(OUTPUT_DIR, file);
    const image = sharp(filePath);
    const metadata = await image.metadata();
    const stats = await image.stats();
    const pixelSpread = Math.max(...stats.channels.map((channel) => channel.max - channel.min));
    const bytes = fs.statSync(filePath).size;
    if (metadata.width < 1800 || metadata.height < 1000 || bytes < 10000 || pixelSpread < 40) {
      throw new Error(`invalid diagram ${file}: ${metadata.width}x${metadata.height}, ${bytes} bytes, spread ${pixelSpread}`);
    }
    process.stdout.write(`verified ${file}: ${metadata.width}x${metadata.height}, ${bytes} bytes\n`);
    contactLayers.push({
      input: await sharp(filePath).resize(500, 300, { fit: "fill" }).png().toBuffer(),
      left: (index % 4) * 500,
      top: Math.floor(index / 4) * 300,
    });
  }

  const contactPath = path.join(os.tmpdir(), "contract-solution-diagrams-contact.png");
  await sharp({
    create: { width: 2000, height: 1200, channels: 3, background: C.bg },
  }).composite(contactLayers).png().toFile(contactPath);
  process.stdout.write(`contact sheet ${contactPath}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
