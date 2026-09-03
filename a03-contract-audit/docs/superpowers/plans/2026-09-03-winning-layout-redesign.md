# 往届获奖风格排版重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将两份重构版参赛材料改为用户确认的“A 高还原往届”排版，详细方案保持 42～46 页、概要介绍保持 9 页，同时保护正文事实、原 DOCX 和 legacy 输出。

**Architecture:** 在现有两个 DOCX 生成器中为 `redesign` profile 注入独立的往届式页面和字体令牌，保留 `legacy` 分支的现有值与行为。两个验证器先增加 OOXML 版式断言形成 RED，再实现生成器形成 GREEN；最后通过 Word COM 真实分页、Poppler 全页渲染和原稿哈希完成验收。

**Tech Stack:** Node.js、docx 9.6.1、Python 3、python-docx、ElementTree、pypdf、PowerShell/Word COM、Poppler。

---

## 文件结构

| 路径 | 职责 |
|---|---|
| `docs/contract-solution/scripts/build_docx.js` | 为详细方案 redesign profile 生成楷体正文、黑色标题、白底表格和朴素页眉页脚 |
| `docs/contract-solution/scripts/validate_document.py` | 验证详细方案 redesign 的 42～46 页、字体字号、边距、颜色和表格底纹 |
| `docs/project-overview/scripts/build_docx.js` | 为概要 redesign profile 移除编号标题、彩色卡片和强调底纹，并改为往届式图文排版 |
| `docs/project-overview/scripts/validate_document.py` | 验证概要 redesign 的 9 页、字体字号、无两位页码标题、无主题色和无彩色底纹 |
| `契鉴_项目详细方案_重构版.docx` | 更新后的详细方案交付物 |
| `docs/project-overview/契鉴_项目概要介绍_重构版.docx` | 更新后的概要介绍交付物 |
| `outputs/materials-redesign/` | 仅存放 PDF、legacy 回归文件、分页 PNG、接触表和临时统计，不进入 Git |

所有命令均从项目根目录 `a03-contract-audit` 执行。使用以下已安装运行时，不安装或升级依赖：

```powershell
$node = 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$python = 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pdftoppm = 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe'
```

### Task 1: 为详细方案建立往届式版式 RED 门禁

**Files:**
- Modify: `docs/contract-solution/scripts/validate_document.py`
- Reference: `docs/superpowers/specs/2026-09-03-winning-layout-redesign.md`
- Test input: `契鉴_项目详细方案_重构版.docx`

- [ ] **Step 1: 把页面参数放入详细方案 profile**

将 `legacy/redesign` 的页数、边距和页眉页脚距离写入各自配置，保持 legacy 原值：

```python
"legacy": {
    # 保留现有字段
    "pages": (40, 50),
    "margins": {"top": "1080", "bottom": "1080", "left": "1080", "right": "1080"},
    "header": "560",
    "footer": "560",
},
"redesign": {
    # 保留现有字段
    "pages": (42, 46),
    "margins": {"top": "1134", "bottom": "1134", "left": "1134", "right": "1134"},
    "header": "851",
    "footer": "992",
},
```

- [ ] **Step 2: 新增样式读取和 redesign 断言**

在 `validate_docx()` 前加入以下函数；它必须从 `word/styles.xml` 读取东亚字体与半点字号，并拒绝原主题色和非白色表格底纹：

