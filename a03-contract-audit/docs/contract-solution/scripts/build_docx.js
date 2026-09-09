const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  Bookmark,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  Header,
  HeadingLevel,
  ImageRun,
  LevelFormat,
  LineRuleType,
  PageBreak,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableOfContents,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} = require("docx");

const ROOT = path.resolve(__dirname, "..");

const PAGE = {
  width: 11906,
  height: 16838,
  marginTop: 1080,
  marginBottom: 1080,
  marginLeft: 1080,
  marginRight: 1080,
  header: 560,
  footer: 560,
};

let CONTENT_WIDTH_DXA = PAGE.width - PAGE.marginLeft - PAGE.marginRight;
const TABLE_INDENT_DXA = 120;
let TABLE_WIDTH_DXA = CONTENT_WIDTH_DXA - TABLE_INDENT_DXA;

const COLOR = {
  primary: "245B78",
  secondary: "4C7A92",
  accent: "C48A2C",
  text: "1F2933",
  muted: "52616B",
  border: "C9D4DC",
  tableHeader: "E8F0F4",
  panel: "F4F6F9",
};

// narrative_proposal + A4/project-palette named overrides.
const STYLE = {
  bodySize: 19,
  bodyAfter: 60,
  bodyLine: 250,
  h1Size: 32,
  h2Size: 28,
  h3Size: 24,
  tableSize: 17,
  captionSize: 17,
  headerSize: 16,
  codeSize: 17,
  firstLine: 0,
  winningStyle: false,
};

const LEGACY_TABLES = new Set([
  "02-industry-market.md|痛点|根因|直接影响|方案响应",
  "02-industry-market.md|能力维度|e签宝|法大大 iContract|百度合同智能处理|契鉴目标方案",
  "03-users-requirements.md|角色|主要目标|核心任务|关注信息|责任边界",
  "03-users-requirements.md|编号|需求|优先级|前置依赖|验收标准",
  "05-overall-solution.md|功能域|核心职责|主要输入|主要输出|关键依赖",
  "06-functional-process.md|状态|进入条件|允许操作|正常出口|异常出口",
  "07-architecture-deployment.md|区域|组件|入站路径|出站限制|主要数据",
  "08-dual-agent.md|参与者|主要职责|禁止越界|典型输出",
  "09-rag-evidence.md|类别|示例|用途|可靠性规则",
  "10-parsing-risk.md|要素组|核心字段|标准化规则|证据要求",
  "11-data-security.md|实体|主键与关键字段|主要关系|索引建议|生命周期|敏感等级",
  "13-implementation.md|阶段|核心目标|关键门禁|主要证据",
  "14-testing-acceptance.md|指标|目标阈值|判定规则|证据",
  "14-testing-acceptance.md|指标|目标阈值|失败判定",
  "15-feasibility-risk.md|风险|概率/影响|触发信号|预防措施|应急措施|责任角色",
]);

const REDESIGN_TABLES = new Set([
  "01-project-overview.md|赛题要求|契鉴的回应|对应证据",
  "02-requirements-goals.md|角色|需要完成的判断|现有障碍|系统支持|最终责任",
  "03-overall-solution.md|层级|核心职责|主要输入|主要输出|失败处理",
  "04-core-functions.md|处理阶段|用户动作|系统处理|可见结果|异常出口",
  "04-core-functions.md|异常场景|系统反应|用户可采取的动作|保留证据",
  "05-key-technology.md|技术环节|选择依据|实际处理|输出|限制",
  "05-key-technology.md|证据状态|触发条件|系统处置|人工动作",
  "06-implementation-application.md|环境或组件|项目用途|当前证据|交付条件",
  "07-verification-conclusion.md|赛题指标|当前状态|本轮证据摘要|仍需条件",
]);

const PROFESSIONAL_TABLES = new Set([
  "02-requirements-analysis.md|角色|主要任务|关注信息|系统支持|责任边界",
  "02-requirements-analysis.md|优先级|需求范围|验收重点",
  "03-overall-design.md|层级|核心职责|主要输入|主要输出|失败处理",
  "04-functional-design.md|处理阶段|用户动作|系统处理|可见结果|异常出口",
  "04-functional-design.md|异常场景|系统反应|用户可采取的动作|保留记录",
  "05-technical-implementation.md|技术环节|选择依据|处理方式|输出|限制",
  "05-technical-implementation.md|参数域|当前基线值|设计作用|调整要求",
  "05-technical-implementation.md|证据状态|触发条件|系统处置|人工动作",
  "06-data-security.md|数据对象|关键内容|主要关系|保护要求|保留策略",
  "07-deployment-operations.md|环境或组件|主要用途|配置要求|验收条件",
  "08-testing-acceptance.md|测试类别|测试对象|判定依据|证据形式",
  "08-testing-acceptance.md|接口域|主要接口|输入|输出与状态",
  "08-testing-acceptance.md|术语|含义",
]);

