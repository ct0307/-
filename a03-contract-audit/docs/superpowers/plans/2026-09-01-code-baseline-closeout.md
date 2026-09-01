# 契鉴代码基线收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验收并归档现有主题系统、企业法务工作台和项目概要，形成自动化零失败、浏览器实测通过、进度口径一致的比赛代码基线。

**Architecture:** 本计划不新增业务能力，而是按“成果边界审查 → 自动化验证 → 真实浏览器验证 → 文档归档 → 全量复验”的顺序收口现有工作区。主题系统、企业界面和概要文档分别形成可独立审查的提交；任何失败都先停止并进入系统化诊断，不用推测性修改掩盖问题。

**Tech Stack:** Vue 3、TypeScript、Vite、Element Plus、ECharts、Playwright、FastAPI、pytest、Word/PDF 校验脚本、Git

---

除非步骤另有说明，所有命令均从 `a03-contract-audit` 项目根目录执行。

## 文件结构

### 主题系统

- Create: `frontend/src/theme/theme.ts`：主题模式、系统偏好、持久化与调色板读取。
- Create: `frontend/src/components/layout/ThemeSwitcher.vue`：顶栏主题菜单。
- Create: `frontend/tests/theme-mode.spec.ts`：纯逻辑主题测试。
- Create: `frontend/tests/theme-switching-e2e.spec.ts`：持久化、系统跟随和移动端 E2E。
- Modify: `frontend/src/main.ts`、`frontend/src/components/layout/AppHeader.vue`：应用启动与入口挂载。
- Modify: `frontend/src/styles/tokens.scss`、`frontend/src/styles/index.scss`、`frontend/src/styles/element-overrides.scss`：三套语义主题。
- Modify: `frontend/src/components/charts/BaseChart.vue`、`TrendLine.vue`、`RiskDonut.vue`、`DeptBar.vue`、`TopRiskBar.vue`：主题变更时重新取色与重绘。
- Modify: `frontend/src/layouts/MainLayout.vue`、`frontend/src/components/layout/AppSidebar.vue`、`OpenClawBadge.vue`、`UserSwitcher.vue`：共享应用框架适配。

### 企业法务工作台

- Modify: `frontend/src/views/AuditView.vue`：360px 配置轨、连续结果工作面与风险证据状态。
- Modify: `frontend/src/components/audit/RiskReviewDrawer.vue`：证据链轨道、无可靠依据警告和移动布局。
- Modify: `frontend/src/components/audit/AnnotationModal.vue`：主题色适配。
- Modify: `frontend/src/views/AdminView.vue`、`CollaborationView.vue`、`DashboardView.vue`、`KnowledgeView.vue`、`LoginView.vue`、`RectifyView.vue`、`ReportsView.vue`、`RulesView.vue`：统一信息密度与语义令牌。
- Modify: `frontend/src/styles/mixins.scss`：共享风险视觉语义。
- Modify: `frontend/tests/ocr-quality-e2e.spec.ts`：低置信度、类型确认和历史筛选响应式验证。
- Existing test: `frontend/tests/enterprise-ui.spec.ts`：桌面、空状态、错误状态和移动导航验收。

### 项目概要与状态文档

- Create: `docs/project-overview/`：概要正文、生成器、校验器、DOCX/PDF 和渲染页。
- Modify: `README.md`：刷新当前进度、测试证据和交付材料索引。
- Modify: `PROGRESS.md`：追加 2026-09-01 收口记录。

---

### Task 1: 固化执行前基线

**Files:**
- Read: `docs/superpowers/specs/2026-09-01-competition-delivery-closeout-design.md`
- Read: `docs/superpowers/plans/2026-07-31-theme-switching.md`
- Read: `docs/superpowers/plans/2026-07-31-enterprise-legal-review-desk.md`
- Update local only: `.planning/competition-delivery-closeout/findings.md`
- Update local only: `.planning/competition-delivery-closeout/progress.md`

- [ ] **Step 1: 记录执行前 Git 状态**

Run from `a03-contract-audit` project root:

```powershell
git status --short --branch
git diff --stat
git ls-files --others --exclude-standard
```

Expected: 当前分支为 `codex/frontend-enterprise-polish`；业务改动规模与计划文件记录一致，没有来源不明的新删除项。