```python
def require_style(styles_root: ET.Element, style_id: str, font: str, size: str) -> None:
    style = styles_root.find(f".//w:style[@w:styleId='{style_id}']", NS)
    if style is None:
        fail(f"缺少样式：{style_id}")
    fonts = style.find("w:rPr/w:rFonts", NS)
    size_node = style.find("w:rPr/w:sz", NS)
    if fonts is None or fonts.get(W + "eastAsia") != font:
        fail(f"{style_id} 东亚字体应为 {font}")
    if size_node is None or size_node.get(W + "val") != size:
        fail(f"{style_id} 字号应为 {int(size) / 2:g}pt")


def validate_redesign_layout(archive: zipfile.ZipFile, root: ET.Element) -> None:
    styles_xml = xml_text(archive, "word/styles.xml")
    styles_root = ET.fromstring(styles_xml)
    require_style(styles_root, "Normal", "楷体", "24")
    require_style(styles_root, "Heading1", "黑体", "30")
    require_style(styles_root, "Heading2", "宋体", "28")
    require_style(styles_root, "Heading3", "宋体", "24")
    require_style(styles_root, "Caption", "楷体", "21")

    forbidden_colors = ("245B78", "4C7A92", "C48A2C", "E8F0F4", "F4F6F9")
    document_xml = ET.tostring(root, encoding="unicode")
    if any(color in styles_xml or color in document_xml for color in forbidden_colors):
        fail("redesign 仍包含旧版主题色")

    colored_fills = [
        node.get(W + "fill")
        for node in root.findall(".//w:tbl//w:shd", NS)
        if node.get(W + "fill") not in (None, "auto", "FFFFFF")
    ]
    if colored_fills:
        fail(f"表格仍包含彩色底纹：{colored_fills[0]}")
```

- [ ] **Step 3: 在 DOCX 校验中调用版式门禁**

把固定边距改为读取 `config`，同时检查页眉页脚距离；仅 redesign 调用新增断言：

```python
expected_margins = config["margins"]
if page_margin is None or any(page_margin.get(W + key) != value for key, value in expected_margins.items()):
    fail("页边距与 profile 不一致")
if page_margin.get(W + "header") != config["header"] or page_margin.get(W + "footer") != config["footer"]:
    fail("页眉页脚距离与 profile 不一致")
if profile == "redesign":
    validate_redesign_layout(archive, root)
```

- [ ] **Step 4: 运行旧产物并确认 RED**

```powershell
& $python docs/contract-solution/scripts/validate_document.py --profile redesign '契鉴_项目详细方案_重构版.docx'
```

Expected: 退出码 1，首先报告页边距、楷体 Normal、黑体 Heading1、旧主题色或表格底纹中的至少一项不符合；不得因解析异常失败。

- [ ] **Step 5: 提交详细方案验证门禁**

```powershell
git add docs/contract-solution/scripts/validate_document.py
git diff --cached --check
git commit -m "test: enforce winning-style detail layout"
```

### Task 2: 实现详细方案往届式版式

**Files:**
- Modify: `docs/contract-solution/scripts/build_docx.js`
- Test: `docs/contract-solution/scripts/validate_document.py`

- [ ] **Step 1: 增加 profile 独立版式令牌**

为 `PROFILES.legacy` 保留现有值，为 `PROFILES.redesign` 增加以下 `layout`。后续函数从 `config.layout` 取值，不再通过 `STYLE.bodyLine` 单项突变：

```javascript
layout: {
  page: { marginTop: 1134, marginBottom: 1134, marginLeft: 1134, marginRight: 1134, header: 851, footer: 992 },
  color: { text: "000000", muted: "555555", border: "000000", white: "FFFFFF" },
  font: {
    body: { ascii: "Arial", hAnsi: "Arial", eastAsia: "楷体", cs: "Arial" },
    h1: { ascii: "Arial", hAnsi: "Arial", eastAsia: "黑体", cs: "Arial" },
    heading: { ascii: "Arial", hAnsi: "Arial", eastAsia: "宋体", cs: "Arial" },
    code: { ascii: "Consolas", hAnsi: "Consolas", eastAsia: "等线", cs: "Consolas" },
  },
  size: { body: 24, h1: 30, h2: 28, h3: 24, table: 21, caption: 21, header: 18, code: 21 },
  spacing: { bodyLine: 360, bodyAfter: 100, h1Before: 360, h1After: 160, h2Before: 240, h2After: 120, h3Before: 160, h3After: 80 },
  firstLine: 480,
  winningStyle: true,
},
```

