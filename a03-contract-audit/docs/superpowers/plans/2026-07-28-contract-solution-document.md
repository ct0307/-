# Contract Solution Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一份以目标态需求与规划视角撰写、40 至 50 页、达到或超过往届获奖作品质量的《契鉴——企业级合同合规审查与多维报表生成智能体系统项目详细方案》Word 文档。

**Architecture:** 文档采用“可核验研究资料 → 分章 Markdown 内容 → PNG 图表资产 → docx-js 构建 → Word 字段刷新 → PDF 渲染验收”的流水线。正文不记录项目现状，现有代码只作为目标方案可行性和技术边界的内部依据；测试章节只定义方法、指标和验收阈值，实测数据由独立测试报告承载。

**Tech Stack:** Markdown、Node.js、docx-js、sharp、Python 3、python-docx、pypdf、pypdfium2、Microsoft Word COM、PowerShell。

---

## 文件结构

### 新建目录与文件

- `docs/contract-solution/README.md`：说明源稿、资产、构建和验证流程。
- `docs/contract-solution/research/source-register.md`：公开资料来源、发布日期、统计口径、引用位置。
- `docs/contract-solution/research/scoring-matrix.md`：四项评分标准到章节、图表和证据的映射。
- `docs/contract-solution/content/01-overview.md` 至 `17-conclusion-references.md`：17 个一级章节源稿。
- `docs/contract-solution/assets/diagrams/*.png`：14 张核心架构与流程图。
- `docs/contract-solution/assets/screenshots/*.png`：经裁切和脱敏的界面设计示意。
- `docs/contract-solution/scripts/generate_diagrams.js`：生成统一视觉风格的 PNG 图表。
- `docs/contract-solution/scripts/build_docx.js`：解析分章 Markdown 并生成 DOCX。
- `docs/contract-solution/scripts/update_word_fields.ps1`：刷新目录、交叉引用、页码并导出 PDF。
- `docs/contract-solution/scripts/validate_document.py`：检查结构、篇幅、图片、禁用表述和 PDF 页面。
- `docs/contract-solution/契鉴_项目详细方案.docx`：最终可编辑交付物。
- `docs/contract-solution/契鉴_项目详细方案.pdf`：用于逐页验收的固定版式文件。

### 保留不改

- `docs/A03企业级合同合规审查系统_产品需求分析文档.docx`
- `docs/A03企业级合同合规审查系统_产品需求分析文档.md`
- `PROGRESS.md`
- 用户提供的往届参考 DOCX 与赛题 PDF

---

### Task 1: 建立研究来源与评分覆盖矩阵

**Files:**
- Create: `docs/contract-solution/README.md`
- Create: `docs/contract-solution/research/source-register.md`
- Create: `docs/contract-solution/research/scoring-matrix.md`
- Read: `docs/superpowers/specs/2026-07-28-contract-solution-document-design.md`
- Read: `README.md`
- Read: `PROGRESS.md`

- [ ] **Step 1: 创建文档工作区说明**

在 `README.md` 中明确文档定位、目录职责、构建命令、验证命令和“详细方案不记录项目进度”的写作边界。

- [ ] **Step 2: 收集权威公开资料**

优先检索全国人大、国务院、最高人民法院、司法部、国家网信办、中国信通院和企业官方资料。每条来源记录以下字段：

```markdown
| 编号 | 机构 | 标题 | 发布日期 | URL | 可引用结论 | 统计口径 | 使用章节 | 核验日期 |
|---|---|---|---|---|---|---|---|---|
```

不得写入来源不明的市场规模、用户访谈或企业案例。

- [ ] **Step 3: 建立评分矩阵**

将项目创意 20 分、实施方案 30 分、技术实现与交付 30 分、项目展示 20 分映射到具体章节、图表和验收项。每个评分点至少对应一个章节和一个可验证证据形式。

- [ ] **Step 4: 检查研究来源完整性**

Run:

```powershell
rg -n "\| [0-9]{2} \|" docs/contract-solution/research/source-register.md
rg -n "项目创意|实施方案|技术实现与交付|项目展示" docs/contract-solution/research/scoring-matrix.md
```

Expected: 来源登记表有连续编号；四项评分均至少出现一次。

- [ ] **Step 5: Commit**

```powershell
git add docs/contract-solution/README.md docs/contract-solution/research
git commit -m "docs: establish solution research and scoring matrix"
```

---

### Task 2: 重构目标态需求与产品方案章节

