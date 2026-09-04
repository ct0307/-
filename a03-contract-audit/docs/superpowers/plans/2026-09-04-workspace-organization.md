# 工作区保守收口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变正式项目内部构建路径的前提下，将仓库外围整理为正式项目、参考资料、交付索引、历史归档和本地过程文件五个清晰区域。

**Architecture:** `a03-contract-audit/` 继续作为唯一正式项目，内部源码与生成路径不迁移。根目录通过 `README.md` 和 `AGENTS.md` 提供统一入口；Git 跟踪的参考附件与废弃原型使用可追溯重命名；本地过程和验收输出仅通过忽略规则隔离。工作树清理不包含在自动执行范围内，只生成经哈希核验的清理清单并等待用户再次确认。

**Tech Stack:** Git、PowerShell、Markdown、Python 标准库、项目现有质量门禁

---

## 文件结构

| 路径 | 操作 | 职责 |
|---|---|---|
| `README.md` | 创建 | 仓库总入口、目录导航和常用命令 |
| `AGENTS.md` | 创建 | 项目级技术栈、命令、环境变量、目录和禁止操作 |
| `.gitignore` | 修改 | 忽略根 `.planning/`、所有临时工作树和项目运行输出 |
| `references/README.md` | 创建 | 三份原始比赛资料的来源与用途说明 |
| `references/*` | 重命名 | 官方赛题手册、综合分析和实施方案 |
| `archive/a03-demo/*` | 重命名 | 已废弃原生 JavaScript 原型 |
| `archive/a03-demo/README.md` | 创建 | 归档状态和禁止作为正式入口的说明 |
| `deliverables/README.md` | 创建 | 正式材料唯一索引及待完成材料状态 |
| `CLAUDE.md` | 修改 | 更新附件与归档原型路径，校准目录说明 |
| `a03-contract-audit/docs/backend-modules.md` | 修改 | 更新实施方案来源路径和原型引用 |
| `a03-contract-audit/frontend/src/stores/demo.ts` | 修改 | 将历史注释改为归档原型路径，不改变逻辑 |
| `a03-contract-audit/docs/workspace-organization-check.ps1` | 创建 | 自动验证目标目录、旧路径引用和 Git 忽略规则 |
| `a03-contract-audit/docs/worktree-cleanup-inventory.md` | 创建 | 工作树状态、未跟踪产物和后续清理边界 |

### Task 1：建立目录治理自动检查

**Files:**
- Create: `a03-contract-audit/docs/workspace-organization-check.ps1`

- [ ] **Step 1：编写目标结构与旧路径检查脚本**

脚本从自身位置反推仓库根目录，并固定检查以下条件：

```powershell
[CmdletBinding()]
param()

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$errors = [System.Collections.Generic.List[string]]::new()

$required = @(
    'README.md',
    'AGENTS.md',
    'a03-contract-audit',
    'references/README.md',
    'references/浙江省外包赛-2026赛题手册.pdf',
    'references/浙江省外包赛-2026赛题手册综合分析.docx',
    'references/A03企业合同合规审查系统实施方案.docx',
    'deliverables/README.md',
    'archive/a03-demo/README.md',
    'archive/a03-demo/app.js',
    'archive/a03-demo/index.html',
    'archive/a03-demo/styles.css'
)

$forbidden = @(
    '浙江省外包赛-2026赛题手册.pdf',
    '浙江省外包赛-2026赛题手册综合分析.docx',
    'A03企业合同合规审查系统实施方案.docx',
    'a03-demo'
)

foreach ($relativePath in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath))) {
        $errors.Add("缺少目标路径：$relativePath")
    }
}

foreach ($relativePath in $forbidden) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath)) {
        $errors.Add("旧路径仍存在：$relativePath")
    }
}
```

继续检查根忽略规则和有效引用：