- [ ] **Step 2: 让字体、行内文本和列表读取 layout**

从 `docx` 解构导入中加入 `LineRuleType`。将 `eastAsiaFont()`、`headingFont()`、`inlineRuns()`、`numbering()` 改为接收 `layout`。redesign 普通文字固定黑色，粗体不切换主题色，代码不加底纹；URL 分支继续生成外部超链接：

```javascript
function inlineRuns(value, layout, options = {}) {
  return splitInline(value).map((part) => {
    if (part.type === "url") {
      return new ExternalHyperlink({
        link: part.value,
        children: [new TextRun({ text: part.value, style: "Hyperlink", font: layout.font.body, size: options.size || layout.size.body })],
      });
    }
    return new TextRun({
      text: part.value,
      bold: part.type === "bold" || options.bold,
      font: part.type === "code" ? layout.font.code : layout.font.body,
      size: options.size || (part.type === "code" ? layout.size.code : layout.size.body),
      color: options.color || layout.color.text,
      shading: layout.winningStyle ? undefined : (part.type === "code" ? { type: ShadingType.CLEAR, fill: "EEF3F6" } : undefined),
    });
  });
}
```

项目符号和数字编号使用黑色正文样式。

- [ ] **Step 3: 改造表格、分组条目和代码块**

`makeTable(block, layout)` 对 redesign 使用黑色单线边框、白底和 10.5pt 宋体；表头仅加粗。`tableAsGroupedItems(block, layout)` 移除左侧彩色线和 `｜` 装饰，改为加粗标签加自然说明。代码块 redesign 只保留 0.5pt 黑色外框，不设灰底和彩色左线。

```javascript
const border = { style: BorderStyle.SINGLE, color: layout.color.border, size: layout.winningStyle ? 4 : 4 };
shading: layout.winningStyle ? undefined : (header ? { type: ShadingType.CLEAR, fill: COLOR.tableHeader } : undefined),
```

- [ ] **Step 4: 改造封面、正文块和页眉页脚**

为 `coverChildren(config, layout)` 的 redesign 分支使用黑体 22pt 主标题、宋体 15pt 副标题和全黑文字；目录标题为黑体 16pt。`blockToWord(block, stats, keepAsTable, layout)` 应落实正文 12pt、18pt 行距、首行 480 twip，图片无装饰，图题 10.5pt。`runningHeader(layout)` 仅显示“契鉴项目详细方案”，`runningFooter(config, layout)` 仅显示居中 PAGE 域。

```javascript
new Paragraph({
  children: inlineRuns(block.text, layout),
  alignment: AlignmentType.JUSTIFIED,
  widowControl: true,
  indent: { firstLine: layout.firstLine },
  spacing: { before: 0, after: layout.spacing.bodyAfter, line: layout.spacing.bodyLine, lineRule: LineRuleType.EXACT },
})
```

- [ ] **Step 5: 将文档样式和页面属性接入 layout**

`documentStyles(layout)` 精确生成 `Normal/Heading1/Heading2/Heading3/Caption/TOC1/TOC2`；`main()` 使用 `config.layout` 调用全部渲染函数，并把 section margin 改为 `layout.page`。legacy layout 必须复制当前 PAGE、COLOR、STYLE 和字体值，确保旧版回归不变。

- [ ] **Step 6: 构建并确认详细方案 GREEN**

```powershell
& $node --check docs/contract-solution/scripts/build_docx.js
& $node docs/contract-solution/scripts/build_docx.js --profile redesign
& $python docs/contract-solution/scripts/validate_document.py --profile redesign '契鉴_项目详细方案_重构版.docx'
```

Expected: Node 语法检查退出码 0；生成器报告 7 章、23 图、9 表；验证器返回 PASS，字体与 OOXML 版式门禁通过。

- [ ] **Step 7: 提交详细方案实现**

```powershell
git add docs/contract-solution/scripts/build_docx.js
git diff --cached --check
git commit -m "docs: restyle detail material after winning entry"
```