**Files:**
- Create: `docs/contract-solution/content/01-overview.md`
- Create: `docs/contract-solution/content/02-industry-market.md`
- Create: `docs/contract-solution/content/03-users-requirements.md`
- Create: `docs/contract-solution/content/04-positioning-innovation.md`
- Create: `docs/contract-solution/content/05-overall-solution.md`
- Read: `docs/A03企业级合同合规审查系统_产品需求分析文档.md`
- Read: `docs/contract-solution/research/source-register.md`

- [ ] **Step 1: 撰写项目概述与赛题解读**

用 1200 至 1600 字说明命题背景、业务对象、问题边界、建设任务、交付目标和设计原则。不得出现开发完成度或历史修改记录。

- [ ] **Step 2: 撰写行业、政策、市场与竞品分析**

用 2500 至 3500 字形成“政策驱动—业务痛点—技术机会—市场格局”论证链。竞品采用能力维度比较表，至少比较合同接入、风险解释、知识治理、人工闭环、私有化和审计六个维度，不推断竞品未公开实现。

- [ ] **Step 3: 撰写用户与需求分析**

定义法务主管、财务主管、业务人员、系统管理员和管理层五类角色；覆盖合同审查、复核整改、知识治理、经营分析和系统管理五类场景；为核心需求标注 P1/P2/P3、依赖和验收标准。

- [ ] **Step 4: 撰写产品定位、创新与总体方案**

创新点限定为可解释双 Agent、逐风险证据链、人机责任闭环、多维数据治理和企业私有化五类。说明系统非目标，避免将通用聊天、自动法律裁决或替代法务判断纳入范围。

- [ ] **Step 5: 执行禁用表述检查**

Run:

```powershell
rg -n "当前已|已经完成|截至目前|后续完善|完成度|现有项目|本项目目前" docs/contract-solution/content/0[1-5]-*.md
```

Expected: 无匹配结果。

- [ ] **Step 6: Commit**

```powershell
git add docs/contract-solution/content/01-overview.md docs/contract-solution/content/02-industry-market.md docs/contract-solution/content/03-users-requirements.md docs/contract-solution/content/04-positioning-innovation.md docs/contract-solution/content/05-overall-solution.md
git commit -m "docs: draft target-state product solution chapters"
```

---

### Task 3: 撰写总体架构与业务流程章节

**Files:**
- Create: `docs/contract-solution/content/06-functional-process.md`
- Create: `docs/contract-solution/content/07-architecture-deployment.md`
- Read: `backend/app/api/v1/router.py`
- Read: `backend/app/models/models.py`
- Read: `frontend/src/router/index.ts`
- Read: `docker-compose.yml`

- [ ] **Step 1: 建立目标态功能域模型**

将系统划分为合同接入、智能审查、人工复核、整改闭环、知识治理、报表分析、系统治理七个功能域。每个功能域写明职责、输入、输出、依赖和失败处理。

- [ ] **Step 2: 描述端到端业务流程**

覆盖上传与校验、加密存储、文本解析、要素抽取、双 Agent 审查、RAG 取证、人工复核、整改、归档和报表更新，并定义异常分支和人工接管点。

- [ ] **Step 3: 设计目标态分层架构**

定义交互层、应用服务层、智能编排层、知识检索层、数据持久层和基础设施层。将单体开发形态与企业部署目标统一为可分阶段演进的模块化架构，不虚构未定义的微服务接口。

- [ ] **Step 4: 设计部署拓扑和数据流**

明确浏览器、Nginx、FastAPI、异步任务、关系数据库、对象存储、本地模型服务、向量检索和监控组件的信任边界、网络路径、数据落点与降级路径。

- [ ] **Step 5: 检查架构术语一致性**

Run:

```powershell
rg -n "合同接入|智能审查|人工复核|整改闭环|知识治理|报表分析|系统治理" docs/contract-solution/content/06-functional-process.md
rg -n "交互层|应用服务层|智能编排层|知识检索层|数据持久层|基础设施层" docs/contract-solution/content/07-architecture-deployment.md
```

Expected: 七个功能域和六个技术层全部出现。

- [ ] **Step 6: Commit**

```powershell
git add docs/contract-solution/content/06-functional-process.md docs/contract-solution/content/07-architecture-deployment.md
git commit -m "docs: define business flow and target architecture"
```

---

### Task 4: 撰写智能审查与 RAG 关键技术章节

