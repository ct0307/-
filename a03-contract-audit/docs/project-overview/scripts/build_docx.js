const fs = require('fs')
const path = require('path')
const { createRequire } = require('module')

const ROOT = path.resolve(__dirname, '..')
const DOCS_ROOT = path.resolve(ROOT, '..')
const CONTENT_PATH = path.join(ROOT, 'content', 'overview.md')
const OUTPUT_PATH = path.join(ROOT, '契鉴_项目概要介绍.docx')
const requireFromSolution = createRequire(path.join(DOCS_ROOT, 'contract-solution', 'package.json'))
const {
  AlignmentType,
  BorderStyle,
  Document,
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
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} = requireFromSolution('docx')

const PAGE = {
  width: 11906,
  height: 16838,
  margin: 1134,
  header: 560,
  footer: 560,
  contentWidth: 9638,
}

const COLOR = {
  navy: '28364A',
  navySoft: 'E8EDF2',
  red: 'A33A32',
  gold: '9A7628',
  goldSoft: 'F4EFDF',
  text: '30343B',
  secondary: '5F6772',
  muted: '7C8490',
  line: 'CBD2D9',
  surface: 'F7F8F9',
  white: 'FFFFFF',
}

function chineseFont() {
  return { ascii: 'Microsoft YaHei', hAnsi: 'Microsoft YaHei', eastAsia: '微软雅黑' }
}

function titleFont() {
  return { ascii: 'Microsoft YaHei', hAnsi: 'Microsoft YaHei', eastAsia: '微软雅黑' }
}

function splitCells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((item) => item.trim())
}

function isSeparator(line) {
  return splitCells(line).every((cell) => /^:?-{3,}:?$/.test(cell))
}

function parseContent(sourcePath) {
  const lines = fs.readFileSync(sourcePath, 'utf8').replace(/\r\n/g, '\n').split('\n')
  const pages = []
  let page = null

  function requirePage(lineNumber) {
    if (!page) throw new Error(`content before first page at line ${lineNumber}`)
  }

  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index]
    const line = raw.trim()
    if (!line) continue

    if (line.startsWith('# PAGE:')) {
      page = { title: line.slice(7).trim(), blocks: [] }
      pages.push(page)
      continue
    }

    requirePage(index + 1)

    const meta = line.match(/^@(eyebrow|subtitle|doctype|meta|date)\s+(.+)$/)
    if (meta) {
      page.blocks.push({ type: meta[1], text: meta[2] })
      continue
    }

    if (line.startsWith('## ')) {
      page.blocks.push({ type: 'heading', text: line.slice(3).trim() })
      continue
    }

    if (line.startsWith('> ')) {
      page.blocks.push({ type: 'callout', text: line.slice(2).trim() })
      continue
    }

    const image = line.match(/^!\[(.+)]\((.+)\)$/)
    if (image) {
      page.blocks.push({
        type: 'image',
        caption: image[1].trim(),
        imagePath: path.resolve(path.dirname(sourcePath), image[2].trim()),
      })
      continue
    }

    if (line.startsWith('|')) {
      const tableLines = [line]
      while (index + 1 < lines.length && lines[index + 1].trim().startsWith('|')) {
        index += 1
        tableLines.push(lines[index].trim())
      }
      if (tableLines.length < 2 || !isSeparator(tableLines[1])) {
        throw new Error(`invalid markdown table near line ${index + 1}`)
      }
      const header = splitCells(tableLines[0])
      const rows = tableLines.slice(2).map(splitCells)
      if (rows.some((row) => row.length !== header.length)) {
        throw new Error(`table column mismatch near line ${index + 1}`)
      }
      page.blocks.push({ type: 'table', header, rows })
      continue
    }

    const ordered = line.match(/^\d+\.\s+(.+)$/)
    if (ordered) {
      page.blocks.push({ type: 'list', ordered: true, text: ordered[1] })
      continue
    }

    if (line.startsWith('- ')) {
      page.blocks.push({ type: 'list', ordered: false, text: line.slice(2).trim() })
      continue
    }

    page.blocks.push({ type: 'paragraph', text: line })
  }

  if (pages.length !== 12) throw new Error(`expected 12 pages, found ${pages.length}`)
  return pages
}

