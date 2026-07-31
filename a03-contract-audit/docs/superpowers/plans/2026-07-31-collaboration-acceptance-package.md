# 契鉴协作验收包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一套可安全发送给老师和组员、可在 Windows 电脑复现测试并回收人工准确率证据的脱敏协作验收 ZIP。

**Architecture:** 使用独立生成脚本把项目事实、测试用例和人工标注规则转换为 Word 与 Excel；使用白名单式源码复制和黑名单式二次扫描构建净化源码副本；所有生成物进入独立 `outputs/collaboration-acceptance-package/`，不修改用户现有业务源码和未提交交付物。最终对文档、工作簿、源码清单、自动化测试和 ZIP 哈希分别验收。

**Tech Stack:** PowerShell 7/Windows PowerShell、bundled Node.js、`docx`、`@oai/artifact-tool`、Python 3.11、pytest、Playwright、Vue 3/Vite、ZIP/SHA-256。

---

## 文件结构

**新增生成与校验文件：**

- `tools/acceptance-package/build-documents.mjs`：生成三个 Word 文档。
- `tools/acceptance-package/build-workbooks.mjs`：生成五个 Excel 工作簿并导出视觉预览。
- `tools/acceptance-package/build-package.ps1`：创建目录、复制白名单源码和材料、排除敏感文件、生成 ZIP 与 SHA-256。
- `tools/acceptance-package/verify-package.ps1`：校验目录、敏感模式、绝对路径、数据库、上传文件、大文件和 ZIP 完整性。
- `tools/acceptance-package/content/project-status.json`：存放报告使用的结构化项目状态和本轮测试结果。
- `tools/acceptance-package/content/test-cases.json`：存放功能测试用例、证据要求和人工材料任务。
- `tools/acceptance-package/README.md`：记录生成命令、运行前提和输出位置。

**新增输出目录：**

- `outputs/collaboration-acceptance-package/契鉴_协作验收包/`：解压后的最终目录。
- `outputs/collaboration-acceptance-package/契鉴_协作验收包.zip`：可发送文件。
- `outputs/collaboration-acceptance-package/契鉴_协作验收包.zip.sha256`：传输校验值。
- `outputs/collaboration-acceptance-package/verification/`：渲染图、测试日志和扫描报告，不放入发送包。

### Task 1: 建立持久化任务状态和内容数据契约

**Files:**
- Create: `.planning/collaboration-acceptance-package/task_plan.md`
- Create: `.planning/collaboration-acceptance-package/findings.md`
- Create: `.planning/collaboration-acceptance-package/progress.md`
- Modify: `.planning/.active_plan`
- Create: `tools/acceptance-package/content/project-status.json`
- Create: `tools/acceptance-package/content/test-cases.json`

- [ ] **Step 1: 建立任务计划文件**

计划阶段固定为：事实盘点、生成器、文档、工作簿、源码净化、测试与视觉验收、ZIP 交付。`findings.md` 记录历史证据与本轮新鲜证据的区别，`progress.md` 记录每条执行命令、退出码和错误。

- [ ] **Step 2: 编写项目状态数据**

`project-status.json` 必须包含 `generated_at`、`git_commit`、`historical_evidence`、`fresh_evidence`、`blocked_evidence`、`human_materials` 和 `milestones`。准确率状态固定为 `blocked_pending_frozen_gold`，直至收到双人复核金标准。

- [ ] **Step 3: 编写测试用例数据**

`test-cases.json` 至少覆盖登录权限、上传、解析、要素抽取、双 Agent、RAG、复核、整改、报表、知识库、审计、批量、异常恢复、响应式和部署。每条记录必须包含 `case_id`、`priority`、`module`、`type`、`preconditions`、`steps`、`expected`、`automation` 和 `evidence`。

- [ ] **Step 4: 验证 JSON 结构**

Run:

```powershell
Get-Content -Raw tools/acceptance-package/content/project-status.json | ConvertFrom-Json | Out-Null
Get-Content -Raw tools/acceptance-package/content/test-cases.json | ConvertFrom-Json | Out-Null
```

Expected: 两条命令退出码均为 0，无 JSON 解析错误。

### Task 2: 生成 Word 文档