**Files:**
- Create: `docs/contract-solution/content/08-dual-agent.md`
- Create: `docs/contract-solution/content/09-rag-evidence.md`
- Create: `docs/contract-solution/content/10-parsing-risk.md`
- Read: `backend/app/services/audit/auditor.py`
- Read: `backend/app/services/audit/runner.py`
- Read: `backend/app/services/rag/retriever.py`
- Read: `backend/app/services/parser/extractor.py`
- Read: `backend/app/llm/factory.py`

- [ ] **Step 1: 撰写双 Agent 协同方案**

定义法务 Agent、财务 Agent 和编排器的职责边界、输入输出契约、共享上下文、交叉验证、冲突消解、风险分档、超时重试和人工接管。不得使用“两个模型各跑一次”作为协同定义。

- [ ] **Step 2: 撰写 RAG 知识治理与混合检索方案**

覆盖知识分类、结构化元数据、条文切片、正文哈希、向量与 BM25 双路召回、RRF 融合、余弦阈值、合同类型/维度/有效期过滤、版本替换、事务回滚和缓存失效。

- [ ] **Step 3: 撰写逐风险可验证证据链**

为每条候选风险定义“风险分类 + 原文”检索查询；正式依据只能来自通过可靠性和适用性检查的来源；无可靠来源时输出人工复核提示并限制置信度，不允许兜底规则冒充法规。

- [ ] **Step 4: 撰写解析、要素抽取和风险结构**

定义 PDF/DOCX/TXT 解析、表格读取、扫描件 OCR 扩展、正则初提、LLM 精抽、一致性校验、风险 JSON 契约、原文定位、建议生成和错误分级。

- [ ] **Step 5: 检查责任边界**

Run:

```powershell
rg -n "人工复核|置信度|可靠来源|降级|责任边界" docs/contract-solution/content/08-dual-agent.md docs/contract-solution/content/09-rag-evidence.md docs/contract-solution/content/10-parsing-risk.md
```

Expected: 五类责任边界关键词均有明确规则，而非仅列名词。

- [ ] **Step 6: Commit**

```powershell
git add docs/contract-solution/content/08-dual-agent.md docs/contract-solution/content/09-rag-evidence.md docs/contract-solution/content/10-parsing-risk.md
git commit -m "docs: specify agent rag and extraction design"
```

---

### Task 5: 撰写数据、安全与交互设计章节

**Files:**
- Create: `docs/contract-solution/content/11-data-security.md`
- Create: `docs/contract-solution/content/12-interaction-design.md`
- Read: `backend/app/core/security.py`
- Read: `backend/app/core/crypto.py`
- Read: `backend/app/services/masking.py`
- Read: `backend/app/services/audit_log.py`
- Read: `frontend/src/config/nav.ts`
- Read: `frontend/src/views/*.vue`

- [ ] **Step 1: 定义目标态数据模型**

描述用户、合同、风险、知识切片、整改、规则、模板、审计日志、模型调用和基础字典等实体，列出主键、关键字段、关系、索引、生命周期和敏感等级。

- [ ] **Step 2: 定义纵深安全体系**

覆盖身份认证、RBAC、部门隔离、最小权限、文件加密、字段脱敏、传输加密、密钥管理、审计追踪、数据备份、删除策略、模型数据边界和供应链安全。

- [ ] **Step 3: 定义信息架构与关键交互**

围绕工作台、合同审查、协同分析、整改、报表、知识库、历史、规则和系统管理构建导航与任务流。对加载、空、错误、权限不足、批量部分失败和移动端状态给出规则。

- [ ] **Step 4: 定义无障碍与响应式验收**

明确键盘导航、焦点可见性、ARIA、对比度、触控尺寸、390/1440/2560px 适配和无横向溢出要求。

- [ ] **Step 5: Commit**

```powershell
git add docs/contract-solution/content/11-data-security.md docs/contract-solution/content/12-interaction-design.md
git commit -m "docs: specify data security and interaction design"
```

---

### Task 6: 撰写实施、测试、可行性与价值章节

**Files:**
- Create: `docs/contract-solution/content/13-implementation.md`
- Create: `docs/contract-solution/content/14-testing-acceptance.md`
- Create: `docs/contract-solution/content/15-feasibility-risk.md`
- Create: `docs/contract-solution/content/16-value-roadmap.md`
- Create: `docs/contract-solution/content/17-conclusion-references.md`
- Read: `docs/contract-solution/research/source-register.md`
- Read: `docs/contract-solution/research/scoring-matrix.md`