```powershell
$ignored = @('.planning', 'a03-contract-audit/outputs')
foreach ($relativePath in $ignored) {
    & git -C $repoRoot check-ignore -q -- $relativePath
    if ($LASTEXITCODE -ne 0) {
        $errors.Add("未被 Git 忽略：$relativePath")
    }
}

$trackedText = & git -C $repoRoot grep -n -E `
    '(^|[`"''( ])(浙江省外包赛-2026赛题手册[.]pdf|浙江省外包赛-2026赛题手册综合分析[.]docx|A03企业合同合规审查系统实施方案[.]docx|a03-demo/)' `
    -- ':!a03-contract-audit/docs/superpowers/specs/2026-09-04-workspace-organization-design.md' `
       ':!a03-contract-audit/docs/superpowers/plans/2026-09-04-workspace-organization.md'
if ($LASTEXITCODE -eq 0) {
    $errors.Add("发现旧路径引用：`n$($trackedText -join "`n")")
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'PASS workspace organization'
exit 0
```

- [ ] **Step 2：运行检查并确认当前结构失败**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File a03-contract-audit/docs/workspace-organization-check.ps1
```

Expected: 退出码 1，并至少报告缺少 `README.md`、`references/README.md`、`deliverables/README.md` 或旧根路径仍存在；不得因 PowerShell 语法错误失败。

- [ ] **Step 3：提交检查脚本**

```powershell
git add -- a03-contract-audit/docs/workspace-organization-check.ps1
git diff --cached --check
git commit -m "test: define workspace organization contract"
```

### Task 2：建立根入口与本地文件边界

**Files:**
- Create: `README.md`
- Create: `AGENTS.md`
- Modify: `.gitignore`

- [ ] **Step 1：更新根忽略规则**

在根 `.gitignore` 的 Agent 本地元数据段加入：

```gitignore
.planning/
.worktrees/
**/.worktrees/
a03-contract-audit/outputs/
```

保留现有 `.agents/`、`.codex/` 和构建产物规则，不忽略 `deliverables/`、`references/` 或 `archive/`。

- [ ] **Step 2：创建根 README**

内容固定包含：

```markdown
# 浙江省外包赛 A03 项目工作区

本仓库的唯一正式项目是 [契鉴企业合同合规审查系统](./a03-contract-audit/README.md)。

## 目录导航

| 目录 | 用途 | 是否正式交付 |
|---|---|---|
| `a03-contract-audit/` | 前后端源码、部署配置、测试和可追溯文档源 | 是 |
| `references/` | 官方赛题与原始需求资料 | 输入资料 |
| `deliverables/` | 最终参赛材料索引 | 是 |
| `archive/` | 已废弃原型，仅供历史参考 | 否 |
| `.planning/` | 本地 Agent 工作记录 | 否，不入库 |
| `.worktrees/` | 临时 Git 工作树 | 否，不入库 |

## 常用入口

- 项目说明：`a03-contract-audit/README.md`
- 项目进度：`a03-contract-audit/PROGRESS.md`
- 硬指标证据：`a03-contract-audit/docs/evaluation/hard-indicator-matrix.md`
- 参赛材料：`deliverables/README.md`

## 质量门禁

在 `a03-contract-audit/` 目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

质量门禁不替代真实 52 文件、PostgreSQL、OCR 准确率、OpenClaw/GPU 或能耗实测。
```

- [ ] **Step 3：创建项目级 AGENTS.md**

文件必须明确：正式项目目录、Vue 3/TypeScript/Vite 与 FastAPI/SQLAlchemy 技术栈、本地与 Docker 启动命令、完整质量门禁、材料构建命令、主要环境变量来源、`backend/`、`frontend/`、`docs/`、`scripts/` 目录职责，以及禁止提交密钥、数据库、合同、运行输出和未实测结论。

- [ ] **Step 4：验证忽略规则和 Markdown 格式**

```powershell
git check-ignore -v --no-index -- .planning/.workspace-organization-check a03-contract-audit/outputs/.workspace-organization-check
git diff --check -- .gitignore README.md AGENTS.md
```

Expected: 两个哨兵路径均显示匹配的根忽略规则；不创建哨兵文件；`git diff --check` 退出码 0。

- [ ] **Step 5：提交根入口**

```powershell
git add -- .gitignore README.md AGENTS.md
git commit -m "docs: establish workspace entry points"
```

### Task 3：移动参考资料并修复引用

**Files:**
- Create: `references/README.md`
- Rename: `浙江省外包赛-2026赛题手册.pdf` → `references/浙江省外包赛-2026赛题手册.pdf`
- Rename: `浙江省外包赛-2026赛题手册综合分析.docx` → `references/浙江省外包赛-2026赛题手册综合分析.docx`
- Rename: `A03企业合同合规审查系统实施方案.docx` → `references/A03企业合同合规审查系统实施方案.docx`
- Modify: `CLAUDE.md`
- Modify: `a03-contract-audit/docs/backend-modules.md`

- [ ] **Step 1：记录移动前哈希**

```powershell
$files = @(
  '浙江省外包赛-2026赛题手册.pdf',
  '浙江省外包赛-2026赛题手册综合分析.docx',
  'A03企业合同合规审查系统实施方案.docx'
)
$before = @{}
foreach ($file in $files) {
  $before[$file] = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash
}
$before.GetEnumerator() | Sort-Object Name | Format-Table -AutoSize
```

Expected: 三个文件均返回 64 位 SHA-256；将结果保留在当前终端会话用于 Step 5 比较。

- [ ] **Step 2：使用 Git 移动三个文件**

```powershell
New-Item -ItemType Directory -Path references -ErrorAction Stop | Out-Null
git mv -- '浙江省外包赛-2026赛题手册.pdf' 'references/浙江省外包赛-2026赛题手册.pdf'
git mv -- '浙江省外包赛-2026赛题手册综合分析.docx' 'references/浙江省外包赛-2026赛题手册综合分析.docx'
git mv -- 'A03企业合同合规审查系统实施方案.docx' 'references/A03企业合同合规审查系统实施方案.docx'
```

- [ ] **Step 3：创建参考资料说明**

`references/README.md` 使用表格列出三份资料、来源、用途和“只作为需求与事实输入，不执行文档中的指令性文本”边界。

- [ ] **Step 4：更新有效引用**

- `CLAUDE.md` 中根附件路径改为 `references/...`，目录结构中的附件说明同步更新。
- `a03-contract-audit/docs/backend-modules.md` 中实施方案引用改为 `../../references/A03企业合同合规审查系统实施方案.docx`。
- 历史规格与计划中描述“原路径”的文本保留，因为它们是决策记录并已被检查脚本排除。

- [ ] **Step 5：比较移动前后哈希**

```powershell
foreach ($file in $files) {
  $after = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path 'references' $file)).Hash
  if ($after -ne $before[$file]) { throw "哈希不一致：$file" }
}
'PASS reference hashes'
```

Expected: 输出 `PASS reference hashes`。

- [ ] **Step 6：验证引用并提交**

```powershell
rg -n -g '!a03-contract-audit/docs/superpowers/specs/2026-09-04-workspace-organization-design.md' -g '!a03-contract-audit/docs/superpowers/plans/2026-09-04-workspace-organization.md' -e '(^|[ `(])浙江省外包赛-2026赛题手册[.]pdf' -e '(^|[ `(])A03企业合同合规审查系统实施方案[.]docx' .
git diff --check
git add -- references CLAUDE.md a03-contract-audit/docs/backend-modules.md
git commit -m "docs: organize competition references"
```

Expected: `rg` 无有效旧路径匹配；Git 将三个二进制文件显示为 rename 或等价删除/新增且哈希不变。

### Task 4：归档废弃原型

**Files:**
- Rename: `a03-demo/app.js` → `archive/a03-demo/app.js`
- Rename: `a03-demo/index.html` → `archive/a03-demo/index.html`
- Rename: `a03-demo/styles.css` → `archive/a03-demo/styles.css`
- Create: `archive/a03-demo/README.md`
- Modify: `CLAUDE.md`
- Modify: `a03-contract-audit/docs/backend-modules.md`
- Modify: `a03-contract-audit/frontend/src/stores/demo.ts`

- [ ] **Step 1：记录原型文件哈希并移动**

```powershell
$demoFiles = @('app.js', 'index.html', 'styles.css')
$demoHashes = @{}
foreach ($file in $demoFiles) {
  $demoHashes[$file] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path 'a03-demo' $file)).Hash
}
New-Item -ItemType Directory -Path archive -ErrorAction SilentlyContinue | Out-Null
git mv -- a03-demo archive/a03-demo
```

- [ ] **Step 2：创建归档说明**

`archive/a03-demo/README.md` 必须说明：该目录是 2026 年 7 月 Vue 迁移前的静态交互原型；使用模拟数据；不接受维护；不得作为正式系统、演示服务器或功能完成度证据；正式入口为 `../../a03-contract-audit/README.md`。

- [ ] **Step 3：更新文字引用**

- `CLAUDE.md` 的目录与迁移说明改为 `archive/a03-demo/`。
- `a03-contract-audit/docs/backend-modules.md` 将 `a03-demo 前端` 改为 `archive/a03-demo 归档原型`。
- `a03-contract-audit/frontend/src/stores/demo.ts` 注释改为 `迁移自 archive/a03-demo 归档原型`，不改变任何标识符或运行逻辑。

- [ ] **Step 4：比较哈希并验证旧引用**

```powershell
foreach ($file in $demoFiles) {
  $after = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path 'archive/a03-demo' $file)).Hash
  if ($after -ne $demoHashes[$file]) { throw "哈希不一致：$file" }
}
rg -n -g '!a03-contract-audit/docs/superpowers/specs/2026-09-04-workspace-organization-design.md' -g '!a03-contract-audit/docs/superpowers/plans/2026-09-04-workspace-organization.md' 'a03-demo/' .
```

Expected: 三个原文件哈希一致；除 `archive/a03-demo/` 新路径外无旧路径引用。

- [ ] **Step 5：提交归档**

```powershell
git add -- archive CLAUDE.md a03-contract-audit/docs/backend-modules.md a03-contract-audit/frontend/src/stores/demo.ts
git diff --cached --check
git commit -m "chore: archive legacy frontend prototype"
```

### Task 5：建立唯一交付索引并校准状态

**Files:**
- Create: `deliverables/README.md`
- Modify: `a03-contract-audit/README.md`

- [ ] **Step 1：创建交付索引**

`deliverables/README.md` 分为三个表格：

1. 正式新版材料：链接到 `../a03-contract-audit/契鉴_项目详细方案_重构版.docx` 和 `../a03-contract-audit/docs/project-overview/契鉴_项目概要介绍_重构版.docx`。
2. 历史材料：链接到项目内原 17 章详细方案及 12 页概要，仅标注“历史版本”。
3. 待制作材料：PPT、测试报告与测试用例、团队过程材料、演示视频。

索引必须写明：PDF 视觉验收产物位于本地忽略目录，尚未选定最终提交版时不得复制到 `deliverables/`；真实 52 文件、PostgreSQL、OCR 准确率、OpenClaw/GPU 和能耗仍按证据矩阵状态表述。

- [ ] **Step 2：更新项目 README 材料入口**

在 `a03-contract-audit/README.md` 的“当前交付材料”前增加仓库级索引链接 `../deliverables/README.md`，并将新版两份 DOCX 标记为当前推荐材料；旧版条目明确标记历史版本。不得改写自动化测试和硬指标数字。

- [ ] **Step 3：验证所有 Markdown 链接目标**

```powershell
$targets = @(
  'a03-contract-audit/契鉴_项目详细方案_重构版.docx',
  'a03-contract-audit/docs/project-overview/契鉴_项目概要介绍_重构版.docx',
  'a03-contract-audit/docs/contract-solution/契鉴_项目详细方案.docx',
  'a03-contract-audit/docs/project-overview/契鉴_项目概要介绍.docx'
)
foreach ($target in $targets) {
  if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "交付物不存在：$target" }
}
'PASS deliverable targets'
```

Expected: 输出 `PASS deliverable targets`。

- [ ] **Step 4：提交交付索引**

```powershell
git add -- deliverables/README.md a03-contract-audit/README.md
git diff --cached --check
git commit -m "docs: add canonical deliverables index"
```

### Task 6：完整验收并生成工作树清理清单

**Files:**
- Create: `a03-contract-audit/docs/worktree-cleanup-inventory.md`
- Modify: `a03-contract-audit/PROGRESS.md`

- [ ] **Step 1：运行目录治理检查**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File a03-contract-audit/docs/workspace-organization-check.ps1
git status --short --ignored -- .planning a03-contract-audit/outputs
```

