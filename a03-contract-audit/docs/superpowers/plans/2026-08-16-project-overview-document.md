# 契鉴项目概要介绍 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 参考往届 A19 概要介绍的内容形式，制作并验收一份 12 页、适用于比赛评审的《契鉴_项目概要介绍.docx》。

**Architecture:** 使用独立内容源保存 12 页概要正文，使用 `docx 9.6.1` 生成固定 A4 版式并复用详细方案中的 PNG 图示和系统截图。独立 Python 校验器检查页数、章节、事实口径、图片、页眉页脚和 OOXML 结构；Word/PDF 渲染用于最终逐页视觉检查。

**Tech Stack:** Markdown、Node.js、docx-js 9.6.1、Python、python-docx、pypdf、Microsoft Word/PowerPoint 渲染能力

---

## 文件结构

- Create: `docs/project-overview/content/overview.md`：12 页概要正文和图像引用的唯一内容源。
- Create: `docs/project-overview/scripts/build_docx.js`：解析内容、构造 A4 页面、表格、图片、页眉页脚并生成 Word。
- Create: `docs/project-overview/scripts/validate_document.py`：验证 DOCX/PDF 结构、事实、页数和素材完整性。
- Create: `docs/project-overview/README.md`：记录生成、校验与交付命令。
- Create: `docs/project-overview/契鉴_项目概要介绍.docx`：最终 Word 交付物。
- Create: `docs/project-overview/契鉴_项目概要介绍.pdf`：用于视觉复核和便捷预览的同步版。
- Reuse: `docs/contract-solution/assets/diagrams/*.png`：业务、架构、安全和路线图。
- Reuse: `docs/contract-solution/assets/screenshots/*.png`：真实系统界面。

### Task 1: 编写 12 页概要内容源

**Files:**
- Create: `docs/project-overview/content/overview.md`

- [x] **Step 1: 按页面建立 12 个一级标题**

标题依次为：封面、前言、项目创意、总体方案、功能简介、核心业务流程、技术架构与开发环境、应用对象与典型场景、项目优势与安全体系、验证情况与责任边界、结语与发展方向、系统关键界面展示。

- [x] **Step 2: 写入经过事实核对的正文**

正文必须使用 `PROGRESS.md` 和 `docs/contract-solution/content/` 的稳定口径，明确写出 13 张数据库表、40 条 `/api/` 路由、后端 `125 passed, 1 skipped`、前端 `11 passed, 3 skipped`，不得把 OCR 准确率和目标环境吞吐写成已达标。

- [x] **Step 3: 为页面绑定现有图示**

使用以下图示：`01-problem-solution.png`、`03-functional-architecture.png`、`04-contract-review-flow.png`、`05-technical-architecture.png`、`07-agent-sequence.png`、`08-rag-evidence-flow.png`、`11-security-layers.png`、`14-product-roadmap.png`，以及 `02-dashboard.png`、`03-audit.png`、`04-risk-review.png`、`07-reports.png`。

- [x] **Step 4: 执行文本预检**

Run:

```powershell
rg -n "TBD|TODO|待定|准确率已达|客户数量|市场份额" docs/project-overview/content/overview.md
```

Expected: 无输出。

### Task 2: 实现 Word 生成器

**Files:**
- Create: `docs/project-overview/scripts/build_docx.js`

- [x] **Step 1: 读取内容源并解析 12 个页面块**

生成器按 `# PAGE:` 标记拆分页面，支持 `##` 小节、普通段落、项目符号、三列表格和 `![图题](路径)` 图片；页面数量不是 12 时立即退出失败。

- [x] **Step 2: 建立 A4 与中文样式系统**

页面固定为 11906×16838 DXA，四边 1134 DXA；中文正文字体为微软雅黑/宋体，标题使用微软雅黑加粗；主色为深蓝灰 `28364A`、印章红 `A33A32`、金色 `9A7628`，表面色使用白色和浅灰。

- [x] **Step 3: 实现图片与表格组件**

图片读取 PNG 尺寸后按内容区等比缩放，必须提供 `altText`；表格统一使用 DXA 双宽度、浅色表头和 80/120 DXA 单元格内边距，禁止使用百分比宽度。