### Task 3: 为概要介绍建立往届式版式 RED 门禁

**Files:**
- Modify: `docs/project-overview/scripts/validate_document.py`
- Test input: `docs/project-overview/契鉴_项目概要介绍_重构版.docx`

- [ ] **Step 1: 新增概要 redesign 样式断言**

复用 Task 1 的 `require_style()` 结构，断言 `Normal=楷体/24`、`Heading1=黑体/30`、`Heading2=宋体/28`、`Caption=楷体/21`。扫描 `styles.xml` 与 `document.xml`，拒绝 `28364A/A33A32/9A7628/F4EFDF/E8EDF2/F7F8F9`。

- [ ] **Step 2: 新增编号标题和底纹断言**

在现有 headings 统计后加入：

```python
if profile == "redesign" and any(re.match(r"^\d{2}\s+", heading) for heading in headings):
    fail("页面标题仍包含两位补零编号")
```

对 `root.findall(".//w:tbl//w:shd", NS)` 执行与 Task 1 相同的白底检查；无边框图片网格不得误判，因为它不设置 `w:shd`。

- [ ] **Step 3: 检查概要页眉页脚距离**

在 20mm 四边距断言后增加 `header=851`、`footer=992` 的 redesign 检查；legacy 继续检查当前 `560/560`。

- [ ] **Step 4: 运行旧产物并确认 RED**

```powershell
& $python docs/project-overview/scripts/validate_document.py --profile redesign 'docs/project-overview/契鉴_项目概要介绍_重构版.docx'
```

Expected: 退出码 1，报告楷体、黑体、两位补零标题、主题色或表格底纹中的至少一项不符合。

- [ ] **Step 5: 提交概要验证门禁**

```powershell
git add docs/project-overview/scripts/validate_document.py
git diff --cached --check
git commit -m "test: enforce winning-style overview layout"
```

### Task 4: 实现概要介绍往届式版式

**Files:**
- Modify: `docs/project-overview/scripts/build_docx.js`
- Test: `docs/project-overview/scripts/validate_document.py`

- [ ] **Step 1: 为两个 profile 定义独立 layout**

在 `PROFILES` 中加入 `layout`。legacy 复制当前微软雅黑、配色、560 页眉页脚和 9.5pt 正文；redesign 使用下列核心值：

```javascript
layout: {
  winningStyle: true,
  page: { margin: 1134, header: 851, footer: 992, contentWidth: 9638 },
  color: { text: '000000', muted: '555555', border: '000000', white: 'FFFFFF' },
  font: {
    body: { ascii: 'Arial', hAnsi: 'Arial', eastAsia: '楷体' },
    h1: { ascii: 'Arial', hAnsi: 'Arial', eastAsia: '黑体' },
    heading: { ascii: 'Arial', hAnsi: 'Arial', eastAsia: '宋体' },
  },
  size: { body: 24, h1: 30, h2: 28, caption: 21, table: 21, header: 18 },
  spacing: { bodyLine: 360, bodyAfter: 80 },
},
```

- [ ] **Step 2: 将渲染函数改为 config 驱动**

为 `inlineRuns()`、`cellParagraph()`、`makeTable()`、`imageParagraph()`、`makeImageGrid()`、`pageTitle()`、`coverChildren()`、`blockToWord()`、`renderPage()`、`runningHeader()`、`runningFooter()`、`styles()` 和 `numbering()` 增加 `layout` 参数；`main()` 只从当前 config 传入该 layout。

- [ ] **Step 3: 移除 redesign 卡片式视觉**

redesign 的 `pageTitle()` 只返回一个黑色 Heading1，不加入两位补零页码和金色横线。`blockToWord()` 中 callout 改为无边框、无底纹、以“说明：”开头的楷体自然段；普通粗体仍为黑色。状态表使用白底黑线，表头仅加粗。

```javascript
if (layout.winningStyle) {
  return [new Paragraph({
    heading: HeadingLevel.HEADING_1,
    keepNext: true,
    children: [new TextRun({ text: title, font: layout.font.h1, size: layout.size.h1, bold: true, color: layout.color.text })],
  })]
}
```