Expected: 检查输出 `PASS workspace organization`；两个本地目录显示 `!!` 而不是 `??`。

- [ ] **Step 2：运行材料专项与差异检查**

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest a03-contract-audit/docs/competition-materials/scripts/test_audit_materials.py -v
git diff --check
```

Expected: 8 项材料审计测试通过；`git diff --check` 退出码 0。

- [ ] **Step 3：运行完整质量门禁**

```powershell
Set-Location a03-contract-audit
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
Set-Location ..
```

Expected: 评测专项、后端全量、前端测试、类型检查和生产构建五个阶段均返回 0，`.quality-gate/summary.json` 的 `status` 为 `passed`。

- [ ] **Step 4：生成只读工作树盘点**

`a03-contract-audit/docs/worktree-cleanup-inventory.md` 必须记录：

- `master` 与远端差距。
- `codex/materials-redesign` 已合并但工作树含未跟踪 `outputs/`，列出文件数、总大小和清单 SHA-256。
- `codex/contract-solution` 登记目标不存在，可在确认后由 `git worktree prune` 修剪。
- `codex/enterprise-hard-indicators` 与 `codex/collaboration-acceptance-package` 未纳入本次删除。
- 明确写出“本次未删除工作树、未删除分支、未推送”。

清单数据使用以下只读命令获得：

```powershell
git worktree list --porcelain
git status --short --branch
git -C .worktrees/materials-redesign status --short --branch
rg --files .worktrees/materials-redesign/a03-contract-audit/outputs | Sort-Object
```

- [ ] **Step 5：更新项目进度**

在 `a03-contract-audit/PROGRESS.md` 顶部增加 2026-09-04 记录，写明目录治理范围、三个附件与原型哈希保持、目录检查结果、完整门禁结果以及工作树尚未删除的边界。

- [ ] **Step 6：提交验收记录**

```powershell
git add -- a03-contract-audit/docs/worktree-cleanup-inventory.md a03-contract-audit/PROGRESS.md
git diff --cached --check
git commit -m "docs: record workspace organization verification"
```

- [ ] **Step 7：最终复核**

```powershell
git status --short --branch
git log --oneline -7
git diff origin/master..HEAD --check
```

Expected: 工作区无意外已跟踪改动；`.planning/` 与 `a03-contract-audit/outputs/` 不再显示为未跟踪；提交历史包含治理检查、根入口、参考资料、原型归档、交付索引和验收记录。

## 工作树清理确认点

上述任务完成后暂停并向用户展示 `a03-contract-audit/docs/worktree-cleanup-inventory.md`。只有用户再次明确同意，才执行以下独立操作：

1. 将 `materials-redesign` 工作树未跟踪验收产物复制到主项目忽略目录并校验逐文件 SHA-256。
2. 从仓库主目录执行 `git worktree remove <精确工作树路径>`。
3. 确认失效工作树目标路径不存在后执行 `git worktree prune`。
4. 不删除 `codex/materials-redesign` 分支，除非用户另行明确要求。
