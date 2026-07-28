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
const CONTENT_DIR = path.join(ROOT, "content");
const OUTPUT_PATH = path.join(ROOT, "契鉴_项目详细方案.docx");

const PAGE = {
  width: 11906,
  height: 16838,
  marginTop: 1440,
  marginBottom: 1440,
  marginLeft: 1474,
  marginRight: 1474,
  header: 720,
  footer: 720,
};

const CONTENT_WIDTH_DXA = PAGE.width - PAGE.marginLeft - PAGE.marginRight;
const TABLE_INDENT_DXA = 120;
const TABLE_WIDTH_DXA = CONTENT_WIDTH_DXA - TABLE_INDENT_DXA;

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
  bodySize: 21,
  bodyAfter: 160,
  bodyLine: 320,
  h1Size: 32,
  h2Size: 28,
  h3Size: 24,
  tableSize: 17,
  captionSize: 18,
};

const KEEP_AS_TABLE = new Set([
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

function eastAsiaFont() {
  return { ascii: "Arial", hAnsi: "Arial", eastAsia: "宋体", cs: "Arial" };
}

function headingFont() {
  return { ascii: "Arial", hAnsi: "Arial", eastAsia: "微软雅黑", cs: "Arial" };
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
  const maxWidth = 570;
  const maxHeight = 610;
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
        children: [new TextRun({ text: part.value, style: "Hyperlink", font: eastAsiaFont(), size: options.size || STYLE.bodySize })],
      });
    }
    return new TextRun({
      text: part.value,
      bold: part.type === "bold" || options.bold,
      font: part.type === "code" ? { ascii: "Consolas", hAnsi: "Consolas", eastAsia: "等线" } : eastAsiaFont(),
      size: options.size || STYLE.bodySize,
      color: part.type === "code" ? COLOR.primary : options.color || COLOR.text,
      shading: part.type === "code" ? { type: ShadingType.CLEAR, fill: "EEF3F6" } : undefined,
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
    children: inlineRuns(value, { size: STYLE.tableSize, bold }),
    alignment: AlignmentType.LEFT,
    spacing: { before: 0, after: 0, line: 280 },
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
      margins: { top: 90, bottom: 90, left: 120, right: 120 },
      shading: header ? { type: ShadingType.CLEAR, fill: COLOR.tableHeader } : undefined,
      children: [tableParagraph(cell, header)],
    })),
  });
  return new Table({
    rows: [rowToWord(block.header, true), ...block.rows.map((row) => rowToWord(row, false))],
    width: { size: TABLE_WIDTH_DXA, type: WidthType.DXA },
    indent: { size: TABLE_INDENT_DXA, type: WidthType.DXA },
    columnWidths: widths,
    margins: { top: 90, bottom: 90, left: 120, right: 120 },
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
        new TextRun({ text: label, bold: true, color: COLOR.primary, font: eastAsiaFont(), size: STYLE.bodySize }),
        new TextRun({ text: details ? `｜${details}` : "", color: COLOR.text, font: eastAsiaFont(), size: STYLE.bodySize }),
      ],
      spacing: { before: 0, after: 100, line: 290 },
      indent: { left: 260, hanging: 0 },
      border: { left: { style: BorderStyle.SINGLE, color: COLOR.border, size: 8, space: 8 } },
    }));
  });
  return children;
}