function inlineRuns(text, options = {}) {
  const runs = []
  const regex = /\*\*(.+?)\*\*/g
  let cursor = 0
  let match
  while ((match = regex.exec(text)) !== null) {
    if (match.index > cursor) runs.push(new TextRun({ text: text.slice(cursor, match.index), ...options }))
    runs.push(new TextRun({ text: match[1], bold: true, color: COLOR.navy, ...options }))
    cursor = regex.lastIndex
  }
  if (cursor < text.length) runs.push(new TextRun({ text: text.slice(cursor), ...options }))
  return runs.length ? runs : [new TextRun({ text, ...options })]
}

function pngDimensions(buffer) {
  if (buffer.toString('ascii', 1, 4) !== 'PNG') throw new Error('only PNG images are supported')
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) }
}

function fitImage(width, height, maxWidth, maxHeight) {
  const scale = Math.min(maxWidth / width, maxHeight / height, 1)
  return { width: Math.round(width * scale), height: Math.round(height * scale) }
}

function borders(color = COLOR.line, size = 4) {
  const edge = { style: BorderStyle.SINGLE, color, size }
  return { top: edge, bottom: edge, left: edge, right: edge, insideHorizontal: edge, insideVertical: edge }
}

function noBorders() {
  const edge = { style: BorderStyle.NONE, color: COLOR.white, size: 0 }
  return { top: edge, bottom: edge, left: edge, right: edge, insideHorizontal: edge, insideVertical: edge }
}

function tableWidths(columnCount) {
  if (columnCount === 2) return [2900, PAGE.contentWidth - 2900]
  if (columnCount === 3) return [2200, 3550, PAGE.contentWidth - 5750]
  const base = Math.floor(PAGE.contentWidth / columnCount)
  return Array.from({ length: columnCount }, (_, index) => index === columnCount - 1 ? PAGE.contentWidth - base * index : base)
}

function cellParagraph(text, bold = false, color = COLOR.text, size = 18) {
  return new Paragraph({
    children: inlineRuns(text, { bold, color, size, font: chineseFont() }),
    alignment: AlignmentType.LEFT,
    spacing: { before: 0, after: 0, line: 235 },
    widowControl: true,
  })
}

function makeTable(block) {
  const widths = tableWidths(block.header.length)
  const rows = [block.header, ...block.rows].map((values, rowIndex) => new TableRow({
    tableHeader: rowIndex === 0,
    cantSplit: true,
    children: values.map((value, cellIndex) => new TableCell({
      width: { size: widths[cellIndex], type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      shading: { type: ShadingType.CLEAR, fill: rowIndex === 0 ? COLOR.navySoft : (rowIndex % 2 === 0 ? COLOR.surface : COLOR.white) },
      margins: { top: 70, bottom: 70, left: 110, right: 110 },
      borders: borders(),
      children: [cellParagraph(value, rowIndex === 0, rowIndex === 0 ? COLOR.navy : COLOR.text, rowIndex === 0 ? 18 : 17)],
    })),
  }))

  return new Table({
    width: { size: PAGE.contentWidth, type: WidthType.DXA },
    columnWidths: widths,
    rows,
  })
}

function imageParagraph(block, maxWidth = 590, maxHeight = 330) {
  if (!fs.existsSync(block.imagePath)) throw new Error(`missing image: ${block.imagePath}`)
  const data = fs.readFileSync(block.imagePath)
  const size = pngDimensions(data)
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 70, after: 35 },
      keepNext: true,
      children: [new ImageRun({
        type: 'png',
        data,
        transformation: fitImage(size.width, size.height, maxWidth, maxHeight),
        altText: { title: block.caption, description: block.caption, name: path.basename(block.imagePath) },
      })],
    }),
    new Paragraph({
      style: 'Caption',
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 90 },
      children: [new TextRun({ text: block.caption, font: chineseFont(), size: 16, color: COLOR.muted })],
    }),
  ]
}

function makeImageGrid(imageBlocks) {
  const columnWidths = [PAGE.contentWidth / 2, PAGE.contentWidth / 2]
  const rows = []
  for (let index = 0; index < imageBlocks.length; index += 2) {
    const pair = imageBlocks.slice(index, index + 2)
    while (pair.length < 2) pair.push(null)
    rows.push(new TableRow({
      cantSplit: true,
      children: pair.map((block, cellIndex) => new TableCell({
        width: { size: columnWidths[cellIndex], type: WidthType.DXA },
        margins: { top: 50, bottom: 50, left: 70, right: 70 },
        borders: noBorders(),
        verticalAlign: VerticalAlign.TOP,
        children: block ? imageParagraph(block, 270, 175) : [new Paragraph('')],
      })),
    }))
  }
  return new Table({
    width: { size: PAGE.contentWidth, type: WidthType.DXA },
    columnWidths,
    borders: noBorders(),
    rows,
  })
}