- [ ] **Step 2: 逐项核对主题改动边界**

```powershell
git diff -- frontend/src/theme frontend/src/components/layout frontend/src/components/charts frontend/src/main.ts frontend/src/styles
```

Expected: 只包含主题状态、语义令牌、应用框架和图表重绘，不改变 API、路由或业务数据结构。

- [ ] **Step 3: 逐项核对企业界面改动边界**

```powershell
git diff -- frontend/src/views frontend/src/components/audit frontend/tests/ocr-quality-e2e.spec.ts
```

Expected: 保留现有 Pinia 和 API 调用；新增内容只呈现已有风险、依据和置信度，不伪造业务结果。

- [ ] **Step 4: 将审查结论写入本地 findings.md**

记录以下确定结论：主题边界是否合格、企业界面边界是否合格、是否存在需要单独诊断的行为变更。若任一边界不合格，停止本计划并先建立对应缺陷任务。

- [ ] **Step 5: 启动前后端并检查健康状态**

```powershell
$backendOut = Join-Path $env:TEMP 'qijian-backend.out.log'
$backendErr = Join-Path $env:TEMP 'qijian-backend.err.log'
$frontendOut = Join-Path $env:TEMP 'qijian-frontend.out.log'
$frontendErr = Join-Path $env:TEMP 'qijian-frontend.err.log'
$env:PYTHONPATH = (Resolve-Path 'backend\.venv\Lib\site-packages').Path
$backendProcess = Start-Process -FilePath 'C:\Users\chentao\AppData\Local\Programs\Python\Python313\python.exe' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory (Resolve-Path 'backend').Path -WindowStyle Hidden -PassThru -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
$frontendProcess = Start-Process -FilePath (Get-Command npm.cmd).Source -ArgumentList 'run','dev','--','--host','127.0.0.1','--port','5173' -WorkingDirectory (Resolve-Path 'frontend').Path -WindowStyle Hidden -PassThru -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr
"backend_pid=$($backendProcess.Id)"
"frontend_pid=$($frontendProcess.Id)"
```

等待两个进程进入监听后执行：

```powershell
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/v1/runtime/status' | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5173/login' | Select-Object StatusCode
```

Expected: 两个请求均返回 HTTP 200。若端口已被其他进程占用，先识别现有进程和页面身份，不直接终止未知进程。

---

### Task 2: 验收并归档主题系统