**Files:**
- Create: `tools/acceptance-package/build-documents.mjs`
- Create: `tools/acceptance-package/README.md`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/00_请先阅读/项目进度反馈.docx`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/00_请先阅读/启动与测试指南.docx`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/03_准确率标注/标注说明.docx`

- [ ] **Step 1: 加载 bundled workspace dependencies 并阅读 Documents API 指南**

使用 `codex_app__load_workspace_dependencies` 返回的 Node.js 与 `node_modules`，不得安装新包或猜测依赖路径。完整阅读 Documents skill 要求及其引用的 DOCX 生成、渲染和检查说明。

- [ ] **Step 2: 实现 Word 生成器**

生成器从两个 JSON 内容文件读取数据，统一使用 A4、中文字体、页眉页脚、标题层级、页码、8pt 以内表格间距和可打印配色。项目进度反馈必须区分“本轮验证”“历史证据”“外部阻塞”；启动指南必须提供本地与 Docker 两条路径；标注说明必须与 `backend/evaluation/schema.json` 六字段一致。

- [ ] **Step 3: 运行 Word 生成器**

Run:

```powershell
& $bundledNode tools/acceptance-package/build-documents.mjs
```

Expected: 生成三个非空 DOCX，输出每个文件的字节数和章节数，退出码为 0。

- [ ] **Step 4: 检查 DOCX OOXML**

Run:

```powershell
& $bundledPython -m zipfile -t outputs/collaboration-acceptance-package/契鉴_协作验收包/00_请先阅读/项目进度反馈.docx
& $bundledPython -m zipfile -t outputs/collaboration-acceptance-package/契鉴_协作验收包/00_请先阅读/启动与测试指南.docx
& $bundledPython -m zipfile -t outputs/collaboration-acceptance-package/契鉴_协作验收包/03_准确率标注/标注说明.docx
```

Expected: 每个包均报告无错误。

### Task 3: 生成 Excel 协作模板

**Files:**
- Create: `tools/acceptance-package/build-workbooks.mjs`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/02_测试任务/测试任务分工.xlsx`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/02_测试任务/功能测试用例.xlsx`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/02_测试任务/测试结果填写模板.xlsx`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/03_准确率标注/合同要素金标准模板.xlsx`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/03_准确率标注/风险标注模板.xlsx`

- [ ] **Step 1: 阅读 Spreadsheet API 与样式指南**

完整阅读 `API_QUICK_START.md` 和 `style_guidelines.md`，只使用 loader 提供的 `@oai/artifact-tool`。在独立临时目录建立指向 loader `node_modules` 的 junction，不修改依赖目录。

- [ ] **Step 2: 实现工作簿生成器**

所有工作簿使用统一标题色、冻结表头、筛选、数据验证和说明页。测试结果统计页使用公式计算总数、通过、失败、阻塞和通过率；金标准模板必须包含样本、六项要素、标注人、复核人、版本、冻结日期和冻结状态；未冻结行通过醒目状态提示排除出正式统计。

- [ ] **Step 3: 运行工作簿生成器**

Run:

```powershell
& $bundledNode tools/acceptance-package/build-workbooks.mjs
```

Expected: 生成五个非空 XLSX，并在 `verification/workbooks/` 生成每个工作表的 PNG 预览。

- [ ] **Step 4: 检查关键单元格与公式错误**

使用 `workbook.inspect` 检查统计页和金标准表关键范围，再使用正则扫描 `#REF!|#DIV/0!|#VALUE!|#NAME?|#N/A`。

Expected: 关键范围值与公式完整，公式错误扫描为 0。

### Task 4: 构建脱敏源码副本与协作目录

**Files:**
- Create: `tools/acceptance-package/build-package.ps1`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/00_请先阅读/安全与脱敏要求.md`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/04_待测试合同/请将脱敏合同放在此处.md`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/05_结果回收/问题清单/问题登记模板.md`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包/01_项目源码/`

- [ ] **Step 1: 实现白名单复制**

使用 `git ls-files` 枚举已跟踪文件，再显式加入已确认的项目详细方案 DOCX/PDF。路径命中 `.git`、`.planning`、`.env`、`.venv`、`node_modules`、`storage`、缓存、数据库、日志或 Playwright 临时目录时拒绝复制。每个目标路径解析后必须位于验收包根目录内。

- [ ] **Step 2: 生成安全说明与回收目录**

安全说明明确禁止放入未脱敏合同、账号密码、Token 和客户信息；待测试合同目录只含操作说明；结果回收目录包含日志、截图、准确率结果和问题清单空目录及模板。

- [ ] **Step 3: 复制现有项目材料**

将根目录的 `契鉴_项目详细方案.docx` 和 `契鉴_项目详细方案.pdf` 复制到 `06_现有项目材料/`，核对源文件和副本 SHA-256 一致。

- [ ] **Step 4: 生成源码清单**

在 `01_项目源码/FILE_MANIFEST.sha256` 写入所有源码文件的相对路径、长度和 SHA-256，使用 UTF-8 编码。

### Task 5: 执行本轮新鲜自动化验证