function pageTitle(title, pageNumber) {
  return [
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      keepNext: true,
      spacing: { before: 40, after: 30 },
      children: [
        new TextRun({ text: String(pageNumber).padStart(2, '0'), color: COLOR.red, size: 20, bold: true, font: titleFont() }),
        new TextRun({ text: '  ' + title, color: COLOR.navy, size: 34, bold: true, font: titleFont() }),
      ],
    }),
    new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, color: COLOR.gold, size: 8, space: 5 } },
      spacing: { before: 0, after: 120 },
      children: [new TextRun('')],
    }),
  ]
}

function coverChildren(page) {
  const values = Object.fromEntries(page.blocks.filter((block) => block.type !== 'meta').map((block) => [block.type, block.text]))
  const metas = page.blocks.filter((block) => block.type === 'meta').map((block) => block.text)
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 850, after: 260 },
      children: [new TextRun({ text: values.eyebrow, bold: true, color: COLOR.gold, size: 22, font: titleFont() })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 80 },
      children: [new TextRun({ text: page.title, bold: true, color: COLOR.navy, size: 64, font: titleFont() })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 180 },
      children: [new TextRun({ text: values.subtitle, bold: true, color: COLOR.text, size: 30, font: titleFont() })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 430 },
      children: [new TextRun({ text: values.doctype, color: COLOR.red, size: 28, bold: true, font: titleFont() })],
    }),
    new Paragraph({
      border: {
        top: { style: BorderStyle.SINGLE, color: COLOR.gold, size: 8, space: 8 },
        bottom: { style: BorderStyle.SINGLE, color: COLOR.gold, size: 8, space: 8 },
      },
      shading: { type: ShadingType.CLEAR, fill: COLOR.goldSoft },
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 180, line: 300 },
      indent: { left: 520, right: 520 },
      children: [new TextRun({ text: metas[0], color: COLOR.navy, size: 20, bold: true, font: chineseFont() })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 120, after: 90 },
      children: [new TextRun({ text: metas[1], color: COLOR.secondary, size: 20, font: chineseFont() })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 520, after: 0 },
      children: [new TextRun({ text: values.date, color: COLOR.muted, size: 19, font: chineseFont() })],
    }),
  ]
}

function blockToWord(block) {
  if (block.type === 'heading') {
    return [new Paragraph({
      heading: HeadingLevel.HEADING_2,
      keepNext: true,
      spacing: { before: 120, after: 60 },
      children: [new TextRun({ text: block.text, bold: true, color: COLOR.red, size: 24, font: titleFont() })],
    })]
  }
  if (block.type === 'callout') {
    return [new Paragraph({
      shading: { type: ShadingType.CLEAR, fill: COLOR.goldSoft },
      border: { left: { style: BorderStyle.SINGLE, color: COLOR.gold, size: 14, space: 8 } },
      indent: { left: 160, right: 120 },
      spacing: { before: 0, after: 120, line: 260 },
      children: [new TextRun({ text: block.text, bold: true, color: COLOR.navy, size: 20, font: chineseFont() })],
    })]
  }
  if (block.type === 'paragraph') {
    return [new Paragraph({
      alignment: AlignmentType.JUSTIFIED,
      widowControl: true,
      spacing: { before: 0, after: 75, line: 260 },
      children: inlineRuns(block.text, { size: 19, color: COLOR.text, font: chineseFont() }),
    })]
  }
  if (block.type === 'list') {
    return [new Paragraph({
      numbering: { reference: block.ordered ? 'numbered-list' : 'bullet-list', level: 0 },
      spacing: { before: 0, after: 42, line: 240 },
      children: inlineRuns(block.text, { size: 18, color: COLOR.text, font: chineseFont() }),
    })]
  }
  if (block.type === 'table') return [makeTable(block), new Paragraph({ text: '', spacing: { after: 80 } })]
  if (block.type === 'image') return imageParagraph(block)
  throw new Error(`unsupported block type: ${block.type}`)
}

function renderPage(page, pageIndex) {
  if (pageIndex === 0) return coverChildren(page)
  const children = [...pageTitle(page.title, pageIndex + 1)]
  for (let index = 0; index < page.blocks.length; index += 1) {
    if (page.blocks[index].type === 'image') {
      const images = []
      while (index < page.blocks.length && page.blocks[index].type === 'image') {
        images.push(page.blocks[index])
        index += 1
      }
      index -= 1
      if (images.length === 1) children.push(...imageParagraph(images[0]))
      else children.push(makeImageGrid(images))
      continue
    }
    children.push(...blockToWord(page.blocks[index]))
  }
  return children
}