- [ ] **Step 4: 简化 redesign 封面和页眉页脚**

封面保留现有真实工作台截图，但所有文字改为黑色；主标题黑体 22pt，副标题宋体 15pt，赛事名与日期宋体 12pt。移除金色上下边框和金色底纹元信息框。页眉仅显示“契鉴项目概要介绍”，页脚仅显示居中 PAGE 域，不加横线。

- [ ] **Step 5: 构建并确认概要 GREEN**

```powershell
& $node --check docs/project-overview/scripts/build_docx.js
& $node docs/project-overview/scripts/build_docx.js --profile redesign
& $python docs/project-overview/scripts/validate_document.py --profile redesign 'docs/project-overview/契鉴_项目概要介绍_重构版.docx'
```

Expected: Node 语法检查退出码 0；生成器报告 9 页、8 图；验证器返回 PASS，且无两位补零标题、主题色和彩色表格底纹。

- [ ] **Step 6: 提交概要实现**

```powershell
git add docs/project-overview/scripts/build_docx.js
git diff --cached --check
git commit -m "docs: restyle overview after winning entry"
```

### Task 5: 执行双 profile 构建与内容回归

**Files:**
- Generate only: `outputs/materials-redesign/winning-legacy-detail.docx`
- Generate only: `outputs/materials-redesign/winning-legacy-overview.docx`
- Verify: 四个生成/验证脚本和两份内容源

- [ ] **Step 1: 对四个脚本执行语法检查**

```powershell
& $node --check docs/contract-solution/scripts/build_docx.js
& $node --check docs/project-overview/scripts/build_docx.js
& $python -m py_compile docs/contract-solution/scripts/validate_document.py docs/project-overview/scripts/validate_document.py
```

Expected: 三条命令退出码均为 0。

- [ ] **Step 2: 生成不覆盖原稿的 legacy 回归文件**

```powershell
New-Item -ItemType Directory -Force -Path outputs/materials-redesign | Out-Null
& $node docs/contract-solution/scripts/build_docx.js --profile legacy --output ../../outputs/materials-redesign/winning-legacy-detail.docx
& $node docs/project-overview/scripts/build_docx.js --profile legacy --output ../../outputs/materials-redesign/winning-legacy-overview.docx
```

Expected: 详细方案报告 17 章、23 图、15 表；概要报告 12 页、12 图。

- [ ] **Step 3: 验证 legacy 和 redesign 四份 DOCX**

```powershell
& $python docs/contract-solution/scripts/validate_document.py --profile legacy outputs/materials-redesign/winning-legacy-detail.docx
& $python docs/project-overview/scripts/validate_document.py --profile legacy outputs/materials-redesign/winning-legacy-overview.docx
& $python docs/contract-solution/scripts/validate_document.py --profile redesign '契鉴_项目详细方案_重构版.docx'
& $python docs/project-overview/scripts/validate_document.py --profile redesign 'docs/project-overview/契鉴_项目概要介绍_重构版.docx'
```

Expected: 四条命令全部返回 PASS。

- [ ] **Step 4: 运行语言与内容审计**

```powershell
& $python -m unittest docs/competition-materials/scripts/test_audit_materials.py -v
& $python docs/competition-materials/scripts/audit_materials.py --detail-dir docs/contract-solution/content-redesign --overview docs/project-overview/content/overview-redesign.md
git diff --check
```

Expected: 8 项单元测试通过；真实稿件仍为 7 章、9 页、占位符 0、禁用宣传语 0、最大长段相似度不高于 0.80；Git 无空白错误。

### Task 6: Word 真实分页与单变量调优