const PROFILES = {
  legacy: {
    contentDir: path.join(ROOT, "content"),
    outputPath: path.join(ROOT, "契鉴_项目详细方案.docx"),
    expectedFiles: 17,
    expectedChapters: 17,
    expectedFigures: 23,
    keepAsTable: LEGACY_TABLES,
    version: "V1.0",
    date: "2026 年 7 月",
    bodyLine: 250,
    eventTitle: "浙江省职业技能大赛 · 外包赛道",
    eventTitleSize: 24,
    subject: "浙江省职业技能大赛外包赛道 A03 项目详细方案",
    chapterPageBreaks: false,
  },
  redesign: {
    contentDir: path.join(ROOT, "content-redesign"),
    outputPath: path.resolve(ROOT, "../..", "契鉴_项目详细方案_重构版.docx"),
    expectedFiles: 7,
    expectedChapters: 7,
    expectedFigures: 23,
    keepAsTable: REDESIGN_TABLES,
    version: "V2.0",
    date: "2026 年 9 月",
    bodyLine: 280,
    eventTitle: "2026“数字马力杯”第十三届浙江省大学生服务外包创新应用大赛",
    eventTitleSize: 20,
    subject: "2026“数字马力杯”第十三届浙江省大学生服务外包创新应用大赛 A03 项目详细方案",
    chapterPageBreaks: true,
    sectionPageBreaks: new Set(),
    layout: {
      page: { marginTop: 1134, marginBottom: 1134, marginLeft: 1134, marginRight: 1134, header: 851, footer: 992 },
      color: { primary: "000000", secondary: "000000", accent: "000000", text: "000000", muted: "555555", border: "000000", tableHeader: "FFFFFF", panel: "FFFFFF" },
      style: { bodySize: 24, bodyAfter: 120, bodyLine: 360, h1Size: 30, h2Size: 28, h3Size: 24, tableSize: 21, captionSize: 21, headerSize: 18, codeSize: 21, firstLine: 480, winningStyle: true },
    },
  },
  professional: {
    contentDir: path.join(ROOT, "content-professional"),
    outputPath: path.resolve(ROOT, "../..", "outputs", "professional-redesign", "契鉴_项目详细方案_专业重制版.docx"),
    expectedFiles: 8,
    expectedChapters: 8,
    expectedFigures: 23,
    keepAsTable: PROFESSIONAL_TABLES,
    version: "V3.1",
    date: "2026 年 9 月",
    bodyLine: 280,
    eventTitle: "企业级合同合规审查系统建设项目",
    eventTitleSize: 20,
    subject: "契鉴企业级合同合规审查与多维报表生成智能体系统项目详细方案",
    coverMeta: [
      "项目编号  A03",
      "项目单位  海康-南湖研究院",
      "项目团队  豪到你了团队",
    ],
    chapterPageBreaks: true,
    sectionPageBreaks: new Set(["附录D 参考文献"]),
    layout: {
      page: { marginTop: 1134, marginBottom: 1134, marginLeft: 1134, marginRight: 1134, header: 851, footer: 992 },
      color: { primary: "000000", secondary: "000000", accent: "000000", text: "000000", muted: "555555", border: "000000", tableHeader: "FFFFFF", panel: "FFFFFF" },
      style: { bodySize: 24, bodyAfter: 120, bodyLine: 360, h1Size: 30, h2Size: 28, h3Size: 24, tableSize: 21, captionSize: 21, headerSize: 18, codeSize: 21, firstLine: 480, tocLine: 260, winningStyle: true },
    },
  },
};

function parseArgs(argv) {
  let profile = "legacy";
  let output;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg.startsWith("--profile=")) profile = arg.slice("--profile=".length);
    else if (arg === "--profile") profile = argv[++index];
    else if (arg.startsWith("--output=")) output = arg.slice("--output=".length);
    else if (arg === "--output") output = argv[++index];
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (!PROFILES[profile]) throw new Error(`unknown profile: ${profile}`);
  if (output === undefined) return { profile, config: PROFILES[profile] };
  if (!output) throw new Error("--output requires a path");
  return {
    profile,
    config: { ...PROFILES[profile], outputPath: path.resolve(ROOT, output) },
  };
}