function runningHeader() {
  return new Header({
    children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      border: { bottom: { style: BorderStyle.SINGLE, color: COLOR.line, size: 4, space: 3 } },
      spacing: { after: 0 },
      children: [new TextRun({ text: '契鉴  |  企业合同合规智能审查系统', color: COLOR.muted, size: 15, font: chineseFont() })],
    })],
  })
}

function runningFooter() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 0 },
      children: [
        new TextRun({ text: '项目概要介绍  |  ', color: COLOR.muted, size: 15, font: chineseFont() }),
        new TextRun({ children: [PageNumber.CURRENT], color: COLOR.muted, size: 15, font: chineseFont() }),
      ],
    })],
  })
}

function emptyHeader() {
  return new Header({ children: [new Paragraph('')] })
}

function emptyFooter() {
  return new Footer({ children: [new Paragraph('')] })
}

function styles() {
  return {
    default: {
      document: {
        run: { font: chineseFont(), size: 19, color: COLOR.text },
        paragraph: { spacing: { after: 75, line: 260 }, alignment: AlignmentType.JUSTIFIED },
      },
    },
    paragraphStyles: [
      {
        id: 'Normal', name: 'Normal', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: chineseFont(), size: 19, color: COLOR.text },
        paragraph: { spacing: { after: 75, line: 260 }, alignment: AlignmentType.JUSTIFIED },
      },
      {
        id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: titleFont(), size: 34, bold: true, color: COLOR.navy },
        paragraph: { spacing: { before: 40, after: 80 }, outlineLevel: 0, keepNext: true },
      },
      {
        id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: titleFont(), size: 24, bold: true, color: COLOR.red },
        paragraph: { spacing: { before: 120, after: 60 }, outlineLevel: 1, keepNext: true },
      },
      {
        id: 'Caption', name: 'Caption', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { font: chineseFont(), size: 16, color: COLOR.muted },
        paragraph: { spacing: { before: 0, after: 90, line: 220 }, alignment: AlignmentType.CENTER },
      },
    ],
  }
}

function numbering() {
  return {
    config: [
      {
        reference: 'bullet-list',
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: '•',
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 460, hanging: 240 } }, run: { font: chineseFont(), color: COLOR.red, size: 18 } },
        }],
      },
      {
        reference: 'numbered-list',
        levels: [{
          level: 0,
          format: LevelFormat.DECIMAL,
          text: '%1.',
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 500, hanging: 260 } }, run: { font: chineseFont(), color: COLOR.red, size: 18 } },
        }],
      },
    ],
  }
}

async function main() {
  const pages = parseContent(CONTENT_PATH)
  const children = []
  pages.forEach((page, index) => {
    if (index > 0) children.push(new Paragraph({ children: [new PageBreak()] }))
    children.push(...renderPage(page, index))
  })

  const doc = new Document({
    title: '契鉴——企业合同合规智能审查系统项目概要介绍',
    subject: '2026“数字马力杯”第十三届浙江省大学生服务外包创新应用大赛 A03 项目概要介绍',
    creator: '契鉴项目团队',
    lastModifiedBy: '契鉴项目团队',
    description: '面向比赛评审的企业合同合规智能审查系统项目速览',
    keywords: 'A03, 契鉴, 合同合规, 双Agent, RAG, 私有化',
    features: { updateFields: true },
    styles: styles(),
    numbering: numbering(),
    sections: [{
      properties: {
        titlePage: true,
        page: {
          size: { width: PAGE.width, height: PAGE.height },
          margin: { top: PAGE.margin, bottom: PAGE.margin, left: PAGE.margin, right: PAGE.margin, header: PAGE.header, footer: PAGE.footer },
          pageNumbers: { start: 1 },
        },
      },
      headers: { first: emptyHeader(), default: runningHeader() },
      footers: { first: emptyFooter(), default: runningFooter() },
      children,
    }],
  })

  const buffer = await Packer.toBuffer(doc)
  fs.writeFileSync(OUTPUT_PATH, buffer)
  process.stdout.write(`generated=${OUTPUT_PATH} pages=${pages.length} bytes=${buffer.length}\n`)
}

main().catch((error) => {
  console.error(error.stack || error)
  process.exitCode = 1
})