**Files:**
- Modify: `契鉴_项目详细方案_重构版.docx`
- Modify: `docs/project-overview/契鉴_项目概要介绍_重构版.docx`
- Generate only: `outputs/materials-redesign/契鉴_项目详细方案_往届式.pdf`
- Generate only: `outputs/materials-redesign/契鉴_项目概要介绍_往届式.pdf`
- Conditionally modify: 两个 `build_docx.js` 中的 redesign 间距或图片尺寸令牌

- [ ] **Step 1: 更新目录、页码并导出 PDF**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File docs/contract-solution/scripts/update_word_fields.ps1 -DocxPath '契鉴_项目详细方案_重构版.docx' -PdfPath 'outputs/materials-redesign/契鉴_项目详细方案_往届式.pdf'
powershell -NoProfile -ExecutionPolicy Bypass -File docs/contract-solution/scripts/update_word_fields.ps1 -DocxPath 'docs/project-overview/契鉴_项目概要介绍_重构版.docx' -PdfPath 'outputs/materials-redesign/契鉴_项目概要介绍_往届式.pdf'
```

Expected: Word 正常打开并保存两份生成文件；详细方案报告 42～46 页，概要报告 9 页。

- [ ] **Step 2: 当页数不合格时按固定顺序单变量调优**

不得修改 12pt 正文、18pt 行距、A4 和 20mm 页边距。每轮只改一个变量并重新执行 Task 6 Step 1：

1. 详细方案先在 80～120 twip 内调整正文段后距。
2. 仍不合格时在 560～640 px 内调整 `fitImage()` 最大高度。
3. 概要溢出时先减少标题段后距，再调整当前页图片最大高度；不得把正文降到 12pt 以下。
4. 每次调整后重新运行对应 redesign DOCX/PDF 验证，不叠加未经验证的修改。

- [ ] **Step 3: 使用 PDF 运行最终结构验证**

```powershell
& $python docs/contract-solution/scripts/validate_document.py --profile redesign '契鉴_项目详细方案_重构版.docx' 'outputs/materials-redesign/契鉴_项目详细方案_往届式.pdf'
& $python docs/project-overview/scripts/validate_document.py --profile redesign 'docs/project-overview/契鉴_项目概要介绍_重构版.docx' 'outputs/materials-redesign/契鉴_项目概要介绍_往届式.pdf'
```

Expected: 详细方案返回 7 章、42～46 页并识别七个独立章首页；概要返回 9 页；两条命令均 PASS。

- [ ] **Step 4: 提交分页后的两份 DOCX 与必要调优**

```powershell
git add docs/contract-solution/scripts/build_docx.js docs/project-overview/scripts/build_docx.js '契鉴_项目详细方案_重构版.docx' 'docs/project-overview/契鉴_项目概要介绍_重构版.docx'
git diff --cached --check
git commit -m "docs: regenerate materials in winning style"
```

确认暂存区不包含 `outputs/`、内容源、原 DOCX 或参考附件。

### Task 7: 全页视觉验收与最终收尾

**Files:**
- Generate only: `outputs/materials-redesign/detail-pages-winning/`
- Generate only: `outputs/materials-redesign/overview-pages-winning/`
- Generate only: `outputs/materials-redesign/*-winning-contact-*.png`
- Verify: 两份重构版 DOCX、两份 PDF、两份原 DOCX

- [ ] **Step 1: 以 144 dpi 渲染全部页面**

```powershell
New-Item -ItemType Directory -Force -Path outputs/materials-redesign/detail-pages-winning,outputs/materials-redesign/overview-pages-winning | Out-Null
& $pdftoppm -png -r 144 'outputs/materials-redesign/契鉴_项目详细方案_往届式.pdf' 'outputs/materials-redesign/detail-pages-winning/page'
& $pdftoppm -png -r 144 'outputs/materials-redesign/契鉴_项目概要介绍_往届式.pdf' 'outputs/materials-redesign/overview-pages-winning/page'
(Get-ChildItem outputs/materials-redesign/detail-pages-winning -Filter 'page-*.png').Count
(Get-ChildItem outputs/materials-redesign/overview-pages-winning -Filter 'page-*.png').Count
```

Expected: 详细方案 PNG 数为 42～46，概要 PNG 数为 9；命令不经过 `pdftoppm.cmd` 中文路径包装器。

- [ ] **Step 2: 生成接触表和像素边界统计**

复用 `outputs/materials-redesign/make_contact_sheets.py` 的 `page_metrics()` 与 `create_sheets()`，仅把末尾输入目录改为 `detail-pages-winning/overview-pages-winning`，前缀改为 `detail-winning/overview-winning`。该脚本和输出继续保持未跟踪。

```powershell
& $python outputs/materials-redesign/make_contact_sheets.py
```

Expected: 每页都有非空 bbox 和合理 ink ratio；生成覆盖全部页面的接触表。

- [ ] **Step 3: 逐页检查视觉与内容边界**

使用图片查看工具检查全部接触表，并放大检查：封面、目录、七个章首页、全部 9 张详细方案表格、跨页表格、23 张详细方案图片、概要 9 页和 8 张图片。逐项确认：

- 无深蓝、红、金主题标题或彩色卡片。
- 正文为清晰楷体，标题为黑色宋体/黑体，表格白底黑线。
- 无裁切、重叠、图片变形、标题孤行、图题跨页和异常空白页。
- 页眉页脚简洁，目录页码与实际章首页一致。

发现问题时回到 Task 6，每轮只调整一个版式变量，重新生成、验证并渲染受影响的全部页面。

- [ ] **Step 4: 复核原稿哈希**

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Users\chentao\Desktop\浙江省外包赛\a03-contract-audit\契鉴_项目详细方案.docx','docs/contract-solution/契鉴_项目详细方案.docx','docs/project-overview/契鉴_项目概要介绍.docx' | ForEach-Object { $_.Hash + '  ' + $_.Path }
```

Expected:

```text
4752FE64A45B2591726AADC5203B3ADC75416DE611D4F5C1EA62FCD95A07E230  顶层/详细方案原稿
4752FE64A45B2591726AADC5203B3ADC75416DE611D4F5C1EA62FCD95A07E230  docs/contract-solution/详细方案原稿
AFE0A9ECD457901AB9E91FF0352DEA451BFC490F5A77405DDCBB4712C2863449  docs/project-overview/概要原稿
```

- [ ] **Step 5: 执行最终验证集**

```powershell
& $python -m unittest docs/competition-materials/scripts/test_audit_materials.py -v
& $python docs/competition-materials/scripts/audit_materials.py --detail-dir docs/contract-solution/content-redesign --overview docs/project-overview/content/overview-redesign.md
& $python docs/contract-solution/scripts/validate_document.py --profile legacy outputs/materials-redesign/winning-legacy-detail.docx
& $python docs/project-overview/scripts/validate_document.py --profile legacy outputs/materials-redesign/winning-legacy-overview.docx
& $python docs/contract-solution/scripts/validate_document.py --profile redesign '契鉴_项目详细方案_重构版.docx' 'outputs/materials-redesign/契鉴_项目详细方案_往届式.pdf'
& $python docs/project-overview/scripts/validate_document.py --profile redesign 'docs/project-overview/契鉴_项目概要介绍_重构版.docx' 'outputs/materials-redesign/契鉴_项目概要介绍_往届式.pdf'
& $node --check docs/contract-solution/scripts/build_docx.js
& $node --check docs/project-overview/scripts/build_docx.js
git diff --check
git status --short
```

Expected: 8 项语言审计测试通过；四个文档验证均 PASS；两次 Node 语法检查和 `git diff --check` 退出码为 0；Git 只显示预期提交历史和未跟踪的 `outputs/`。

- [ ] **Step 6: 核对提交与推送边界**

```powershell
git log --oneline origin/codex/materials-redesign..HEAD
git status --short --branch
```

Expected: 提交历史包含设计、验证门禁、两个生成器和最终 DOCX 提交；`outputs/` 未暂存。不要创建 PR、合并、强推或推送，除非用户另行明确授权。