**Files:**
- Modify: `tools/acceptance-package/content/project-status.json`
- Create: `outputs/collaboration-acceptance-package/verification/backend-pytest.log`
- Create: `outputs/collaboration-acceptance-package/verification/frontend-playwright.log`
- Create: `outputs/collaboration-acceptance-package/verification/frontend-type-check.log`
- Create: `outputs/collaboration-acceptance-package/verification/frontend-build.log`

- [ ] **Step 1: 运行后端全量测试**

Run:

```powershell
Set-Location backend
& .\.venv\Scripts\python.exe -m pytest tests -q 2>&1 | Tee-Object ..\outputs\collaboration-acceptance-package\verification\backend-pytest.log
```

Expected: pytest 退出码为 0；将实际 passed、skipped、warnings 和耗时写入 `fresh_evidence`，不使用历史数量替代。

- [ ] **Step 2: 运行前端测试**

Run:

```powershell
Set-Location frontend
& npm.cmd test 2>&1 | Tee-Object ..\outputs\collaboration-acceptance-package\verification\frontend-playwright.log
```

Expected: Playwright 退出码为 0；E2E 因缺少 `E2E_BASE_URL` 跳过时如实记录。

- [ ] **Step 3: 运行类型检查和构建**

Run:

```powershell
& npm.cmd run type-check 2>&1 | Tee-Object ..\outputs\collaboration-acceptance-package\verification\frontend-type-check.log
& npm.cmd run build 2>&1 | Tee-Object ..\outputs\collaboration-acceptance-package\verification\frontend-build.log
```

Expected: 两条命令退出码均为 0；记录模块数、构建耗时和警告。

- [ ] **Step 4: 用新鲜结果重建文档**

将四条验证命令的真实结果写入 `project-status.json` 后，重新运行 Word 与 Excel 生成器，确保报告口径与本轮结果一致。

### Task 6: 启动应用并验证核心路径

**Files:**
- Create: `outputs/collaboration-acceptance-package/verification/runtime/`

- [ ] **Step 1: 启动后端和前端**

分别使用空闲端口启动 FastAPI 与 Vite；记录进程 ID、URL 和启动日志。不得覆盖已有端口服务。

- [ ] **Step 2: 浏览器验证正常、空、错误和响应式状态**

验证登录、工作台、审查空状态、运行时接口错误回退和 390x844 响应式导航。记录截图、HTTP 错误和控制台 warn/error。

- [ ] **Step 3: 停止本轮启动的进程**

只停止 Step 1 记录的进程 ID，确认端口释放，不影响用户已有服务。

Expected: 核心页面可访问；发现问题时保留截图和日志并在报告中标记失败，不修改结论掩盖问题。

### Task 7: 安全扫描、视觉验收和 ZIP 交付

**Files:**
- Create: `tools/acceptance-package/verify-package.ps1`
- Create: `outputs/collaboration-acceptance-package/verification/security-scan.txt`
- Create: `outputs/collaboration-acceptance-package/verification/package-inventory.txt`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包.zip`
- Create: `outputs/collaboration-acceptance-package/契鉴_协作验收包.zip.sha256`

- [ ] **Step 1: 实现安全扫描**

校验验收包内不存在 `.env`、`.db`、`.sqlite`、私钥、常见 Token 模式、`C:\Users\` 绝对路径、`backend/storage`、根 `storage`、`.venv`、`node_modules` 和大于 50 MiB 的非批准文件。输出所有检查项和命中数量；任何禁止命中使脚本退出 1。

- [ ] **Step 2: 逐页检查 Word 渲染**

将三个 DOCX 渲染为 PDF/PNG，检查封面、目录或结构入口、表格、分页、中文字体、页码和空白页。修复裁切、重叠、乱码和异常分页后重新渲染。

- [ ] **Step 3: 检查全部 Excel 预览**

逐张查看所有工作表 PNG，修复截断表头、不可读颜色、异常行高、公式错误和空白默认页。

- [ ] **Step 4: 执行包校验**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/acceptance-package/verify-package.ps1
```

Expected: 所有目录、文档、工作簿、源码清单和安全检查通过，退出码为 0。

- [ ] **Step 5: 生成 ZIP 和哈希**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/acceptance-package/build-package.ps1 -Finalize
Get-FileHash outputs/collaboration-acceptance-package/契鉴_协作验收包.zip -Algorithm SHA256
```

Expected: ZIP 非空且可完整展开；计算值与 `.sha256` 文件一致。

- [ ] **Step 6: 最终需求核对**

逐项对照设计规格第 2 至第 10 节，确认文档、五个工作簿、脱敏源码、材料模板、回收目录、安全扫描、测试日志和 ZIP 哈希均有证据。准确率仍无冻结金标准时，所有文档必须保持“待正式验收”。