function coverChildren() {
  const centered = AlignmentType.CENTER;
  return [
    new Paragraph({ spacing: { before: 1100, after: 260 }, alignment: centered, children: [new TextRun({ text: "浙江省职业技能大赛 · 外包赛道", bold: true, color: COLOR.accent, font: headingFont(), size: 24 })] }),
    new Paragraph({ spacing: { before: 0, after: 120 }, alignment: centered, children: [new TextRun({ text: "契鉴", bold: true, color: COLOR.primary, font: headingFont(), size: 58 })] }),
    new Paragraph({ spacing: { before: 0, after: 120 }, alignment: centered, children: [new TextRun({ text: "企业级合同合规审查与多维报表生成智能体系统", bold: true, color: COLOR.text, font: headingFont(), size: 30 })] }),
    new Paragraph({ spacing: { before: 0, after: 420 }, alignment: centered, children: [new TextRun({ text: "项目详细方案", color: COLOR.secondary, font: headingFont(), size: 28 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: "赛题编号  A03", bold: true, color: COLOR.primary, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: "命题单位  海康-南湖研究院", color: COLOR.text, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: "参赛团队  豪到你了团队", color: COLOR.text, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 0, after: 100 }, alignment: centered, children: [new TextRun({ text: "文档版本  V1.0", color: COLOR.text, font: eastAsiaFont(), size: 22 })] }),
    new Paragraph({ spacing: { before: 180, after: 0 }, alignment: centered, children: [new TextRun({ text: "2026 年 7 月", color: COLOR.muted, font: eastAsiaFont(), size: 20 })] }),
    new Paragraph({ children: [new PageBreak()] }),
    new Paragraph({ alignment: centered, spacing: { before: 80, after: 260 }, children: [new TextRun({ text: "目录", bold: true, color: COLOR.primary, font: headingFont(), size: 34 })] }),
    new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function runningHeader() {
  return new Header({
    children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      spacing: { after: 0 },
      children: [new TextRun({ text: "契鉴  |  项目详细方案", color: COLOR.muted, font: headingFont(), size: 17 })],
    })],
  });
}

function runningFooter() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: [
        new TextRun({ text: "V1.0  |  契鉴项目详细方案  |  第 ", color: COLOR.muted, font: eastAsiaFont(), size: 16 }),
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

function blockToWord(block, stats) {
  if (block.type === "heading") {
    const headingMap = { 1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2, 3: HeadingLevel.HEADING_3 };
    const bookmarkId = sanitizeBookmark(`${block.file}_${block.lineNumber}_${block.text}`);
    if (block.level === 1) stats.chapters += 1;
    return [new Paragraph({
      heading: headingMap[block.level],
      pageBreakBefore: block.level === 1,
      keepNext: true,
      children: [new Bookmark({ id: bookmarkId, children: [new TextRun({ text: block.text })] })],
    })];
  }
  if (block.type === "paragraph") {
    return [new Paragraph({
      children: inlineRuns(block.text),
      alignment: AlignmentType.JUSTIFIED,
      widowControl: true,
      spacing: { before: 0, after: STYLE.bodyAfter, line: STYLE.bodyLine },
    })];
  }
  if (block.type === "list") {
    return [new Paragraph({
      children: inlineRuns(block.text),
      numbering: { reference: block.ordered ? "numbered-list" : "bullet-list", level: 0 },
      spacing: { before: 0, after: 80, line: 290 },
    })];
  }
  if (block.type === "table") {
    const key = `${block.file}|${block.header.join("|")}`;
    if (KEEP_AS_TABLE.has(key)) {
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
        spacing: { before: 100, after: 60 },
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
        spacing: { before: 0, after: 180, line: 260 },
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
        size: 17,
        color: COLOR.text,
      })),
      shading: { type: ShadingType.CLEAR, fill: "EEF3F6" },
      border: {
        top: { style: BorderStyle.SINGLE, color: COLOR.border, size: 4, space: 6 },
        bottom: { style: BorderStyle.SINGLE, color: COLOR.border, size: 4, space: 6 },
        left: { style: BorderStyle.SINGLE, color: COLOR.primary, size: 12, space: 8 },
        right: { style: BorderStyle.SINGLE, color: COLOR.border, size: 4, space: 6 },
      },
      spacing: { before: 80, after: 160, line: 260 },
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
  return {
    default: {
      document: {
        run: { font: eastAsiaFont(), size: STYLE.bodySize, color: COLOR.text },
        paragraph: { spacing: { after: STYLE.bodyAfter, line: STYLE.bodyLine }, alignment: AlignmentType.JUSTIFIED },
      },
    },
    paragraphStyles: [
      {
        id: "Normal",
        name: "Normal",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: eastAsiaFont(), size: STYLE.bodySize, color: COLOR.text },
        paragraph: { spacing: { before: 0, after: STYLE.bodyAfter, line: STYLE.bodyLine }, alignment: AlignmentType.JUSTIFIED },
      },
      {
        id: "Heading1",
        name: "Heading 1",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: headingFont(), size: STYLE.h1Size, bold: true, color: COLOR.primary },
        paragraph: { spacing: { before: 360, after: 200 }, keepNext: true, outlineLevel: 0 },
      },
      {
        id: "Heading2",
        name: "Heading 2",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: headingFont(), size: STYLE.h2Size, bold: true, color: COLOR.primary },
        paragraph: { spacing: { before: 240, after: 120 }, keepNext: true, outlineLevel: 1 },
      },
      {
        id: "Heading3",
        name: "Heading 3",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: headingFont(), size: STYLE.h3Size, bold: true, color: COLOR.secondary },
        paragraph: { spacing: { before: 160, after: 80 }, keepNext: true, outlineLevel: 2 },
      },
      {
        id: "Caption",
        name: "Caption",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: eastAsiaFont(), size: STYLE.captionSize, color: COLOR.muted },
        paragraph: { spacing: { before: 0, after: 180, line: 260 }, alignment: AlignmentType.CENTER },
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
            paragraph: { indent: { left: 540, hanging: 280 }, spacing: { after: 80, line: 290 } },
            run: { font: eastAsiaFont(), size: STYLE.bodySize, color: COLOR.primary },
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
            paragraph: { indent: { left: 540, hanging: 280 }, spacing: { after: 80, line: 290 } },
            run: { font: eastAsiaFont(), size: STYLE.bodySize, color: COLOR.primary },
          },
        }],
      },
    ],
  };
}

async function main() {
  const files = fs.readdirSync(CONTENT_DIR).filter((file) => /^\d{2}-.*\.md$/.test(file)).sort();
  if (files.length !== 17) throw new Error(`expected 17 chapter files, found ${files.length}`);

  const stats = { chapters: 0, figures: 0, tables: 0, groupedTables: 0 };
  const body = [];
  for (const file of files) {
    const blocks = parseMarkdown(path.join(CONTENT_DIR, file));
    for (const block of blocks) body.push(...blockToWord(block, stats));
  }
  if (stats.chapters !== 17) throw new Error(`expected 17 chapter headings, found ${stats.chapters}`);
  if (stats.figures !== 23) throw new Error(`expected 23 figures, found ${stats.figures}`);
  if (stats.tables !== KEEP_AS_TABLE.size) throw new Error(`expected ${KEEP_AS_TABLE.size} Word tables, found ${stats.tables}`);

  const doc = new Document({
    title: "契鉴——企业级合同合规审查与多维报表生成智能体系统项目详细方案",
    subject: "浙江省职业技能大赛外包赛道 A03 项目详细方案",
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
      footers: { first: emptyFooter(), default: runningFooter() },
      children: [...coverChildren(), ...body],
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(OUTPUT_PATH, buffer);
  process.stdout.write(`generated ${OUTPUT_PATH}\n`);
  process.stdout.write(`chapters=${stats.chapters} figures=${stats.figures} tables=${stats.tables} groupedTables=${stats.groupedTables} bytes=${buffer.length}\n`);
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