function eastAsiaFont() {
  return { ascii: "Arial", hAnsi: "Arial", eastAsia: STYLE.winningStyle ? "楷体" : "宋体", cs: "Arial" };
}

function headingFont(level = 2) {
  const eastAsia = STYLE.winningStyle ? (level === 1 ? "黑体" : "宋体") : "微软雅黑";
  return { ascii: "Arial", hAnsi: "Arial", eastAsia, cs: "Arial" };
}

function tableFont() {
  return { ascii: "Arial", hAnsi: "Arial", eastAsia: STYLE.winningStyle ? "宋体" : "宋体", cs: "Arial" };
}

function sanitizeBookmark(value) {
  const ascii = value.replace(/[^A-Za-z0-9_]/g, "_").replace(/_+/g, "_");
  return (`b_${ascii}`).slice(0, 36);
}

function pngDimensions(buffer) {
  if (buffer.length < 24 || buffer.toString("ascii", 1, 4) !== "PNG") {
    throw new Error("only PNG images are supported");
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function fitImage(width, height) {
  const maxWidth = 540;
  const maxHeight = 640;
  const scale = Math.min(maxWidth / width, maxHeight / height, 1);
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

function splitInline(value) {
  const result = [];
  const token = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s]+)/g;
  let cursor = 0;
  let match;
  while ((match = token.exec(value)) !== null) {
    if (match.index > cursor) result.push({ type: "text", value: value.slice(cursor, match.index) });
    const raw = match[0];
    if (raw.startsWith("**")) result.push({ type: "bold", value: raw.slice(2, -2) });
    else if (raw.startsWith("`")) result.push({ type: "code", value: raw.slice(1, -1) });
    else {
      const trailing = raw.match(/[，。；、）】]+$/)?.[0] || "";
      const url = trailing ? raw.slice(0, -trailing.length) : raw;
      result.push({ type: "url", value: url });
      if (trailing) result.push({ type: "text", value: trailing });
    }
    cursor = token.lastIndex;
  }
  if (cursor < value.length) result.push({ type: "text", value: value.slice(cursor) });
  return result;
}

function inlineRuns(value, options = {}) {
  return splitInline(value).map((part) => {
    if (part.type === "url") {
      return new ExternalHyperlink({
        link: part.value,
        children: [new TextRun({ text: part.value, style: "Hyperlink", font: options.font || eastAsiaFont(), size: options.size || STYLE.bodySize })],
      });
    }
    return new TextRun({
      text: part.value,
      bold: part.type === "bold" || options.bold,
      font: part.type === "code" ? { ascii: "Consolas", hAnsi: "Consolas", eastAsia: "等线" } : (options.font || eastAsiaFont()),
      size: options.size || (part.type === "code" ? STYLE.codeSize : STYLE.bodySize),
      color: options.color || COLOR.text,
      shading: !STYLE.winningStyle && part.type === "code" ? { type: ShadingType.CLEAR, fill: "EEF3F6" } : undefined,
    });
  });
}

function parseTableCells(line, file, lineNumber) {
  if (!line.startsWith("|") || !line.endsWith("|")) {
    throw new Error(`${file}:${lineNumber}: malformed table row`);
  }
  return line.slice(1, -1).split("|").map((cell) => cell.trim());
}

function isSeparatorRow(cells) {
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function parseMarkdown(filePath) {
  const file = path.basename(filePath);
  const lines = fs.readFileSync(filePath, "utf8").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const lineNumber = index + 1;
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim(), file, lineNumber });
      index += 1;
      continue;
    }
    if (/^#{4,}\s/.test(line)) throw new Error(`${file}:${lineNumber}: heading level above 3 is not supported`);

    const image = line.match(/^!\[([^\]]+)\]\(([^)]+)\)$/);
    if (image) {
      const imagePath = path.resolve(path.dirname(filePath), image[2]);
      if (!fs.existsSync(imagePath)) throw new Error(`${file}:${lineNumber}: missing image ${image[2]}`);
      blocks.push({ type: "image", caption: image[1], imagePath, file, lineNumber });
      index += 1;
      continue;
    }
    if (line.startsWith("![")) throw new Error(`${file}:${lineNumber}: malformed image directive`);

    const fence = line.match(/^```([A-Za-z0-9_-]*)$/);
    if (fence) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && lines[index] !== "```") {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index >= lines.length) throw new Error(`${file}:${lineNumber}: unclosed code fence`);
      index += 1;
      blocks.push({ type: "code", language: fence[1], lines: codeLines, file, lineNumber });
      continue;
    }

    if (line.startsWith("|")) {
      const tableLines = [];
      while (index < lines.length && lines[index].startsWith("|")) {
        tableLines.push({ line: lines[index], lineNumber: index + 1 });
        index += 1;
      }
      if (tableLines.length < 2) throw new Error(`${file}:${lineNumber}: table requires a separator row`);
      const header = parseTableCells(tableLines[0].line, file, tableLines[0].lineNumber);
      const separator = parseTableCells(tableLines[1].line, file, tableLines[1].lineNumber);
      if (header.length !== separator.length || !isSeparatorRow(separator)) {
        throw new Error(`${file}:${tableLines[1].lineNumber}: invalid table separator`);
      }
      const rows = tableLines.slice(2).map((entry) => parseTableCells(entry.line, file, entry.lineNumber));
      if (rows.some((row) => row.length !== header.length)) throw new Error(`${file}:${lineNumber}: inconsistent table column count`);
      blocks.push({ type: "table", header, rows, file, lineNumber });
      continue;
    }

    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      blocks.push({ type: "list", ordered: false, text: bullet[1], file, lineNumber });
      index += 1;
      continue;
    }
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      blocks.push({ type: "list", ordered: true, text: ordered[1], file, lineNumber });
      index += 1;
      continue;
    }

    if (line === "<!-- pagebreak -->" || line === "\\pagebreak") {
      blocks.push({ type: "pagebreak", file, lineNumber });
      index += 1;
      continue;
    }
    if (line === "---") {
      blocks.push({ type: "rule", file, lineNumber });
      index += 1;
      continue;
    }
    if (/^```|^>\s|^<[^!]/.test(line)) throw new Error(`${file}:${lineNumber}: unsupported Markdown syntax`);

    blocks.push({ type: "paragraph", text: line.trim(), file, lineNumber });
    index += 1;
  }
  return blocks;
}

function calculateColumnWidths(header, rows) {
  const count = header.length;
  const min = count >= 6 ? 680 : count >= 5 ? 800 : 920;
  const allRows = [header, ...rows];
  const weights = header.map((_, column) => {
    const maxLength = Math.max(...allRows.map((row) => [...(row[column] || "")].length));
    return Math.max(4, Math.min(maxLength, 30));
  });
  const widths = Array(count).fill(min);
  let remaining = TABLE_WIDTH_DXA - min * count;
  const totalWeight = weights.reduce((sum, value) => sum + value, 0);
  widths.forEach((_, index) => {
    const extra = index === widths.length - 1 ? remaining : Math.floor((TABLE_WIDTH_DXA - min * count) * weights[index] / totalWeight);
    widths[index] += extra;
    remaining -= extra;
  });
  return widths;
}

function tableParagraph(value, bold = false) {
  return new Paragraph({
    children: inlineRuns(value, { size: STYLE.tableSize, bold, font: tableFont() }),
    alignment: AlignmentType.LEFT,
    spacing: { before: 0, after: 0, line: STYLE.winningStyle ? 240 : 260 },
  });
}

function makeTable(block) {
  const widths = calculateColumnWidths(block.header, block.rows);
  const border = { style: BorderStyle.SINGLE, color: COLOR.border, size: 4 };
  const borders = { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border };
  const rowToWord = (cells, header = false) => new TableRow({
    tableHeader: header,
    cantSplit: true,
    children: cells.map((cell, index) => new TableCell({
      width: { size: widths[index], type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      margins: { top: 70, bottom: 70, left: 100, right: 100 },
      shading: header && !STYLE.winningStyle ? { type: ShadingType.CLEAR, fill: COLOR.tableHeader } : undefined,
      children: [tableParagraph(cell, header)],
    })),
  });
  return new Table({
    rows: [rowToWord(block.header, true), ...block.rows.map((row) => rowToWord(row, false))],
    width: { size: TABLE_WIDTH_DXA, type: WidthType.DXA },
    indent: { size: TABLE_INDENT_DXA, type: WidthType.DXA },
    columnWidths: widths,
    margins: { top: 70, bottom: 70, left: 100, right: 100 },
    layout: TableLayoutType.FIXED,
    borders,
  });
}

function tableAsGroupedItems(block) {
  const children = [];
  block.rows.forEach((row) => {
    const label = row[0] || block.header[0];
    const details = row.slice(1)
      .map((value, index) => value ? `${block.header[index + 1]}：${value}` : "")
      .filter(Boolean)
      .join("；");
    children.push(new Paragraph({
      children: [
        new TextRun({ text: label, bold: true, color: COLOR.text, font: eastAsiaFont(), size: STYLE.bodySize }),
        new TextRun({ text: details ? `${STYLE.winningStyle ? "：" : "｜"}${details}` : "", color: COLOR.text, font: eastAsiaFont(), size: STYLE.bodySize }),
      ],
      spacing: { before: 0, after: STYLE.winningStyle ? 80 : 40, line: STYLE.bodyLine, lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined },
      indent: STYLE.winningStyle ? { firstLine: STYLE.firstLine } : { left: 260, hanging: 0 },
      border: STYLE.winningStyle ? undefined : { left: { style: BorderStyle.SINGLE, color: COLOR.border, size: 8, space: 8 } },
    }));
  });
  return children;
}

function coverChildren(config) {
  const centered = AlignmentType.CENTER;
  if (STYLE.winningStyle) {
    const coverMeta = config.coverMeta || [
      "赛题编号  A03",
      "命题单位  海康-南湖研究院",
      "参赛团队  豪到你了团队",
    ];
    return [
      new Paragraph({ spacing: { before: 900, after: 300 }, alignment: centered, children: [new TextRun({ text: config.eventTitle, color: COLOR.text, font: headingFont(2), size: 24 })] }),
      new Paragraph({ spacing: { before: 0, after: 140 }, alignment: centered, children: [new TextRun({ text: "契鉴", bold: true, color: COLOR.text, font: headingFont(1), size: 44 })] }),
      new Paragraph({ spacing: { before: 0, after: 140 }, alignment: centered, children: [new TextRun({ text: "企业级合同合规审查与多维报表生成智能体系统", bold: true, color: COLOR.text, font: headingFont(2), size: 30 })] }),
      new Paragraph({ spacing: { before: 0, after: 480 }, alignment: centered, children: [new TextRun({ text: "项目详细方案", color: COLOR.text, font: headingFont(2), size: 30 })] }),
      ...[...coverMeta, `文档版本  ${config.version}`]
        .map((text) => new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text, color: COLOR.text, font: headingFont(2), size: 24 })] })),
      new Paragraph({ spacing: { before: 180, after: 0 }, alignment: centered, children: [new TextRun({ text: config.date, color: COLOR.text, font: headingFont(2), size: 24 })] }),
      new Paragraph({ children: [new PageBreak()] }),
      new Paragraph({ alignment: centered, spacing: { before: 80, after: 260 }, children: [new TextRun({ text: "目录", bold: true, color: COLOR.text, font: headingFont(1), size: 32 })] }),
      new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-2" }),
      new Paragraph({ children: [new PageBreak()] }),
    ];
  }
  return [
    new Paragraph({ spacing: { before: 1100, after: 260 }, alignment: centered, children: [new TextRun({ text: config.eventTitle, bold: true, color: COLOR.accent, font: headingFont(), size: config.eventTitleSize })] }),
    new Paragraph({ spacing: { before: 0, after: 120 }, alignment: centered, children: [new TextRun({ text: "契鉴", bold: true, color: COLOR.primary, font: headingFont(), size: 58 })] }),
    new Paragraph({ spacing: { before: 0, after: 120 }, alignment: centered, children: [new TextRun({ text: "企业级合同合规审查与多维报表生成智能体系统", bold: true, color: COLOR.text, font: headingFont(), size: 30 })] }),
    new Paragraph({ spacing: { before: 0, after: 420 }, alignment: centered, children: [new TextRun({ text: "项目详细方案", color: COLOR.secondary, font: headingFont(), size: 28 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: "赛题编号  A03", bold: true, color: COLOR.primary, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: "命题单位  海康-南湖研究院", color: COLOR.text, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: "参赛团队  豪到你了团队", color: COLOR.text, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: `文档版本  ${config.version}`, color: COLOR.text, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 180, after: 0 }, alignment: centered, children: [new TextRun({ text: config.date, color: COLOR.muted, font: eastAsiaFont(), size: 20 })] }),
    new Paragraph({ children: [new PageBreak()] }),
    new Paragraph({ alignment: centered, spacing: { before: 80, after: 260 }, children: [new TextRun({ text: "目录", bold: true, color: COLOR.primary, font: headingFont(), size: 34 })] }),
    new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-2" }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function runningHeader() {
  return new Header({
    children: [new Paragraph({
      alignment: STYLE.winningStyle ? AlignmentType.CENTER : AlignmentType.RIGHT,
      spacing: { after: 0 },
      children: [new TextRun({ text: STYLE.winningStyle ? "契鉴项目详细方案" : "契鉴  |  项目详细方案", color: COLOR.muted, font: headingFont(2), size: STYLE.headerSize })],
    })],
  });
}

function runningFooter(config) {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: STYLE.winningStyle
        ? [new TextRun({ children: [PageNumber.CURRENT], color: COLOR.muted, font: headingFont(2), size: STYLE.headerSize })]
        : [
          new TextRun({ text: `${config.version}  |  契鉴项目详细方案  |  第 `, color: COLOR.muted, font: eastAsiaFont(), size: 16 }),
          new TextRun({ children: [PageNumber.CURRENT], color: COLOR.muted, font: eastAsiaFont(), size: 16 }),
          new TextRun({ text: " 页", color: COLOR.muted, font: eastAsiaFont(), size: 16 }),
        ],
    })],
  });
}

function emptyHeader() {
  return new Header({ children: [new Paragraph({ text: "" })] });
}

function emptyFooter() {
  return new Footer({ children: [new Paragraph({ text: "" })] });
}

function blockToWord(block, stats, keepAsTable, sectionPageBreaks = new Set()) {
  if (block.type === "heading") {
    const headingMap = { 1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2, 3: HeadingLevel.HEADING_3 };
    const bookmarkId = sanitizeBookmark(`${block.file}_${block.lineNumber}_${block.text}`);
    if (block.level === 1) stats.chapters += 1;
    return [new Paragraph({
      heading: headingMap[block.level],
      pageBreakBefore: block.level === 2 && sectionPageBreaks.has(block.text),
      keepNext: true,
      children: [new Bookmark({ id: bookmarkId, children: [new TextRun({ text: block.text })] })],
    })];
  }
  if (block.type === "paragraph") {
    const isSourceEntry = /^\[S\d{2}\]\s/.test(block.text);
    return [new Paragraph({
      children: inlineRuns(block.text, { size: isSourceEntry ? (STYLE.winningStyle ? STYLE.captionSize : 17) : STYLE.bodySize }),
      alignment: AlignmentType.JUSTIFIED,
      widowControl: true,
      indent: !isSourceEntry && STYLE.firstLine ? { firstLine: STYLE.firstLine } : undefined,
      spacing: {
        before: 0,
        after: isSourceEntry ? (STYLE.winningStyle ? 60 : 30) : STYLE.bodyAfter,
        line: isSourceEntry ? (STYLE.winningStyle ? 300 : 220) : STYLE.bodyLine,
        lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined,
      },
    })];
  }
  if (block.type === "list") {
    return [new Paragraph({
      children: inlineRuns(block.text),
      numbering: { reference: block.ordered ? "numbered-list" : "bullet-list", level: 0 },
      spacing: {
        before: 0,
        after: STYLE.winningStyle ? STYLE.bodyAfter : 30,
        line: STYLE.winningStyle ? STYLE.bodyLine : 250,
        lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined,
      },
    })];
  }
  if (block.type === "table") {
    const key = `${block.file}|${block.header.join("|")}`;
    if (keepAsTable.has(key)) {
      stats.tables += 1;
      return [makeTable(block), new Paragraph({ text: "", spacing: { before: 0, after: 100 } })];
    }
    stats.groupedTables += 1;
    return tableAsGroupedItems(block);
  }
  if (block.type === "image") {
    const data = fs.readFileSync(block.imagePath);
    const dimensions = pngDimensions(data);
    const fitted = fitImage(dimensions.width, dimensions.height);
    const bookmarkId = sanitizeBookmark(`figure_${stats.figures + 1}_${block.caption}`);
    stats.figures += 1;
    return [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        keepNext: true,
        spacing: { before: 100, after: 60, line: 240, lineRule: LineRuleType.AUTO },
        children: [new ImageRun({
          type: "png",
          data,
          transformation: fitted,
          altText: { title: block.caption, description: block.caption, name: path.basename(block.imagePath) },
        })],
      }),
      new Paragraph({
        style: "Caption",
        alignment: AlignmentType.CENTER,
        keepLines: true,
        spacing: { before: 0, after: 180, line: STYLE.winningStyle ? 300 : 260, lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined },
        children: [new Bookmark({ id: bookmarkId, children: [new TextRun({ text: block.caption })] })],
      }),
    ];
  }
  if (block.type === "pagebreak") return [new Paragraph({ children: [new PageBreak()] })];
  if (block.type === "code") {
    return [new Paragraph({
      children: block.lines.map((line, index) => new TextRun({
        text: line || " ",
        break: index === 0 ? undefined : 1,
        font: { ascii: "Consolas", hAnsi: "Consolas", eastAsia: "等线" },
        size: STYLE.codeSize,
        color: COLOR.text,
      })),
      shading: STYLE.winningStyle ? undefined : { type: ShadingType.CLEAR, fill: "EEF3F6" },
      border: {
        top: { style: BorderStyle.SINGLE, color: COLOR.border, size: 4, space: 6 },
        bottom: { style: BorderStyle.SINGLE, color: COLOR.border, size: 4, space: 6 },
        left: { style: BorderStyle.SINGLE, color: STYLE.winningStyle ? COLOR.border : COLOR.primary, size: STYLE.winningStyle ? 4 : 12, space: STYLE.winningStyle ? 6 : 8 },
        right: { style: BorderStyle.SINGLE, color: COLOR.border, size: 4, space: 6 },
      },
      spacing: { before: 80, after: 160, line: STYLE.winningStyle ? 300 : 260, lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined },
      indent: { left: 160, right: 160 },
      keepLines: true,
    })];
  }
  if (block.type === "rule") {
    return [new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, color: COLOR.border, size: 6, space: 6 } }, spacing: { before: 80, after: 120 } })];
  }
  throw new Error(`${block.file}:${block.lineNumber}: unsupported block type ${block.type}`);
}

function documentStyles() {
  const bodyParagraph = {
    spacing: {
      before: 0,
      after: STYLE.bodyAfter,
      line: STYLE.bodyLine,
      lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined,
    },
    alignment: AlignmentType.JUSTIFIED,
  };
  const heading1 = {
    run: { font: headingFont(1), size: STYLE.h1Size, bold: true, color: STYLE.winningStyle ? COLOR.text : COLOR.primary },
    paragraph: { spacing: { before: STYLE.winningStyle ? 360 : 260, after: STYLE.winningStyle ? 160 : 140 }, keepNext: true, outlineLevel: 0 },
  };
  const heading2 = {
    run: { font: headingFont(2), size: STYLE.h2Size, bold: true, color: STYLE.winningStyle ? COLOR.text : COLOR.primary },
    paragraph: { spacing: { before: STYLE.winningStyle ? 240 : 180, after: STYLE.winningStyle ? 120 : 80 }, keepNext: true, outlineLevel: 1 },
  };
  const heading3 = {
    run: { font: headingFont(3), size: STYLE.h3Size, bold: true, color: STYLE.winningStyle ? COLOR.text : COLOR.secondary },
    paragraph: { spacing: { before: STYLE.winningStyle ? 160 : 120, after: STYLE.winningStyle ? 80 : 60 }, keepNext: true, outlineLevel: 2 },
  };
  return {
    default: {
      document: {
        run: { font: eastAsiaFont(), size: STYLE.bodySize, color: COLOR.text },
        paragraph: bodyParagraph,
      },
      heading1,
      heading2,
      heading3,
    },
    paragraphStyles: [
      {
        id: "Normal",
        name: "Normal",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: eastAsiaFont(), size: STYLE.bodySize, color: COLOR.text },
        paragraph: bodyParagraph,
      },
      {
        id: "Caption",
        name: "Caption",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: eastAsiaFont(), size: STYLE.captionSize, color: COLOR.muted },
        paragraph: { spacing: { before: 0, after: 180, line: STYLE.winningStyle ? 300 : 260, lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined }, alignment: AlignmentType.CENTER },
      },
      {
        id: "TOC1",
        name: "toc 1",
        basedOn: "Normal",
        next: "Normal",
        run: { font: eastAsiaFont(), size: STYLE.winningStyle ? 21 : 17, color: COLOR.text },
        paragraph: { spacing: { before: 0, after: 0, line: STYLE.tocLine || (STYLE.winningStyle ? 300 : 200), lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined }, keepLines: true },
      },
      {
        id: "TOC2",
        name: "toc 2",
        basedOn: "Normal",
        next: "Normal",
        run: { font: eastAsiaFont(), size: STYLE.winningStyle ? 21 : 16, color: COLOR.muted },
        paragraph: { indent: { left: 260 }, spacing: { before: 0, after: 0, line: STYLE.tocLine || (STYLE.winningStyle ? 300 : 190), lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined }, keepLines: true },
      },
    ],
  };
}

function numbering() {
  return {
    config: [
      {
        reference: "bullet-list",
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: "•",
          alignment: AlignmentType.LEFT,
          style: {
            paragraph: { indent: { left: 500, hanging: 260 }, spacing: { after: STYLE.winningStyle ? STYLE.bodyAfter : 30, line: STYLE.winningStyle ? STYLE.bodyLine : 250, lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined } },
            run: { font: eastAsiaFont(), size: STYLE.bodySize, color: STYLE.winningStyle ? COLOR.text : COLOR.primary },
          },
        }],
      },
      {
        reference: "numbered-list",
        levels: [{
          level: 0,
          format: LevelFormat.DECIMAL,
          text: "%1.",
          alignment: AlignmentType.LEFT,
          style: {
            paragraph: { indent: { left: 500, hanging: 260 }, spacing: { after: STYLE.winningStyle ? STYLE.bodyAfter : 30, line: STYLE.winningStyle ? STYLE.bodyLine : 250, lineRule: STYLE.winningStyle ? LineRuleType.EXACT : undefined } },
            run: { font: eastAsiaFont(), size: STYLE.bodySize, color: STYLE.winningStyle ? COLOR.text : COLOR.primary },
          },
        }],
      },
    ],
  };
}

async function main() {
  const { profile, config } = parseArgs(process.argv.slice(2));
  if (config.layout) {
    Object.assign(PAGE, config.layout.page);
    Object.assign(COLOR, config.layout.color);
    Object.assign(STYLE, config.layout.style);
  } else {
    STYLE.bodyLine = config.bodyLine;
  }
  CONTENT_WIDTH_DXA = PAGE.width - PAGE.marginLeft - PAGE.marginRight;
  TABLE_WIDTH_DXA = CONTENT_WIDTH_DXA - TABLE_INDENT_DXA;
  const files = fs.readdirSync(config.contentDir).filter((file) => /^\d{2}-.*\.md$/.test(file)).sort();
  if (files.length !== config.expectedFiles) {
    throw new Error(`expected ${config.expectedFiles} chapter files, found ${files.length}`);
  }

  const stats = { chapters: 0, figures: 0, tables: 0, groupedTables: 0 };
  const body = [];
  for (const [fileIndex, file] of files.entries()) {
    if (config.chapterPageBreaks && fileIndex > 0) {
      body.push(new Paragraph({ children: [new PageBreak()] }));
    }
    const blocks = parseMarkdown(path.join(config.contentDir, file));
    for (const block of blocks) body.push(...blockToWord(block, stats, config.keepAsTable, config.sectionPageBreaks));
  }
  if (stats.chapters !== config.expectedChapters) {
    throw new Error(`expected ${config.expectedChapters} chapter headings, found ${stats.chapters}`);
  }
  if (stats.figures !== config.expectedFigures) {
    throw new Error(`expected ${config.expectedFigures} figures, found ${stats.figures}`);
  }
  if (stats.tables !== config.keepAsTable.size) {
    throw new Error(`expected ${config.keepAsTable.size} Word tables, found ${stats.tables}`);
  }

  const doc = new Document({
    title: "契鉴——企业级合同合规审查与多维报表生成智能体系统项目详细方案",
    subject: config.subject,
    creator: "豪到你了团队",
    lastModifiedBy: "豪到你了团队",
    description: "企业级合同合规审查智能体系统的目标态需求、设计、实施与验收方案",
    keywords: "A03, 合同合规, 双Agent, RAG, 私有化",
    features: { updateFields: true },
    styles: documentStyles(),
    numbering: numbering(),
    sections: [{
      properties: {
        titlePage: true,
        page: {
          size: { width: PAGE.width, height: PAGE.height },
          margin: {
            top: PAGE.marginTop,
            bottom: PAGE.marginBottom,
            left: PAGE.marginLeft,
            right: PAGE.marginRight,
            header: PAGE.header,
            footer: PAGE.footer,
          },
          pageNumbers: { start: 1 },
        },
      },
      headers: { first: emptyHeader(), default: runningHeader() },
      footers: { first: emptyFooter(), default: runningFooter(config) },
      children: [...coverChildren(config), ...body],
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.mkdirSync(path.dirname(config.outputPath), { recursive: true });
  fs.writeFileSync(config.outputPath, buffer);
  process.stdout.write(`generated ${config.outputPath}\n`);
  process.stdout.write(`profile=${profile} chapters=${stats.chapters} figures=${stats.figures} tables=${stats.tables} groupedTables=${stats.groupedTables} bytes=${buffer.length}\n`);
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