**Files:**
- Create: `frontend/src/theme/theme.ts`
- Create: `frontend/src/components/layout/ThemeSwitcher.vue`
- Create: `frontend/tests/theme-mode.spec.ts`
- Create: `frontend/tests/theme-switching-e2e.spec.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/components/layout/AppHeader.vue`
- Modify: `frontend/src/styles/tokens.scss`
- Modify: `frontend/src/styles/index.scss`
- Modify: `frontend/src/styles/element-overrides.scss`
- Modify: `frontend/src/components/charts/BaseChart.vue`
- Modify: `frontend/src/components/charts/TrendLine.vue`
- Modify: `frontend/src/components/charts/RiskDonut.vue`
- Modify: `frontend/src/components/charts/DeptBar.vue`
- Modify: `frontend/src/components/charts/TopRiskBar.vue`
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/components/layout/AppSidebar.vue`
- Modify: `frontend/src/components/layout/OpenClawBadge.vue`
- Modify: `frontend/src/components/layout/UserSwitcher.vue`
- Include design: `docs/superpowers/specs/2026-07-31-theme-switching-design.md`
- Include plan: `docs/superpowers/plans/2026-07-31-theme-switching.md`

- [ ] **Step 1: 运行主题纯逻辑测试**

```powershell
Push-Location frontend
npm.cmd test -- tests/theme-mode.spec.ts
Pop-Location
```

Expected: `2 passed`，覆盖默认卷宗模式、非法存储回退和系统深浅色解析。

- [ ] **Step 2: 运行类型检查**

```powershell
Push-Location frontend
npm.cmd run type-check
Pop-Location
```

Expected: exit 0，无 TypeScript 错误。

- [ ] **Step 3: 在已启动前后端的条件下运行主题 E2E**

```powershell
Push-Location frontend
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npm.cmd test -- tests/theme-switching-e2e.spec.ts
$result=$LASTEXITCODE
Remove-Item Env:\E2E_BASE_URL -ErrorAction SilentlyContinue
Pop-Location
exit $result
```

Expected: `2 passed, 0 skipped`；卷宗默认值、深灰持久化、跟随系统和 390×844 无横向溢出均通过。

- [ ] **Step 4: 使用应用内 Browser 验证主题交互**

The flow under test is: `/login` 登录 → 顶栏切换卷宗/明亮/深灰/跟随系统 → 刷新与系统色彩变化 → 主题和布局保持正确。

检查：页面标题与 URL、非空内容、无框架错误覆盖层、console 无应用错误、主题菜单交互、刷新持久化、1440×900 与 390×844 截图。

- [ ] **Step 5: 检查主题提交范围**

```powershell
git add -- frontend/src/theme frontend/src/components/layout/ThemeSwitcher.vue frontend/src/main.ts frontend/src/components/layout/AppHeader.vue frontend/src/styles/tokens.scss frontend/src/styles/index.scss frontend/src/styles/element-overrides.scss frontend/src/components/charts frontend/src/layouts/MainLayout.vue frontend/src/components/layout/AppSidebar.vue frontend/src/components/layout/OpenClawBadge.vue frontend/src/components/layout/UserSwitcher.vue frontend/tests/theme-mode.spec.ts frontend/tests/theme-switching-e2e.spec.ts docs/superpowers/specs/2026-07-31-theme-switching-design.md docs/superpowers/plans/2026-07-31-theme-switching.md
git diff --cached --check
git diff --cached --name-only
```

Expected: 暂存区只包含上述主题文件，无审查页、概要或输出文件。

- [ ] **Step 6: 获得业务改动提交授权后提交**

```powershell
git commit -m "feat: add persistent multi-theme support"
```

Expected: 单一主题提交成功；未授权时保持暂存区不提交并暂停在此检查点。

---

### Task 3: 验收并归档企业法务工作台

**Files:**
- Modify: `frontend/src/views/AdminView.vue`
- Modify: `frontend/src/views/AuditView.vue`
- Modify: `frontend/src/views/CollaborationView.vue`
- Modify: `frontend/src/views/DashboardView.vue`
- Modify: `frontend/src/views/KnowledgeView.vue`
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/views/RectifyView.vue`
- Modify: `frontend/src/views/ReportsView.vue`
- Modify: `frontend/src/views/RulesView.vue`
- Modify: `frontend/src/components/audit/AnnotationModal.vue`
- Modify: `frontend/src/components/audit/RiskReviewDrawer.vue`
- Modify: `frontend/src/styles/mixins.scss`
- Modify: `frontend/tests/ocr-quality-e2e.spec.ts`
- Existing test: `frontend/tests/enterprise-ui.spec.ts`
- Include design: `docs/superpowers/specs/2026-07-31-enterprise-legal-review-desk-design.md`
- Include plan: `docs/superpowers/plans/2026-07-31-enterprise-legal-review-desk.md`

- [ ] **Step 1: 运行企业界面和 OCR 聚焦 E2E**

```powershell
Push-Location frontend
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npm.cmd test -- tests/enterprise-ui.spec.ts tests/ocr-quality-e2e.spec.ts
$result=$LASTEXITCODE
Remove-Item Env:\E2E_BASE_URL -ErrorAction SilentlyContinue
Pop-Location
exit $result
```

Expected: `4 passed, 0 skipped`；登录、审查空状态、运行时错误回退、移动导航、低置信度 OCR、类型冲突确认和历史筛选均通过。

- [ ] **Step 2: 使用应用内 Browser 走查九个业务页**

The flow under test is: `/login` 登录 → 依次进入 `/dashboard`、`/audit`、`/collaboration`、`/rectify`、`/reports`、`/knowledge`、`/rules`、`/history`、`/admin` → 页面有意义渲染且主要控件可操作。

桌面视口使用 1440×900；移动视口使用 390×844，重点检查 `/audit`、`/reports` 和侧栏。每两次浏览器查看后，将页面身份、空白检查、框架覆盖层、console、交互和溢出结论写入 `.planning/competition-delivery-closeout/findings.md`。

- [ ] **Step 3: 验证风险证据边界**