- [ ] **Step 1: 撰写四阶段实施方案**

对业务闭环、可信增强、企业交付、规模化运营四阶段分别定义目标、范围、角色、资源、依赖、里程碑、交付物和退出标准。团队只使用角色名称，不填写个人姓名。

- [ ] **Step 2: 撰写测试与验收体系**

为功能、AI 效果、RAG、性能、安全、可靠性、兼容性和体验测试定义样本、公式、阈值、判定规则和证据形式。不得写入阶段性知识条数或测试总数。

- [ ] **Step 3: 撰写可行性与风险分析**

从技术、经济、组织、合规和社会五个方面论证，并建立风险登记表，至少覆盖模型幻觉、法规失效、敏感数据泄露、供应商锁定、性能波动、误用责任和推广阻力。

- [ ] **Step 4: 撰写项目价值与路线图**

区分企业效率价值、风险控制价值、管理价值、社会价值和商业价值；商业模式只描述可验证的产品化路径，不编造收入或市场份额。

- [ ] **Step 5: 整理参考文献**

将 `source-register.md` 中实际使用的来源编号写入参考文献，确保正文引用编号连续、URL 可访问、机构和发布日期完整。

- [ ] **Step 6: Commit**

```powershell
git add docs/contract-solution/content/13-implementation.md docs/contract-solution/content/14-testing-acceptance.md docs/contract-solution/content/15-feasibility-risk.md docs/contract-solution/content/16-value-roadmap.md docs/contract-solution/content/17-conclusion-references.md
git commit -m "docs: complete implementation validation and value chapters"
```

---

### Task 7: 生成统一风格的核心图表

**Files:**
- Create: `docs/contract-solution/scripts/generate_diagrams.js`
- Create: `docs/contract-solution/assets/diagrams/*.png`

- [ ] **Step 1: 定义图表主题与输出清单**

脚本固定 A4 可读的蓝灰主题：背景 `#FFFFFF`、主色 `#245B78`、辅色 `#4C7A92`、强调色 `#C48A2C`、文字 `#1F2933`、边框 `#C9D4DC`。输出 14 张 1800px 以上宽度的 PNG，并为每张图保留对应 SVG 源字符串供重建。

- [ ] **Step 2: 实现统一渲染函数**

在脚本中提供以下接口：

```javascript
async function renderDiagram({ name, width, height, title, bodySvg }) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    <rect width="100%" height="100%" fill="#FFFFFF"/>
    <text x="60" y="72" font-family="Microsoft YaHei" font-size="36" font-weight="700" fill="#1F2933">${title}</text>
    ${bodySvg}
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(path.join(OUTPUT_DIR, `${name}.png`));
}
```

所有文本通过 XML 转义函数处理，连接线不得穿过文本，节点保持稳定尺寸。

- [ ] **Step 3: 生成 14 张核心图**

输出文件名固定为：

```text
01-problem-solution.png
02-user-collaboration.png
03-functional-architecture.png
04-contract-review-flow.png
05-technical-architecture.png
06-private-deployment.png
07-agent-sequence.png
08-rag-evidence-flow.png
09-parsing-data-flow.png
10-core-er.png
11-security-layers.png
12-implementation-roadmap.png
13-testing-loop.png
14-product-roadmap.png
```

- [ ] **Step 4: 执行图像验证**

Run:

```powershell
$env:NODE_PATH='C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' docs/contract-solution/scripts/generate_diagrams.js
Get-ChildItem docs/contract-solution/assets/diagrams/*.png | Measure-Object
```

Expected: `Count = 14`，每张图片非空且宽度不少于 1800px。

- [ ] **Step 5: 视觉抽样**

使用 `view_image` 检查全部图的联系表，再逐张检查技术架构、Agent 时序、RAG 流程、ER 图和实施路线图。修复文字截断、连线穿字、颜色对比不足和节点拥挤。

- [ ] **Step 6: Commit**

```powershell
git add docs/contract-solution/scripts/generate_diagrams.js docs/contract-solution/assets/diagrams
git commit -m "docs: add solution architecture diagrams"
```

---

### Task 8: 准备界面设计示意素材

**Files:**
- Create: `docs/contract-solution/assets/screenshots/*.png`
- Read: `frontend/package.json`
- Read: `frontend/src/views/*.vue`

- [ ] **Step 1: 启动本地前后端服务**