- [x] **Step 4: 添加页眉、页脚和显式分页**

封面使用空页眉；正文页眉显示“契鉴｜企业合同合规智能审查系统”；页脚显示“项目概要介绍”和动态页码。每个页面块之间插入显式分页，确保结构稳定为 12 页。

- [x] **Step 5: 生成 DOCX**

Run:

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' docs/project-overview/scripts/build_docx.js
```

Expected: 输出 `generated=...契鉴_项目概要介绍.docx pages=12`，退出码 0。

### Task 3: 实现结构与事实校验

**Files:**
- Create: `docs/project-overview/scripts/validate_document.py`

- [x] **Step 1: 校验 DOCX 基础结构**

使用 `python-docx` 和 `zipfile` 检查文件非空、12 个页面标题、A4 页面、页眉页脚、PAGE 域、至少 10 个图片资源和全部图片替代文字。

- [x] **Step 2: 校验事实与责任边界**

必须包含项目名称、双 Agent、RAG、13 张数据库表、40 条 API 路由和自动化测试证据；必须包含“待实测”或“外部验收”边界；禁止出现虚构客户、收入、市场份额和“OCR 准确率已达标”等表述。

- [x] **Step 3: 校验表格几何与素材引用**

逐表比较 `tblW`、`tblGrid` 和 `tcW`；检查内容源引用的全部 PNG 存在且可读取。

- [x] **Step 4: 运行 DOCX 校验**

Run:

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' docs/project-overview/scripts/validate_document.py docs/project-overview/契鉴_项目概要介绍.docx
```

Expected: `PASS pages=12 ...`，退出码 0。

### Task 4: 转换 PDF 并逐页视觉验收

**Files:**
- Create: `docs/project-overview/契鉴_项目概要介绍.pdf`
- Create: `docs/project-overview/rendered/page-*.png`

- [x] **Step 1: 使用 Microsoft Word 将 DOCX 导出为 PDF**

Run: 通过 Word COM 以只读方式打开 DOCX，并调用 `ExportAsFixedFormat(..., 17)` 生成 PDF。

Expected: PDF 存在且大于 100 KB。

- [x] **Step 2: 校验 PDF 页数**

Run:

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' docs/project-overview/scripts/validate_document.py docs/project-overview/契鉴_项目概要介绍.docx docs/project-overview/契鉴_项目概要介绍.pdf
```

Expected: `PASS pages=12`，退出码 0。

- [x] **Step 3: 将 PDF 渲染为逐页 PNG**

使用工作区内置 PDF 渲染依赖将 12 页按约 140～160 DPI 输出到 `docs/project-overview/rendered/`。

- [x] **Step 4: 逐页检查并修正**

检查封面、段落、图题、表格、图片比例、页眉页脚、页码、页面边缘和中文编码；不得存在裁切、重叠、图片缺失、孤行、异常空白页或密度失衡。

### Task 5: 完成说明与最终验收

**Files:**
- Create: `docs/project-overview/README.md`
- Modify: `.planning/project-overview-document/task_plan.md`
- Modify: `.planning/project-overview-document/progress.md`

- [x] **Step 1: 编写生成说明**

记录内容源、生成命令、校验命令、素材来源和事实边界，不要求安装新依赖。

- [x] **Step 2: 运行最终验证**

Run:

```powershell
git diff --check -- docs/project-overview docs/superpowers/specs/2026-08-15-project-overview-document-design.md docs/superpowers/plans/2026-08-16-project-overview-document.md
```

Expected: 无输出，退出码 0。

- [x] **Step 3: 更新任务记录**

把阶段 3～6 更新为 `complete`，在 `progress.md` 记录生成文件、页数、结构验证和视觉验收结果。

- [x] **Step 4: 提交检查点（仅在用户明确要求提交时执行）**

```powershell
git add docs/project-overview docs/superpowers/specs/2026-08-15-project-overview-document-design.md docs/superpowers/plans/2026-08-16-project-overview-document.md
git commit -m "docs: add project overview document"
```