在审查页分别检查有 `rag_sources` 与无 `rag_sources` 的风险：前者显示可靠依据数量，后者显示“无可靠依据 · 待人工复核”；打开风险抽屉后，无来源风险必须出现人工复核警告，不能显示伪造法条。

Expected: 页面呈现与后端 `rag_sources`、`confidence`、`review_status` 一致，浏览器 console 无相关错误。

- [ ] **Step 4: 对失败执行明确阻断策略**

如果 Step 1 至 Step 3 任一失败，记录复现路径、截图、DOM/console 证据和责任文件，停止本 Task，并启动 `systematic-debugging` 形成单独缺陷修复；不得跳过失败继续更新完成状态。

- [ ] **Step 5: 检查企业界面提交范围**

```powershell
git add -- frontend/src/views/AdminView.vue frontend/src/views/AuditView.vue frontend/src/views/CollaborationView.vue frontend/src/views/DashboardView.vue frontend/src/views/KnowledgeView.vue frontend/src/views/LoginView.vue frontend/src/views/RectifyView.vue frontend/src/views/ReportsView.vue frontend/src/views/RulesView.vue frontend/src/components/audit/AnnotationModal.vue frontend/src/components/audit/RiskReviewDrawer.vue frontend/src/styles/mixins.scss frontend/tests/ocr-quality-e2e.spec.ts docs/superpowers/specs/2026-07-31-enterprise-legal-review-desk-design.md docs/superpowers/plans/2026-07-31-enterprise-legal-review-desk.md
git diff --cached --check
git diff --cached --name-only
```

Expected: 暂存区只包含企业界面与对应规格，不包含项目概要或输出文件。

- [ ] **Step 6: 获得业务改动提交授权后提交**

```powershell
git commit -m "feat: refine enterprise legal review desk"
```

Expected: 单一企业界面提交成功；未授权时保持暂存区不提交并暂停在此检查点。

---

### Task 4: 验收并归档项目概要

**Files:**
- Create: `docs/project-overview/README.md`
- Create: `docs/project-overview/content/overview.md`
- Create: `docs/project-overview/scripts/build_docx.js`
- Create: `docs/project-overview/scripts/validate_document.py`
- Create: `docs/project-overview/契鉴_项目概要介绍.docx`
- Create: `docs/project-overview/契鉴_项目概要介绍.pdf`
- Create: `docs/project-overview/rendered/`
- Include design: `docs/superpowers/specs/2026-08-15-project-overview-document-design.md`
- Include plan: `docs/superpowers/plans/2026-08-16-project-overview-document.md`

- [ ] **Step 1: 运行概要结构与事实校验**

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' docs/project-overview/scripts/validate_document.py docs/project-overview/契鉴_项目概要介绍.docx docs/project-overview/契鉴_项目概要介绍.pdf
```

Expected: `PASS pages=12 headings=11 tables=7 images=12 chinese_chars=2904`。

- [ ] **Step 2: 视觉检查 12 页渲染图**

先查看 `docs/project-overview/rendered/contact-sheet.png`，再抽查封面、功能、架构、验证和结尾页原图。检查裁切、重叠、乱码、缺图、表格越界、异常空白和页码连续性。

Expected: 12 页均可读，图片与正文匹配，不出现尚未实测指标被写成完成值。

- [ ] **Step 3: 检查概要提交范围**

```powershell
git add -- docs/project-overview docs/superpowers/specs/2026-08-15-project-overview-document-design.md docs/superpowers/plans/2026-08-16-project-overview-document.md
git diff --cached --check
git diff --cached --name-only
```

Expected: 暂存区只包含概要源文件、生成物、渲染证据和对应规格/计划。

- [ ] **Step 4: 获得文档提交授权后提交**

```powershell
git commit -m "docs: add competition project overview"
```

Expected: 单一概要文档提交成功；未授权时保持暂存区不提交并暂停在此检查点。

---

### Task 5: 校准 README 与 PROGRESS 事实口径

**Files:**
- Modify: `README.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 更新 README 当前进度日期和验证数据**

将“更新于 2026-07-31”改为“更新于 2026-09-01”。只有 Task 2、Task 3 和 Task 4 全部达到 Expected 时，才将自动化验证写为：后端 `142 passed/1 skipped`、前端 `19 passed/0 skipped`、类型检查与生产构建通过；将前端质量写为本轮浏览器覆盖九个业务页及 1440×900/390×844；将项目概要改为已完成并链接 `docs/project-overview/契鉴_项目概要介绍.docx` 和 PDF。