使用项目既有环境启动后端与前端，不安装或升级依赖。若真实 LLM 不可用，只采集不依赖模型调用的页面；不得为了截图写入伪造业务结果。

- [ ] **Step 2: 采集关键页面**

至少采集登录、工作台、合同审查、风险复核、协同分析、整改、报表、知识库和权限管理九类页面。截图避免暴露密钥、个人信息和本地绝对路径。

- [ ] **Step 3: 裁切并统一尺寸**

使用 `sharp` 将截图裁切为正文可读比例，保留页面标题和关键业务区域；输出宽度不少于 1600px。文件名使用 `01-login.png` 至 `09-admin.png`。

- [ ] **Step 4: 验证页面状态**

正常、空、错误和移动端状态至少各有一个设计示意；图片在正文中统一标注“界面设计示意”，不得写成完成度证据。

- [ ] **Step 5: Commit**

```powershell
git add docs/contract-solution/assets/screenshots
git commit -m "docs: add solution interface design examples"
```

---

### Task 9: 实现 Markdown 到 DOCX 构建器

**Files:**
- Create: `docs/contract-solution/scripts/build_docx.js`
- Test: `docs/contract-solution/scripts/validate_document.py`

- [ ] **Step 1: 定义 Markdown 子集解析器**

构建器支持一级至三级标题、普通段落、有序/无序列表、表格、粗体、代码字面量、图片指令和分页指令。图片指令格式固定为：

```markdown
![图 5-1 系统技术架构](../assets/diagrams/05-technical-architecture.png)
```

解析器遇到无法识别的非空行必须抛出包含文件名和行号的错误，不得静默丢弃。

- [ ] **Step 2: 定义 Word 样式**

设置 A4 页面、上下 2.54cm、左右 2.6cm；正文中文使用宋体 10.5pt，英文使用 Arial；一级标题 16pt、二级 14pt、三级 12pt；固定行距与段前后距；表格使用 DXA 双宽度和浅蓝表头；图片居中并带题注。

- [ ] **Step 3: 构建封面、目录、页眉页脚和正文**

封面包含项目名、系统全称、团队名、赛题编号、命题单位、文档类型和版本。目录使用 Word TOC 域；页眉显示项目简称与文档名；页脚显示版本和当前页码。

- [ ] **Step 4: 合并 17 章源稿**

按 `01` 至 `17` 的文件顺序加载；每个一级章节新起一页；自动生成图表编号、书签和交叉引用；参考文献链接使用可点击超链接。

- [ ] **Step 5: 生成 DOCX**

Run:

```powershell
$env:NODE_PATH='C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' docs/contract-solution/scripts/build_docx.js
```

Expected: 生成 `docs/contract-solution/契鉴_项目详细方案.docx`，进程退出码为 0。

- [ ] **Step 6: 创建结构验证脚本**

`validate_document.py` 使用 python-docx、zipfile 和 pypdf，至少验证：17 个一级章节、字符数范围、图片数、表格数、目录域、页眉页脚、参考文献、禁用表述和缺失图片。

- [ ] **Step 7: Commit**

```powershell
git add docs/contract-solution/scripts/build_docx.js docs/contract-solution/scripts/validate_document.py
git commit -m "docs: add reproducible docx build pipeline"
```

---

### Task 10: 刷新 Word 字段并导出 PDF

**Files:**
- Create: `docs/contract-solution/scripts/update_word_fields.ps1`
- Modify: `docs/contract-solution/契鉴_项目详细方案.docx`
- Create: `docs/contract-solution/契鉴_项目详细方案.pdf`

- [ ] **Step 1: 实现 Word COM 刷新脚本**

脚本以只读检查源路径后打开 DOCX，更新目录、字段和页码，保存 DOCX，再以 `wdFormatPDF = 17` 导出同名 PDF。使用 `try/finally` 确保 Word 进程退出，`DisplayAlerts = 0` 避免交互阻塞。

- [ ] **Step 2: 刷新并导出**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File docs/contract-solution/scripts/update_word_fields.ps1
```

Expected: DOCX 与 PDF 均存在且非空，PDF 页数位于 40 至 50 页。

- [ ] **Step 3: 验证 DOCX 包结构**

Run:

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'C:\Users\chentao\.agents\skills\docx\scripts\office\validate.py' docs/contract-solution/契鉴_项目详细方案.docx
```

Expected: 验证通过，无损坏关系、缺失媒体或无效 XML。

- [ ] **Step 4: Commit**