- [ ] **Step 2: 更新 README 参赛材料状态**

保持以下材料为未完成：项目简介 PPT、测试报告与测试用例、团队过程材料、演示视频。OCR 准确率、52 份批量吞吐、目标 Compose 环境和硬件对照继续标记为待实测，不得由代码测试推断完成。

- [ ] **Step 3: 在 PROGRESS 顶部追加 2026-09-01 记录**

新增“代码基线、企业法务工作台与项目概要收口”章节，必须记录：主题模式范围、风险证据呈现边界、概要页数/表格/图片、后端与前端测试数量、浏览器视口、生产构建模块数，以及仍待外部验收的四项边界。

- [ ] **Step 4: 执行口径扫描**

```powershell
rg -n "125 passed|11 passed|3 skipped|概要.*待制作|更新于 2026-07-31" README.md PROGRESS.md
```

Expected: README 当前状态不再命中过期口径；PROGRESS 的历史章节可以保留带日期的历史结果。

- [ ] **Step 5: 重读目标段落并检查格式**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Get-Content -Encoding UTF8 README.md | Select-Object -First 55
Get-Content -Encoding UTF8 PROGRESS.md | Select-Object -First 70
git diff --check -- README.md PROGRESS.md
```

Expected: 中文编码正常、Markdown 表格列数一致、链接存在、验证数字与本轮证据完全一致。

- [ ] **Step 6: 获得状态文档提交授权后提交**

```powershell
git add -- README.md PROGRESS.md
git diff --cached --check
git commit -m "docs: refresh verified project baseline"
```

Expected: 提交只包含 README 与 PROGRESS。

---

### Task 6: 全量复验并形成阶段一完成证据

**Files:**
- Update local only: `.planning/competition-delivery-closeout/task_plan.md`
- Update local only: `.planning/competition-delivery-closeout/findings.md`
- Update local only: `.planning/competition-delivery-closeout/progress.md`

- [ ] **Step 1: 运行后端全量测试**

```powershell
$env:PYTHONPATH='C:\Users\chentao\Desktop\浙江省外包赛\a03-contract-audit\backend\.venv\Lib\site-packages'
Push-Location backend
& 'C:\Users\chentao\AppData\Local\Programs\Python\Python313\python.exe' -m pytest -q
$result=$LASTEXITCODE
Pop-Location
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
exit $result
```

Expected: `142 passed, 1 skipped, 0 failed`；跳过项和第三方弃用警告如实记录。

- [ ] **Step 2: 运行前端全量真实测试**

```powershell
Push-Location frontend
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npm.cmd test
$result=$LASTEXITCODE
Remove-Item Env:\E2E_BASE_URL -ErrorAction SilentlyContinue
Pop-Location
exit $result
```

Expected: `19 passed, 0 skipped, 0 failed`。

- [ ] **Step 3: 运行前端类型检查和生产构建**

```powershell
Push-Location frontend
npm.cmd run type-check
npm.cmd run build
Pop-Location
```

Expected: 两个命令均 exit 0；构建转换 2352 个模块或更多，任何数量变化都记录真实结果而不沿用旧值。

- [ ] **Step 4: 运行概要校验和 Git 完整性检查**

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' docs/project-overview/scripts/validate_document.py docs/project-overview/契鉴_项目概要介绍.docx docs/project-overview/契鉴_项目概要介绍.pdf
git diff --check
git status --short --branch
```

Expected: 概要校验 PASS；无空白错误；剩余未提交内容仅为明确排除到后续阶段的成果。

- [ ] **Step 5: 更新本地规划状态**

将 `.planning/competition-delivery-closeout/task_plan.md` 的阶段一改为 `complete`，在 `progress.md` 记录所有最终命令、退出码、通过/跳过数量、浏览器证据和剩余风险；阶段二改为 `in_progress` 之前必须先创建独立硬指标实施计划。

- [ ] **Step 6: 阶段一完成检查点**

只在 Task 1 至 Task 6 的 Expected 全部满足时声明阶段一完成。不得把未执行的真实浏览器、外部准确率、吞吐、Compose 或硬件测试写为通过。