```powershell
git add docs/contract-solution/scripts/update_word_fields.ps1 docs/contract-solution/契鉴_项目详细方案.docx docs/contract-solution/契鉴_项目详细方案.pdf
git commit -m "docs: build contract solution deliverables"
```

---

### Task 11: 执行内容、评分和视觉验收

**Files:**
- Modify: `docs/contract-solution/content/*.md`
- Modify: `docs/contract-solution/scripts/build_docx.js`
- Modify: `docs/contract-solution/契鉴_项目详细方案.docx`
- Modify: `docs/contract-solution/契鉴_项目详细方案.pdf`
- Read: `docs/contract-solution/research/scoring-matrix.md`

- [ ] **Step 1: 运行自动化文档验证**

Run:

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' docs/contract-solution/scripts/validate_document.py docs/contract-solution/契鉴_项目详细方案.docx docs/contract-solution/契鉴_项目详细方案.pdf
```

Expected: 17 章齐全；正文字符 25000 至 35000；页面 40 至 50；有效图片 20 至 30；表格 10 至 15；禁用表述、空标题、丢图和断链均为 0。

- [ ] **Step 2: 检查评分覆盖**

逐项读取 `scoring-matrix.md`，为每个评分点确认正文位置、图表位置和证据形式。任何没有对应内容的评分点必须补写后重新构建。

- [ ] **Step 3: 渲染全部 PDF 页面**

使用 pypdfium2 以 150 DPI 渲染全部页面，生成 4×N 联系表。检查封面、目录、章节起始页、表格跨页、图片清晰度、页眉页脚、孤行孤字和大面积异常留白。

- [ ] **Step 4: 重点逐页检查**

单独检查目录、市场数据引用、技术架构、部署拓扑、Agent 时序、RAG 证据链、ER 图、实施计划、测试矩阵和参考文献页面。修复文字重叠、字体缺失、图题断页和引用编号错误。

- [ ] **Step 5: 读者测试**

让无上下文读者仅依据成品回答：项目解决什么问题、核心创新是什么、系统如何工作、如何控制 AI 风险、如何实施、如何验收、商业与社会价值是什么。答不清的问题对应章节必须重写。

- [ ] **Step 6: 最终重建与验证**

重新执行图表生成、DOCX 构建、字段刷新、PDF 导出和自动验证，确认所有命令退出码为 0。

- [ ] **Step 7: Commit**

```powershell
git add docs/contract-solution
git commit -m "docs: finalize competition contract solution"
```

---

## 规格追踪矩阵

| 设计规格主题 | 实施任务 | 验收方式 |
|---|---|---|
| 文档定位 | Task 1、Task 2 | README 写作边界；禁用进度表述扫描为 0 |
| 目标读者 | Task 2、Task 5、Task 6 | 评审、企业管理者、研发、运维四类阅读目标均有对应内容 |
| 内容结构 | Task 2 至 Task 6 | 17 个分章文件全部存在并进入 DOCX |
| 目标能力边界 | Task 2 至 Task 5 | 功能域、输入输出、依赖、异常与验收标准齐全 |
| 图表与视觉设计 | Task 7、Task 8、Task 9 | 14 张核心图、界面示意、统一样式和图表编号 |
| 研究与引用策略 | Task 1、Task 2、Task 6 | 来源登记、正文引用与参考文献逐项对应 |
| 测试与验收设计 | Task 6、Task 11 | 指标方法完整；不出现阶段性测试数量 |
| 实施与演进策略 | Task 6 | 四阶段目标、资源、依赖、交付物和退出标准齐全 |
| 交付规格与质量门槛 | Task 9 至 Task 11 | DOCX/PDF 结构、篇幅、页面、图表和视觉验证通过 |
| 明确不包含的内容 | Task 1、Task 11 | 原 PRD 与 PROGRESS.md 未覆盖；无虚构成果或范围外材料 |

## 完成定义

- 交付 DOCX 与 PDF 均能正常打开，目录和页码正确。
- 文档全文采用目标态需求与规划视角，不出现开发现状和进度汇报。
- 17 个一级章节、14 张核心图和评分覆盖矩阵全部完成。
- 市场、政策、法律和竞品结论均有可核验来源。
- 测试章节只定义方法、指标和阈值，不固化阶段性知识量和测试数量。
- 详细方案达到 40 至 50 页、2.5 万至 3.5 万中文字符，并通过自动与逐页视觉验收。
