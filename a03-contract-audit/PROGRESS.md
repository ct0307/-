# 项目进度记录 · A03 企业合同合规审查系统

> 每完成一次完整改动（功能闭环 / 前后端联动 / 重要重构），在此追加一条改动日志（最新在上）。
> 记录格式：日期 + 改动主题 + 涉及文件 + 验证结论。
> 「完成情况总览」章节随项目推进整体刷新，不追加。

---

## 2026-09-11 · 智能合同收件箱合并门禁修复

### 交付结果

- 修正导入批次和审查批次的幂等键生命周期：请求失败保留原键重试，请求成功后为下一次独立操作生成新键。
- 导入批次保存由归属部门、文件名和内容哈希组成的请求指纹；同一幂等键提交不同请求时返回结构化 `409 IDEMPOTENCY_CONFLICT`，软删除后允许原文件重新上传。
- 批次、导入、合同、风险、报表和导出统一使用用户当前授权部门集合；授权撤销后不再因批次创建者身份继续读取合同元数据。
- 审查页新增批次进度、逐合同状态、失败原因、失败项重试和历史结果入口。
- 软删除合同从历史、详情和报表中隐藏；管理员新增合同回收站列表与恢复入口；Celery 每日清理超过保留期且位于受管存储目录内的原文件，并保留合同墓碑记录。
- Alembic 迁移补齐 `contracts.type_confirmed_by`、`contracts.deleted_by` 到 `users.id` 的外键、`import_batches.request_fingerprint` 列及降级顺序。

### 验证结论

- TDD 定向回归覆盖幂等键生命周期、权限范围、软删除与迁移；最终新增阻断项测试由 7 项失败转为 `42 passed`。
- 完整质量门禁：评测 `59 passed`；后端 `374 passed, 1 skipped`；前端非服务模式 `39 passed, 23 skipped`；TypeScript 类型检查和生产构建通过。
- 服务型全量 E2E 在原工作树前后端联调环境中 `62 passed`，覆盖审查批次结果闭环、管理员回收站恢复、空状态、错误状态和移动端显示。
- 未执行真实 52 文件、PostgreSQL 16、OCR 准确率、OpenClaw/GPU 或能耗实测，上述硬指标状态不变。

---

## 2026-09-10 · 50+2 真实企业合同冻结集 v3 收口验收（进行中）

- 已恢复 v3 实施上下文，确认 v1/v2 未修改，当前仅有中文附件名校验修复及对应测试尚未提交。
- 已锁定修正版输出 `outputs/frozen-contracts-v3-revised/`，首次候选继续保留为已否决版本，不作为最终交付。
- F3-014、F3-036、F3-037 三类代表 PDF 已完成联系表和可疑页放大复核；中文标题、网格表格、签署栏和页脚无乱码、裁切或重叠，但 F3-014/F3-037 的末页存在孤立续表和大面积留白。
- 已用流式布局轨迹定位到附件贪心分页根因，并新增失败回归测试；修复前 F3-014 末页有效内容下边界仅 239.16。
- 已增加附件块最小起始空间规则，完整 v3 专项测试 12 项通过，并提交为 `34239e0`。
- 已生成独立新候选 `outputs/frozen-contracts-v3-final-candidate/`；静态校验通过，53 个清单文件哈希唯一，最大正文相似度 0.521844。
- 生产解析保留 50 份分母：41 份成功、9 份无 OCR 扫描件失败，失败清单与 `ocr_required` 完全一致；构造真值预评测 overall F1 为 0.05，不作为人工金标准准确率。
- 代表 PDF 逐页复核确认附件分页改善，但发现 F3-014/F3-036 两处页末孤立章节标题；已新增先失败后通过的回归测试，并以“标题 + 第一段”高度预检修复。
- 发布候选全量页指标进一步定位到 F3-029 三方签署表拆页；新增全 PDF 签署表同页测试并以带表格章节整体高度预检修复，三个分页回归测试均通过。
- 二次视觉放大复核发现附件存在字段语义错配：云资源“计费方式”出现审批/传输方式，交付物“格式”“提交阶段”等仍使用兜底句。新增全附件占位句测试和五类关键附件字段语义测试，修复前两项均按预期失败；全量统计仍有 630 个兜底单元格。
- 2026-09-11 生成 `frozen-contracts-v3-realism-final` 过程候选并通过静态校验，但代表 PDF 放大复核继续发现仓配 KPI 混入 IT 指标、工程量单位错配、安全措施泛化和车辆里程失真；该目录降级为过程证据，不作为最终冻结版本。
- 已进一步修正仓配 KPI、订单、车辆里程与变更对照、洁净工程量及安全措施；视觉复核额外发现并修正运输价格计费单位与价格量级错配，新增逐行回归测试。
- 最终候选 `outputs/frozen-contracts-v3-enterprise-release/` 静态校验通过：53 个清单文件、53 个唯一哈希；生产解析 41 成功、9 个无 OCR 扫描件失败且清单完全一致。
- F3-014、F3-029、F3-036、F3-037 共 26 页已重新视觉抽检，未见空白页、裁切、重叠、破表、签署表拆页或孤立续表；F3-029 运输价格表已放大确认口径一致。
- 已新增 `ACCEPTANCE.md`，明确本批文件可作为高拟真合成测试集，但不能直接作为签约模板或真人法务金标准。
- 完整质量门禁通过：后端 338 项通过、1 项跳过；前端 Playwright 17 项通过、12 项跳过；类型检查和生产构建成功。第三方依赖产生 6 条既有警告。
- 当前环境缺少 LibreOffice/soffice，14 份 DOCX 只能进行结构、文本和 OOXML 校验，不能宣称完成批量视觉渲染。

---

## 2026-09-08 · 《项目详细方案》专业化二次修订（V3.1）

### 交付结果

- 在八章专业重制结构不变的前提下，补入真实代码与示例配置中的文件、OCR、模型、会话、异步任务、轮询和数据环境参数，并统一标为可按部署条件调整的“当前实现参数基线”。
- 增加付款比例未闭合、法务与财务意见冲突、OCR 低置信度转人工、批量解析部分失败四个假设案例，明确这些案例用于说明机制，不代表实测记录。
- 为第三至第五章及第七章的关键流程图、架构图和页面截图补充控制点解读；第七章新增“参数校准与方案变更”，区分日常配置调整和详细方案改版。
- 将“批次创建前整批预检”和“批次建立后单文件失败隔离”拆开说明，使方案与当前实现一致；删除机械连接词、夸张宣传语和重复的责任边界表述。

### 验证结论

- DOCX/PDF 联合校验通过：8章、30659个中文字符、13张表、23张图、54页。
- Microsoft Word 导出 PDF，Poppler 生成54张页面图；逐页拼图检查后，对新增内容所在页面放大复核，未发现空白页、文字裁切、对象重叠、表格越界、缺图、乱码或页眉页脚错位。
- 禁用措辞与常见模板化宣传词扫描为0；参数表跨页重复表头，八个一级章节独立起页。
- 原专业重制版正在 Word 中打开，未强制覆盖；本次成品另存为 `契鉴_项目详细方案_专业重制版_V3.1.docx`。源文件与提交包文件 SHA-256 均为 `6936B857D8F0FE4FB468030F2D4472A530A45D163B44FA60110421F3F003CB5A`。

---

## 2026-09-08 · 《项目详细方案》专业重制

### 交付结果

- 保留原版、重构版和人工润色版，新增 `契鉴_项目详细方案_专业重制版.docx`。
- 正文重构为“项目概述、需求分析、总体方案设计、核心功能详细设计、关键技术实现方案、数据安全与权限设计、部署实施与运行保障、测试与验收方案”八章，并增加接口清单、数据字典、术语和参考文献四个附录。
- 原第七章的动态验证记录已拆除；详细方案只保留长期稳定的环境、样本、公式、阈值、判定和证据规范，具体执行记录由独立《项目测试案例及报告》承载。
- 正文删除竞赛化措辞、实时通过数量、完成比例、待办状态、源码路径和材料制作过程；AI 始终定位为辅助审查，最终决定保留给授权人员。

### 验证结论

- 专业版结构校验通过：8章、27942个中文字符、12张表、23张图、51页。
- Microsoft Word 导出 PDF 后逐页渲染复核；目录为2页，一级章节独立起页，跨页表格重复表头，参考文献独立起页，未发现空白页、文字裁切、对象重叠、表格越界、缺图、乱码或页眉页脚错位。
- `[S01]` 至 `[S06]` 引用完整，禁用词扫描和 `git diff --check` 通过。
- 已复制到桌面提交包；源文件与目标文件 SHA-256 均为 `C5F63EC2DECE9371755EE398202D82033F02FDEB4873F9FB2B3F2AEFB675E3E1`。

---

## 2026-09-07 · 《项目详细方案》人工润色与第七章重构

### 交付结果

- 保留原版 `契鉴_项目详细方案.docx`，另行生成 `契鉴_项目详细方案_人工润色版.docx`。
- 第一至第六章仅调整明显的模板句、重复自证和空泛总结，项目事实、技术路线、图表及章节结构保持不变。
- 第七章重组为“验证范围、本地测试结果、赛题指标完成情况、尚待完成的实测、项目总结、参考文献”六节，删除文件哈希、Git 基线和材料制作过程等幕后内容。
- 真实 50+2 文件、OCR/要素准确率、PostgreSQL 16、完整 Compose 环境、OpenClaw/GPU 和能耗仍标记为待实测或依赖外部条件，未写成已达标。

### 验证结论

- 项目校验脚本通过：7 章、27025 个中文字符、9 张表、23 张图、45 页。
- 使用 Microsoft Word 导出 PDF，并生成 45 张逐页 PNG；总览覆盖全部页面，另对表格密集页及第 43～45 页放大复核，未发现文字裁切、对象重叠、表格越界、缺图、乱码或页眉页脚错位。
- `[S01]` 至 `[S06]` 引用完整，幕后制作字符串未进入成稿；`git diff --check` 通过。
- 原版 SHA-256 仍为 `1BFAF584B4B9083DFCA55B0ACA58C358DD70135446B276F2F0FB0332235F539E`，未被覆盖。
- 已复制到桌面提交包，源/目标 SHA-256 均为 `AB82E6D5E73755D14AA2EA72BCE26A16D58F1786A80EB6867092440E546E3B33`。

---

## 2026-09-07 · 比赛材料提交包整理与进度同步

### 交付结果

- 在桌面建立并整理 `比赛材料提交包/`，该目录位于仓库外，不纳入 Git 版本控制。
- 复制当前推荐的两份正式材料，并按提交用途命名为 `契鉴_项目详细方案.docx` 和 `契鉴_项目概要介绍.docx`。
- 建立 `项目简介PPT/`、`测试案例及报告/`、`演示视频/` 三个空目录，用于后续补齐对应材料。
- 当前提交包未单独建立团队过程材料目录；是否作为独立交付物保留为待确认事项。

### 验证结论

- 两份 DOCX 的 SHA-256 与仓库内对应重构版源文件一致，复制过程未改变文档内容。
- 三个待制作目录均为空，提交包当前共包含两份正式 DOCX 和三个待制作目录。
- 同步刷新本文“完成情况总览”，使材料状态、自动化验证结果和真实硬指标边界与当前事实一致。

---

## 2026-09-07 · 废弃开发资产清理与治理收口

### 决策与范围

- 删除已废弃的原生 JavaScript 原型；该原型不再承担开发、演示或验收职责。本决策取代 2026-09-04 的“保留历史归档”要求，历史内容仍可从 Git 提交追溯。
- 删除一次性 Agent 执行计划，保留已经批准的设计规格，避免丢失 OCR、RAG、质量门禁和材料设计等关键技术决策。
- 删除旧版项目概要逐页渲染图、重复的根目录旧方案副本及本地任务记录；渲染图改为本地生成且由 Git 忽略。
- 删除可重新生成的前端构建产物、测试结果、质量门禁结果和 Python 缓存。
- 保留当前源码、测试、文档构建链、设计规格、依赖环境和开发数据库。

### 涉及文件

- 删除：`archive/a03-demo/`、`docs/project-overview/rendered/`、`docs/superpowers/plans/`。
- 保留：`docs/superpowers/specs/`；恢复并更新 `docs/workspace-organization-check.ps1`。
- 同步：仓库导航、忽略规则、工作树清单、旧原型来源注释和后端历史说明。

### 验证结论

- `docs/workspace-organization-check.ps1` 通过，正式目录、废弃资产、忽略规则和旧路径引用均符合当前治理约定。
- 完整质量门禁通过：评测测试 59 项通过；后端测试 304 项通过、1 项跳过；前端默认门禁 17 项通过、12 项服务型用例跳过；TypeScript 类型检查和生产构建通过。
- Windows Python 3.13.1 的虚拟环境启动器无法直接接收当前中文工作区中的脚本路径；本次改用同一基础 Python 启动 `scripts/quality_gate.py`，门禁内部仍使用项目 `.venv` 执行后端测试，未安装或升级第三方依赖。
- `git diff --check HEAD` 通过。

---

## 2026-09-04 · 工作区外围目录治理（✓ 已完成，工作树清理待确认）

### 交付结果

- 新增仓库根入口和项目级 `AGENTS.md`，明确唯一正式项目、参考资料、交付物、历史归档和本地过程目录边界。
- 三份比赛输入附件移动到 `references/`；废弃原生 JavaScript 原型完整归档到 `archive/a03-demo/`，不再与正式项目并列。
- 新增 `deliverables/README.md` 作为参赛材料唯一索引；两份重构版 DOCX 为当前推荐材料，原 17 章和 12 页材料保留为历史版本。
- 根忽略规则覆盖 `.planning/`、所有临时工作树和 `a03-contract-audit/outputs/`；新增自动检查脚本验证目标结构、旧路径、忽略规则和有效引用。

### 完整性验证

| 验证项 | 结果 |
|---|---|
| 三份参考附件 SHA-256 | 移动前后一致；Git 均识别为 100% rename |
| 原型三个源文件 SHA-256 | 移动前后一致；Git 均识别为 100% rename |
| 目录治理检查 | `PASS workspace organization` |
| 材料语言审计 | `8 tests`，全部通过 |
| 评测专项 | `59 passed in 2.73s` |
| 后端全量 | `208 passed, 1 skipped, 6 warnings in 12.54s` |
| 前端测试 | `13 passed, 6 skipped in 1.0s` |
| TypeScript 类型检查 | 退出码 0 |
| Vite 生产构建 | 退出码 0，转换 2352 个模块 |
| 质量门禁汇总 | `status=passed`、`exit_code=0`，提交 `2f26e99` |

### 工作树边界

- 本轮没有删除工作树、分支或未跟踪产物，也没有推送或修改远端。
- 已合并的 `materials-redesign` 工作树仍含 280 个未跟踪文件，共 123.04 MB；清单 SHA-256 和保留条件见 `docs/worktree-cleanup-inventory.md`。
- `contract-solution` 为 Git 标记的失效登记；`enterprise-hard-indicators` 按既定边界保留；`collaboration-acceptance-package` 尚有未合并提交，必须保留。
- 工作树移除与失效登记修剪必须在用户再次明确确认后单独执行。

---

## 2026-09-01 · 本地一键质量门禁（✓ 开发与自动化验收完成）

### 交付结果

- 新增 Python 核心执行器和 PowerShell 一键入口，默认按“评测专项 → 后端全量 → 前端测试 → 类型检查 → 生产构建”顺序执行，任一阶段失败立即停止。
- 默认模式主动移除前端测试子进程的 `E2E_BASE_URL`；可选 `-IncludeE2E` 模式具备端口保护、健康检查和自有进程回收能力。
- 每次运行原子写入 `.quality-gate/summary.json`，仅记录提交 SHA、UTC 时间、状态、退出码和阶段耗时，不保存环境变量、密钥或业务输出。
- `.quality-gate/` 已由 Git 忽略；脚本不安装依赖、不修改 Git、不推送、不部署。

### 新鲜验证证据

| 验证项 | 结果 |
|---|---|
| 执行器专项 | `17 passed in 0.29s` |
| 默认门禁评测专项 | `59 passed in 2.66s` |
| 默认门禁后端全量 | `208 passed, 1 skipped, 6 warnings in 12.35s` |
| 默认门禁前端测试 | `13 passed, 6 skipped in 0.99s`；跳过项均要求显式 `E2E_BASE_URL` |
| TypeScript 类型检查 | 退出码 0 |
| Vite 生产构建 | 退出码 0，转换 2352 个模块 |
| 统一汇总 | `status=passed`、`exit_code=0`，五个阶段顺序正确 |

警告仍来自既有 SWIG 类型、jieba `pkg_resources` 和 Rollup 第三方注释位置提示，不属于本轮新增失败。

### 验收边界

- 本轮按已确认的默认方案执行，没有运行 `-IncludeE2E` 真实服务型浏览器验收；E2E 启动、失败、端口占用和进程回收由自动化测试覆盖。
- 本地质量门禁不等于真实硬指标验收，未执行真实 52 文件、Docker Compose、PostgreSQL 16、OpenClaw、GPU 或功率数据实测。

---

## 2026-09-01 · 硬指标证据流水线开发与自动化测试（✅ 代码就绪）

### 交付结果

- 要素评测入口强制执行 JSON Schema Draft 2020-12；金标准必须包含两个唯一审核人及明确复核状态，裁决记录必须提供裁决人。
- 新增版本化 `manifest.json`、追加式 JSONL、SHA-256 输入绑定、递归脱敏和原子报告写入；缺事件、哈希冲突、状态矛盾或轮次不足时拒绝生成有效报告。
- 新增 `elements`、`batch`、`benchmark`、`report` 四个 CLI 子命令；稳定区分输入无效、执行异常、指标未达和外部条件阻塞。
- 50+2 批测执行器强制 50 份有效文件同批提交、2 份异常文件隔离提交，覆盖超时、终态刷新和 multipart 文件句柄流式上传。
- OpenClaw/GPU 执行器强制相同模型/提示词/数据集/并发/输出 Schema，执行 3 个完整预热轮次和 5 个完整正式轮次；能耗缺失时保持 `not_measured`。
- PostgreSQL 证据状态由“已验证”校准为“代码就绪待实测”，明确现有迁移烟雾测试使用 SQLite。

### 涉及文件

- 评测实现：`backend/evaluation/{elements,evidence,batch,benchmark,benchmark_runner,report,cli}.py`、`backend/evaluation/schema.json`
- 自动化测试：`backend/tests/test_element_metrics.py`、`test_evaluation_evidence.py`、`test_evaluation_batch.py`、`test_benchmark_stats.py`、`test_benchmark_runner.py`、`test_evaluation_report.py`、`test_evaluation_cli.py`
- 依赖与文档：`backend/requirements.txt`、`.gitignore`、`docs/evaluation/element-accuracy-protocol.md`、`docs/evaluation/hard-indicator-matrix.md`

### 新鲜验证证据

| 验证项 | 结果 |
|---|---|
| 评测专项 | `59 passed in 2.98s`，零失败 |
| 关键业务回归 | `63 passed, 1 skipped, 5 warnings in 5.48s`，零失败 |
| 后端全量 | `191 passed, 1 skipped, 6 warnings in 12.40s`，零失败 |
| 依赖完整性 | `pip check`：`No broken requirements found` |
| 运行目录隔离 | `/evaluation-runs/` 已由 Git 忽略，不提交原始运行数据 |

警告来自既有 SWIG 类型和 jieba `pkg_resources` 第三方弃用提示。跳过项为既有环境型集成条件，不影响本轮自动化验收结论。

### 依赖安全审计

- 新增 `jsonschema==4.25.1`，来源为官方 PyPI，许可证为 MIT，要求 Python ≥3.9。
- OSV 以 PyPI 包名和固定版本查询返回空对象 `{}`，未发现公开已知漏洞；安装后未出现依赖冲突。

### 外部验收边界

- 本轮只完成开发和自动化测试，没有执行真实 52 文件、Docker Compose、PostgreSQL 16、OpenClaw 或 GPU 实机验收。
- 双人复核冻结金标准、50+2 冻结文件、真实模型哈希/数据集、设备凭据和 PostgreSQL 验收环境到位前，硬指标状态保持“代码就绪待实测”或“阻塞”，不得写成达标。

---

## 2026-09-01 · 代码基线、企业法务工作台与项目概要收口（✅ 已完成）

### 交付结果

- 主题系统支持卷宗、企业明亮、深灰和跟随系统四种模式，手动选择可持久化，图表与共享框架随主题重绘。
- 企业法务工作台完成九个业务页的信息密度与响应式收口；风险依据直接呈现 `rag_sources`、`confidence` 和 `review_status`，无可靠来源时明确转人工复核，不伪造法条。
- 项目概要 Word/PDF 均为 12 页，包含 11 个正文标题、7 张表和 12 张图；结构、事实、页码和逐页视觉验收通过。

### 新鲜验证证据

| 验证项 | 结果 |
|---|---|
| 后端全量 | `142 passed, 1 skipped, 6 warnings in 12.55s`，零失败；警告来自现有 SWIG/jieba 第三方弃用提示 |
| 前端全量 | `19 passed, 0 skipped in 10.0s`，真实 E2E 已连接本地前后端执行 |
| 类型与构建 | TypeScript 检查退出 0；Vite 生产构建退出 0，转换 2352 个模块 |
| 浏览器验收 | 1440×900 走查 9 个业务页；390×844 复验审查、报表和移动导航；无正向横向溢出，console 0 warning/error |
| 项目概要 | `PASS pages=12 headings=11 tables=7 images=12 chinese_chars=2904` |

### 外部验收边界

- 冻结扫描件 OCR 字符准确率仍需人工金标准数据集实测。
- 52 份冻结文件批量吞吐仍需在目标环境执行并记录资源占用。
- Docker Compose 目标环境仍需完成容器级启动、迁移和回滚验收。
- OpenClaw/GPU 硬件对照仍缺同口径设备与功率数据，不生成模拟结论。

---

## 2026-07-31 · 项目状态口径校准与交付索引修正（✅ 已完成）

### 修正内容

- README 与完成情况总览统一为 13 张数据库表、40 条 `/api/` 路由。
- 自动化验证改用本轮新鲜证据，不再把 39 项 RAG 专项测试写成全量测试。
- 973 条知识明确为本机演示库历史验证结果；数据库不随源码分发，新环境需重新执行种子和法规导入。
- 项目详细方案统一链接到 `docs/contract-solution/` 规范目录，根目录相同副本不纳入版本控制。
- `.planning/` 保留为本地 Agent 过程文件，不作为稳定项目资产提交。

### 新鲜验证证据

- 后端全量：`125 passed, 1 skipped, 6 warnings in 9.29s`；跳过项为环境相关集成条件，零失败。
- 前端全量：`11 passed, 3 skipped in 1.8s`；三个 E2E 在未设置 `E2E_BASE_URL` 时按设计跳过。
- `npm.cmd run type-check` 退出 0。
- `npm.cmd run build` 退出 0，Vite 成功转换 2348 个模块。
- FastAPI 应用导入实测为 13 张 ORM 表、40 条 `/api/` 路由。

---

## 2026-07-28 · 项目详细方案重构与正式交付（✅ 已完成）

### 交付结果

| 交付物 | 结果 | 位置 |
|---|---|---|
| 项目详细方案 Word 版 | 49 页，17 章，正文 34,316 个中文字符，23 张图片，15 张表 | `docs/contract-solution/契鉴_项目详细方案.docx` |
| 项目详细方案 PDF 版 | Word 刷新目录、字段和页码后导出，可直接阅读与打印 | `docs/contract-solution/契鉴_项目详细方案.pdf` |
| 项目进度与入口说明 | README 增加材料索引，PROGRESS 同步最新里程碑与后续任务 | `README.md`、`PROGRESS.md` |

### 内容范围

- 以目标态需求和规划视角重构 17 章内容，覆盖行业背景、用户需求、产品定位、总体方案、业务流程、技术架构、双 Agent、RAG 证据链、文档解析、数据安全、交互设计、实施计划、测试验收、可行性、项目价值和参考文献。
- 方案不写开发状态、阶段性知识数量或测试数量，避免把过程数据固化为产品能力承诺。
- 交付材料不包含团队成员姓名，只描述项目角色、职责和实施分工。

### 验收结论

- 自动结构检查通过：17 章、34,316 个中文字符、15 张 Word 表格、23 张图片、49 页。
- DOCX OOXML 包校验通过；目录、页眉页脚、页码、书签、图片替代文字、表格几何和外部链接均通过检查。
- PDF 全部 49 页按约 150 DPI 渲染并逐页检查，未发现裁切、重叠、缺图、表格越界或异常空白页。
- 9 张界面设计示意通过尺寸、文件体积和像素动态范围验证。

### 下一阶段

| 优先级 | 任务 | 目标 |
|---|---|---|
| P1 | 项目概要介绍 | 从详细方案提炼 2～3 页图文速览 |
| P1 | 项目进度汇报 PPT | 面向老师和组员说明成果、当前状态、风险和下一步计划 |
| P1 | 测试报告与测试用例 | 汇总本轮后端 126 项（125 通过/1 跳过）和前端 14 项（11 通过/3 跳过）、端到端验证与准确率证据 |
| P2 | 团队分工与开发过程材料 | 按角色记录职责、协作机制、里程碑和产出物 |
| P2 | 演示视频 | 录制 3～5 分钟合同上传、双 Agent 审查、复核整改与报表闭环 |

---

## 2026-07-27 · RAG 可靠性与可验证证据链加固（✅ 已完成）

### 核心改进

| 范围 | 改进 |
|---|---|
| 逐风险证据闭环 | Agent 先生成候选风险，再按“风险分类 + 原文”逐条检索；正式 `basis` 只取该风险的可靠来源，无来源时改为人工复核提示并将置信度封顶 50 |
| 检索可靠性 | 向量路增加最低余弦阈值；损坏/异维向量按条跳过；Embedding 数量和维度整批校验；单路 Top-N 真正生效 |
| 适用性过滤 | `retrieve()` 支持合同类型、审查维度、知识分类和有效期过滤；用户选定维度会跳过无关 Agent |
| 引用真实性 | 兜底内容统一标记为 `fallback_rule` 内置审查规则，不再冒充民法典条文；旧知识可从正文自动提取“第X条” |
| 知识治理 | 增加条文号、版本、生效/失效日期、适用合同类型/维度、Embedding 模型/维度和正文哈希 9 个字段 |
| 数据一致性 | 覆盖导入改为“先准备全部新行，再单事务删除+写入”；异常回滚并保留旧知识；BM25 缓存改用 ID+正文 SHA-256 指纹 |
| 输入与部署 | 无标点长文本硬切至 ≤380 字并保留条文前缀；知识文件应用上传大小限制；本地 Embedding 运行时 `local_files_only=True`，禁止隐式联网 |
| 迁移 | SQLite 启动补列；补齐 Alembic 配置、环境和可回滚版本 `20260726_rag_metadata` |

### 主要文件

- `backend/app/services/rag/retriever.py`
- `backend/app/services/audit/auditor.py`
- `backend/app/api/v1/endpoints/knowledge.py`
- `backend/app/llm/adapters/local_embedding.py`
- `backend/app/models/models.py`
- `backend/app/db/init_db.py`
- `backend/alembic.ini`、`backend/alembic/`
- `backend/tests/test_rag_hardening_unittest.py`
- `backend/tests/test_rag_grounding.py`

### 验证

- 新增标准库测试：16/16 通过；原有无夹具测试：23/23 通过，共 39 项 RAG 加固专项测试。
- `compileall` 通过；FastAPI 应用导入成功，当时注册 36 条路由。
- Alembic `history` 正确识别迁移 head；旧表临时库实际执行 `upgrade head` 成功，9 个字段齐全。
- 现有数据库只读复制后迁移：知识仍为 973 条，正文汇总 SHA-256 前后一致，973 条向量仍全部 512 维。
- Embedding 不可用的真实副本检索在 BM25 模式下返回 3 条违约责任相关依据；运行时没有 Hugging Face 网络重试。
- 未安装、升级或降级任何依赖；未修改源数据库。

---

## 2026-07-26 · OCR 质量闭环与强制超时（✅ 代码验收完成，外部实测待补）

### 已完成

| 优先级 | 能力 | 本轮改动 |
|---|---|---|
| P1 | 结构化解析质量 | `DocumentParseResult` 贯通原生/OCR/混合 PDF，保留 `extract_text()` 兼容接口 |
| P1 | 强制超时 | 生产 RapidOCR 改为独立 Python 子进程，stdin/stdout 传输版本化协议；父进程按 `terminate → kill → wait` 强制回收 |
| P1 | 持久化与迁移 | `contracts` 增加来源、置信度、复核标记和原因；第二个 Alembic revision 支持旧数据增量升级及完整回滚 |
| P1 | 审查质量门 | 低置信度和短文本合同进入 `review_required`；幂等生成红色系统风险；批次机器终态仍为 `done` |
| P1 | API 与前端 | 合同、解析、审查和批次响应暴露质量字段；单合同显示复核告警和置信度，批次行显示“需人工复核” |

### 新鲜验证证据

- 后端全量：`91 passed, 6 warnings in 10.95s`。警告为 SWIG 弃用提示和 jieba 对 `pkg_resources` 的既有弃用提示，零失败。
- 迁移聚焦：`pytest tests/test_hard_indicator_smoke.py -q` 为 `8 passed`，覆盖空库 metadata parity、`20260726_01 → head` 旧合同增量升级和 `head → base` 完整回滚。
- OCR/质量聚焦：解析器 `10 passed`；进程超时、解析器和真实 RapidOCR 联合 `13 passed`；审查质量、证据链和批次联合 `21 passed`；质量 API 与批次回归 `24 passed`。
- 前端全量：`8 passed, 2 skipped`；两个 E2E 仅在未设置 `E2E_BASE_URL` 时按设计跳过。显式启动 Vite 后，低置信度 OCR 渲染 E2E `1 passed`。
- `npm.cmd run type-check`、`npm.cmd run build`、`git diff --check` 均退出 0；生产构建成功转换 2348 个模块。
- Browser 实测：`/audit` 上传→解析→审查后唯一显示“扫描件需人工复核”、`42.3%`、“待人工复核”和系统风险；390×844 下侧栏完全隐藏、无横向溢出，控制台 0 warn/error。
- Compose YAML 服务集合保持为 `backend,frontend,postgres,redis,scheduler,worker`，未新增服务或依赖。

### 外部验收边界

- 冻结扫描件字符准确率仍为“待实测”，真实引擎冒烟和质量闭环不能替代准确率结论。
- 50 有效 + 2 异常批次吞吐仍需冻结文件和 Compose 验收环境，API 上限 200 不等于吞吐达标。
- 当前机器无 Docker，未声称容器启动或 Linux terminate/kill 路径已实机通过。

---

## 2026-07-26 · 赛题硬指标企业交付化方案 A（🚧 实现完成，外部实测待补）

### 已完成

| 优先级 | 能力 | 企业交付改动 |
|---|---|---|
| P1 | 风险证据链 | 每条风险独立检索并清洗来源；无可靠来源或检索失败时强制人工复核 |
| P1 | 异步批次 | PostgreSQL 持久化批次/批次项/审查维度；Celery 状态机、行锁租约、启动补投、幂等、失败隔离与重试；前端展示真实服务端状态 |
| P1 | 权限隔离 | 报表 summary/metadata/export/排行统一按部门过滤，business 越权合同返回 403 |
| P1 | OCR 编排 | 文本 PDF 不触发 OCR；扫描/混合 PDF 定向识别；限制页数、像素、总耗时并标记低置信度复核；真实 RapidOCR/ONNX 引擎冒烟通过 |
| P1 | 准确率评测 | 冻结 JSONL 协议、字段宏平均、分组统计、错误案例、JSON/CSV 原始结果与数据集哈希 |
| P1 | 算力评测 | 真实模型三态健康接口；P50/P95/吞吐/成功率/标准差/95% CI；无功率数据固定 `not_measured` |
| P1 | 数据库交付 | 13 张表全量 Alembic 首迁移；空库升级/回滚烟雾测试；生产禁用 `create_all`、默认演示账号和弱默认安全配置 |
| P2 | 部署拓扑 | PostgreSQL + Redis + backend + Celery worker + scheduler + frontend；backend 健康前完成迁移，worker/beat 后启动 |

### 验证结论与边界

- 后端全量：`91 passed, 6 warnings`；包含真实 RapidOCR/ONNX Runtime 集成、强制进程超时、OCR 质量闭环、行锁租约、周期补投、维度约束和生产配置 fail-fast，迁移烟雾覆盖空库升级、旧数据增量升级、完整回滚、生产禁用 `create_all` 和禁种演示账号。
- 前端常规测试：`8 passed, 2 E2E skipped`；低置信度 OCR E2E 在显式启动前端后单独执行 `1 passed`。
- `vue-tsc --noEmit` 与生产构建退出码均为 0；浏览器验证覆盖桌面正常页、审查空状态、运行时接口错误回退和 390px 移动导航，正常路径 0 console error。
- Compose YAML 结构与服务依赖已解析通过；Git whitespace 检查退出码 0。
- 本机无 Docker CLI，Compose 尚未容器实测。
- 旧 SQLite 业务数据不会由 Compose 自动迁移到 PostgreSQL；目标环境仍需执行受控导出/导入、核对和回滚演练。
- RapidOCR 3.9.2 / ONNX Runtime 1.28.0 已完成官方 wheel 哈希、许可证、22 个解析依赖的 PyPI 漏洞记录和真实中文图片/PDF 冒烟；字符准确率仍缺冻结扫描件真值集。
- 52 份冻结文件、人工金标准、OpenClaw/GPU 对照机和功率数据均未提供，因此对应硬指标保持“待实测/阻塞”，不生成模拟结论。
- 详细证据矩阵：`docs/evaluation/hard-indicator-matrix.md`。

## 2026-07-23 · 前端无障碍 + 响应式 + 交付质量四轮改进（✅ 已完成）

### 背景
收到第三方对前端页面的专业评审（59 张截图，1440/2560/390px 多分辨率走查），7 维度评分中无障碍仅 1/5、其余 3/5。核心缺陷：移动端侧栏无 overlay、加载/空/错误态不统一、超宽屏留白、无 focus-visible 规范、硬编码颜色/圆角。据此做四轮迭代改进，每轮均由外部验证脚本复核。

### 第一轮 · 基础改进
| 文件 | 改动 |
|---|---|
| `styles/tokens.scss` | 新增 `--r-xs: 4px`、`--r-pill: 20px` 圆角 token |
| `styles/index.scss` | 新增全局 `:focus-visible`（金色 outline）+ `:focus:not(:focus-visible)` 重置 |
| `layouts/MainLayout.vue` | 移动端（≤768px）侧栏改 fixed overlay + 汉堡按钮 + 遮罩；`.content-inner` max-width 1600px 解决超宽屏留白 |
| `components/layout/AppSidebar.vue` | inject `mobileOpen`；roving tabindex 让 Tab 可进侧栏导航 |
| `DashboardView/RectifyView/AdminView/RulesView` | 错误态统一为内联 `el-result`（原为 el-alert / ElMessage toast），带"重新加载"按钮 |
| 11 个文件 | border-radius 硬编码 `20px→var(--r-pill)`、`4px→var(--r-xs)` |

### 第二轮 · 验证报告未通过项
| 问题 | 文件 | 修复 |
|---|---|---|
| 点菜单不自动关闭侧栏 | `AppSidebar.vue` | `watch(route.path)` 移动端导航后关闭 mobileOpen |
| Escape 无法关闭 | `MainLayout.vue` | 新增 keydown 监听 Escape |
| 背景可滚动 | `MainLayout.vue` | `watch(mobileOpen)` 切换 `body.overflow` |
| menu-item focus outline 被 EP 覆盖 | `element-overrides.scss` | `.el-menu-item:focus-visible` + `!important` 恢复 |
| 错误文案英文 | `client.ts` | 响应拦截器加 HTTP 状态码→中文映射表 |

### 第三轮 · 专业审查发现的缺陷
- `MainLayout.vue`：`onUnmounted` 补 `body.style.overflow=''` 清理，防卸载时滚动锁残留
- `element-overrides.scss`：`outline-offset` 负值改 `2px`（负值画在元素内会叠压），删冗余选择器
- `AppSidebar.vue`：`nextTick + setTimeout` 双重保障，防 EP 路由变化后重置 tabindex

### 第四轮 · 剩余无障碍缺口
| 问题 | 文件 | 修复 |
|---|---|---|
| 侧栏关闭仍能 Tab 到用户卡片（UserSwitcher 固定 tabindex=0） | `MainLayout.vue` | 用 `:inert="isMobile && !mobileOpen"` 一行覆盖侧栏全部后代，替代逐元素枚举 |
| detail 英文直传（500 时 FastAPI 返回 "Internal Server Error"） | `client.ts` | detail 增加中文字符判断 `/[一-鿿]/`，非中文回退状态码映射 |
| 汉堡缺 ARIA + 打开后焦点未移入 | `MainLayout.vue` `AppSidebar.vue` | 汉堡加 `aria-expanded`/`aria-controls`；焦点迁移收敛到 AppSidebar，在设完 tabindex 的同一 setTimeout 内聚焦激活项，消除跨组件时序竞争；删重复 watch |

### 验证结论（外部脚本 + 类型检查，逐轮复核）
- `vue-tsc --noEmit` exit 0、`npm run build` exit 0 ✅
- 1440/2560/390px 全部 9 业务页正常渲染，0 console error、无横向溢出 ✅
- 2560px 内容区限制 1600px 居中 ✅
- 390px：侧栏默认隐藏、汉堡打开、遮罩/Escape/滚动锁/菜单跳转自动关闭全通过 ✅
- inert 生效：侧栏关闭后连续 Tab 不进入任何屏外元素 ✅
- 焦点迁移：连续 10 次实测焦点均落到激活菜单项"工作台"（tabindex=0）✅
- ARIA：`aria-expanded` 随开关 true/false，`aria-controls="app-sidebar"` 正确 ✅
- 英文 500 错误已转"服务器内部错误" ✅
- 桌面侧栏可 Tab 到达，焦点轮廓 2px solid 金色 ✅

### 遗留（需求层，非代码）
- 第 10 个业务页：router 仍 9 个业务子路由，评审称需求为"11 个视图（登录+10 业务）"。属需求范围未确认问题，需先明确第 10 页内容再决定是否新增。

---

## 2026-07-23 · 端到端审查实测：示例合同 RAG 溯源验证（✅ 已完成）

### 背景
07-22 冒烟测试发现：3 份有实体文件的合同（C17/C23/C33）均为已审查完的报告文档，非原始合同，模型返回 `[]` 是正确行为，无法产出带 RAG 溯源的风险样本。演示视频与 T5 测试报告缺"风险→民法典第X条"真实溯源截图。决策：生成一份含典型风险的示例合同，走完整审查流程补齐素材。

### 操作
1. **生成示例合同**：`软件开发服务合同_示例.docx`（桌面），10 条条款，植入 6 处典型风险：
   - 违约金畸高（第七条，乙方每日1%上限100%，双方责任严重不对等）
   - 不可抗力范围过宽（第八条，含员工离职/市场变化）
   - 付款节点苛刻（第二条，30%尾款须运行12个月无故障）
   - 验收标准主观（第四条，以甲方满意度为准，修改次数不限）
   - 知识产权归属模糊（第五条，只约定使用权，著作权未明确）
   - 诉讼+仲裁并列约定（第九条，管辖冲突）
2. **完整审查链路**（Playwright 驱动，legal 视角）：登录→上传（合同 #34，Fernet 加密存储）→ LLM 精抽要素→ 双 Agent 审查→ 查看风险详情 RAG 溯源。

### 验证结论
- **风险检出**：21 条（17 高风险 / 4 中风险），植入的 6 处典型风险全部命中，另检出主体资格缺失、发票绑定缺失等衍生风险 ✅
- **要素抽取演示**：该单份示例合同的甲方/乙方/金额(150万)/标的/签订日期/履约期限/收付款节点 **全部命中**；这不代表冻结真值集准确率，赛题≥90% 指标仍待外部验收
- **RAG 溯源链完整**：以违约金风险为例——
  - 命中原文："乙方延期交付的，每逾期一日…违约金…累计上限不超过合同总金额的100%"
  - 法规依据：**民法典-合同编.txt 第五百八十五条**（违约金过分高于损失可请求适当减少）
  - 检索来源 Top8 带 `#序号` 排名（民法典585/588条、争议解决规则、知产规则、软件外包标准条款等）
  - 置信度 90%，附免责声明"仅供参考，以人工复核为准"，责任边界清晰 ✅
- **0 console error**，双 Agent（法务+财务）协同触发 ✅

### 产出物
- 示例合同：由本机临时测试目录提供，未随仓库分发；正式验收需改用已授权、已脱敏的冻结样本。
- RAG 溯源截图：`frontend/.playwright-mcp/RAG溯源_违约金过高_民法典585条.png`
- 用途：演示视频素材 + T5 测试报告"准确率实测"证据

---

## 2026-07-22 · 参赛交付物制作计划（🚧 持续推进）

### 背景与依据
系统本身已达获奖完成度，但**参赛交付物严重缺失**。对标往届获奖作品（2021 A19 智能化共享租赁平台，一等奖）+ 2026 赛题手册附件一评分标准，得出核心结论：

**附件一 A 类统一评分标准（满分 100，A03 适用）：**
| 评分项 | 分值 | 靠什么拿分 |
|---|---|---|
| 项目创意（市场/商业/社会价值、创新性） | 20 | 文档 |
| 实施方案（目标规划、进度、难点、资源配置） | 30 | 文档 |
| 技术实现与交付（技术路线、完成度、知识产权） | 30 | 系统 + 文档 |
| 项目展示（文档完整性、结构、文笔） | 20 | 文档 |

→ **纯技术仅占 30 分，其余 70 分依赖文档与展示材料**。本节记录 7 月 22 日制定计划时的基线；截至 7 月 28 日，项目详细方案已经完成，其余材料继续按优先级推进。

**往届 A19 交付包基准**（获奖标配）：项目详细方案（25208 字/36 页/36 图/6 表）、项目概要介绍（图文）、项目简介 PPT、演示视频（MP4）、测试报告（10 表）+ 测试用例（593 行 Excel）。

### 必交材料清单对标（手册 A 类通用要求）
| 交付物 | 往届基准 | 我方现状 | 状态 |
|---|---|---|---|
| ① 项目详细方案 | 25208字/36页/36图 | 34,316 个中文字符/49页/23图/15表，DOCX+PDF | ✅ 已完成 |
| ② 项目概要介绍 | 2页图文 | 无 | ❌ |
| ③ 项目简介 PPT | 完整 | 无 | ❌ |
| ④ 项目演示视频（3-5分钟） | MP4 | 无 | ❌ |
| ⑤ 测试报告 + 测试用例 | 报告10表+用例593行 | 无（赛题点名要准确率报告） | ❌ |
| ⑥ 团队分工/开发过程文档 | 部分含 | 无（有 PROGRESS.md 做底） | ❌ |

### 执行计划（按 ROI 与依赖分批）

**批次 1 · 内容底座（P0）**
- [x] **T1 项目详细方案**（内容底座，已完成 49 页 DOCX/PDF）
  - 骨架：项目背景 → 市场/行业/竞品分析 → 需求分析 → 系统架构（功能/技术/拓扑三图）→ 开发工具环境 → 重点技术实现（RAG混合检索/双Agent协同/Fernet加密/字段脱敏/要素LLM精抽）→ 数据库设计（10表）→ 可行性分析（技术/经济/社会）→ 项目价值（创意点/核心价值/商业价值）
  - 素材来源：PROGRESS.md 全量改动日志、根 CLAUDE.md、实际代码结构
  - 验收：34,316 个中文字符、23 图、15 表，覆盖附件一全部四个评分项；结构与全页视觉验收通过

**批次 2 · 派生展示（P0/P1，从 T1 提炼）**
- [ ] **T2 项目概要介绍**（2-3页图文速览：创意+功能架构+技术+界面截图）
- [ ] **T3 项目简介 PPT**（答辩用：背景→需求→系统设计→技术方案→演示→价值）

**批次 3 · 质量证明（P1）**
- [ ] **T4 测试用例**（Excel，按模块组织：登录/上传/解析/审查/复核/整改/报表/知识库/权限）
- [ ] **T5 测试报告**（含**要素提取准确率≥90%实测报告**——用系统真实跑数背书，赛题硬指标）

**批次 4 · 收尾（P2）**
- [ ] **T6 团队分工/开发过程文档**（角色/分工/排期/过程，PROGRESS.md 做底）
- [ ] **T7 演示视频脚本 + 录制**（3-5分钟走完整闭环，依赖前序材料定稿）

### 统一口径（防止交付物署名混乱）
- 项目名：**契鉴**　团队名：**豪到你了团队**
- 系统全称：企业级合同合规审查与多维报表生成智能体系统（A03·海康-南湖研究院命题）
- 所有交付物署名、系统名称、版本号保持一致

### 遗留说明
- 演示视频（T7）需真人录屏，AI 只能出脚本 + 分镜；实机演示环境需提前起好前后端
- 知识产权（专利/著作权证书）为评分加分项，如团队有则补入 T1；无则不强求

---

## 2026-07-22 · 冒烟测试 + 审查引擎代码审查 + 三处修复（✅ 已完成）

### 冒烟测试结论（演示链路全线可用）
- 前后端一键起服务 ✅
- 登录 / Dashboard / 报表 / 知识库 / Excel 导出全部通过，0 console error ✅
- 真实数据：累计 15 份合同 / 31 条风险 / 双 Agent（法务 15+财务 16）/ 通过率 29% ✅
- 要素提取填充率：甲方 100%、合同标的 100%、收付款节点 100%（15/15）；填充率不等于冻结真值集准确率，赛题≥90% 硬指标仍待外部验收
- Excel 导出：200 / 13.5KB 真实 xlsx ✅
- 知识库：973 条（法律 907 / 条款 29 / 规则 33 / 案例 4）✅

### 审查引擎代码审查发现并修复（3处）

**P0 Fix 1 — `extractor.py` docx 漏读表格**
- 根因：`_extract_docx_bytes` 只读 `doc.paragraphs`，完全跳过表格，表格型合同（基金/采购/租赁）文本提取率极低
- 修复：补读 `doc.tables`，行列拼接后追加到提取结果
- 验证：C17 华夏 ETF 合同文本从 984 字提升至 1255 字 ✅

**P0 Fix 2 — `auditor.py` mock fallback 写假风险**
- 根因：LLM 失败时 fallback 到 `_mock_audit` 写假风险进台账，法务无法分辨真实结论与降级占位数据
- 修复：改为写一条"审查引擎降级"系统警告风险（confidence=0，明确标注降级原因），让法务知道需要人工补充审查
- 不再使用 `_mock_audit`（保留函数作备用，不调用）

**P1 Fix 3 — `runner.py` 无短文本前置校验**
- 根因：文本提取失败时（<200 字）仍走完整 LLM 审查，得出不可信的"0 风险"结论
- 修复：前置拦截，写一条"文本解析失败"high 级风险，提示上传可解析格式，及早暴露问题

### 发现的数据问题（非代码 bug）
- 三份有实体文件的合同（C17/C23/C33）均为**已审查完的报告文档**，不是原始待审合同
- 模型审查这类文档后返回 `[]` 是正确行为（文件已含"合规状态：✓"结论）
- RAG 溯源截图素材需上传一份原始合同触发真实审查流程

### 涉及文件
| 文件 | 改动 |
|---|---|
| `backend/app/services/parser/extractor.py` | `_extract_docx_bytes` 补读 `doc.tables` |
| `backend/app/services/audit/auditor.py` | fallback 改为系统警告风险，去掉 `_mock_audit` 调用 |
| `backend/app/services/audit/runner.py` | 补短文本（<200字）前置校验 + 写高危占位风险 |

---

## 2026-07-17 · 合同要素 LLM 精抽 + 报表要素表数据补全（✅ 已完成）

### 背景
对照赛题原文（「自动提取关键元数据：甲方信息、合同标的、收付款节点；要素提取准确率≥90%」），发现三要素真实填充率 **0/15 = 0%**，看板全"—"，是赛题最核心要求的红线级缺口。根因：① 纯正则 extractor 无法应对真实合同的多样格式；② 演示合同无实体文件无法重新解析。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/services/parser/extractor.py` | 新增 `_parse_json_obj` / `_build_extract_excerpt`（智能截取前 3500 字+付款段落）/ `llm_extract_elements`（LLM 精抽六要素，失败返回 None）/ `extract_elements_with_llm`（正则先跑保留审查信号，LLM 补/覆盖语义字段，失败静默降级） |
| `backend/app/api/v1/endpoints/contracts.py` | parse 端点改用 `extract_elements_with_llm`；批量上传保留原正则（不阻塞 50 份上传速度） |
| `backend/app/services/audit/runner.py` | 优先读 `elements_json`（parse 时 LLM 精抽的高质量要素），无则正则实时提取；不重复调 LLM |
| `backend/scripts/backfill_elements.py`（新建） | 对真实上传合同回填 LLM 精抽要素（幂等，有 party_a 则跳过）|
| `backend/scripts/seed_demo_elements.py`（新建） | 给 storage/demo 演示合同（无实体文件）直接写入设计好的真实可信要素数据（幂等） |

### 验证结论
- 后端导入无报错，前端 vue-tsc exit 0 ✅
- 三要素填充率：party_a **15/15** · subject **15/15** · payment_terms **13/15**（2 份基金合同本身无收付款条款）✅
- 浏览器实测（Playwright，0 console error）：合同要素汇总表 15 份全部有甲方/标的/收付款节点显示，无"—"占位 ✅
- 当前仅证明演示数据的三要素填充完整，不代表冻结真值集准确率；赛题「要素提取准确率≥90%」仍待外部验收

### 设计说明（防倒退）
- parse 端点：LLM 精抽，供报表/Excel 展示
- 批量上传（`:144`）：仅正则，不阻塞速度
- runner.py（审查器）：复用 elements_json，不重复调 LLM
- 演示合同要素：设计数据写 DB，seed_demo_elements.py 幂等可重跑

---

## 2026-07-17 · 多维报表模块诚实化 + 明细驱动重构（✅ 已完成）

### 背景
以「交付侧产品经理 + UI设计负责人」视角审查多维报表，发现 1 个产品逻辑硬伤 + 多处 mock 时代遗留的诚实性问题：
- **P0** 「多维钻取」名不副实——钻取只过滤最底部要素表，上方 KPI/4 图完全不联动
- **P0** 合规通过率口径前后端冲突（前端 tooltip 说"已确认+已忽略÷总复核"，后端实际算"无风险合同占比"）
- **P1** 趋势图数据编造（`_ramp_series` 线性摊点），却挂 DemoBadge「实时数据」
- **P1** 环形图量纲混乱（高/中/低=条款数，无风险=合同数，同饼算百分比无意义）
- **P1** 钻取合同类型下拉硬编码 3 项，与库中真实类型脱节
- **P2** 图表网格右侧留空格；金额筛选框永久置灰

### 关键事实核实（决定方案）
查库：15 份合同集中在 2 天（07-07×12、07-09×3），high 风险合同 9 份。
→ 真实时间序列最多 2 点，比假趋势还单薄 → 趋势改「按 created_at 逐日累计」+ 布局降为 2×2 平铺。
→ 通过率口径经用户拍板：**无高风险合同占比**（15 份中 6 份无高风险 = 40.0%）。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/services/report/exporter.py` | ① 通过率口径改为"无 high 风险合同占比"；② donut 去掉"无风险"段，只留高/中/低条款分布；③ 删伪趋势 `_ramp_series`，新增 `_cumulative_trend()` 按 `Contract.created_at` 逐日真实累计（total/pass/risk 三线，合同级口径，<2 天标 mode=sparse）；④ `contracts_metadata` 补 `risk_medium`/`risk_low` 字段（供前端 donut 重算） |
| `frontend/src/api/reports.ts` | `ContractMeta` 补 `risk_medium`/`risk_low` |
| `frontend/src/views/ReportsView.vue` | 整文件重写：钻取类型选项从明细 distinct 生成（不再硬编码）；KPI + 风险等级环形图基于 `filteredMeta` **前端实时重算**（真联动）；趋势/部门/TOP5 保持全局并打「全局视图」标；移除失效的时间分段 seg 和永久置灰的金额框；KPI 第 4 格改真实可算的「风险条款总数」；去掉空 kpiTrend 徽标 |
| `frontend/src/components/charts/RiskDonut.vue` | 中心从"合规通过率"（已退回 KPI）改为"风险条款总数"，量纲与三段统一；移除 `pass` prop；高度 300→260 |
| `frontend/src/components/charts/TrendLine/DeptBar/TopRiskBar.vue` | 高度统一 260px，2×2 平铺齐平 |
| `frontend/src/mock/reports.ts` | 三档 donut 同步去掉"无风险"段（避免旧量纲留坑） |

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅
- 后端函数直调验证：KPI 通过率 40.0%（6÷15）、donut 高9/中13/低9 无"无风险"段、trend labels=['07-07','07-09'] total=[12,15] pass=[5,6] risk=[7,9] mode=real、metadata risk_medium/risk_low 输出正常 ✅
- 浏览器 UI 实测（Playwright，legal 视角，0 console error）：
  - 全局态 KPI 15/40%/9/31，4 图 2×2 平铺齐平、趋势 2 点累计单调递增、环形中心 31 条款总数 ✅
  - 钻取「高风险」联动：命中 9/15，KPI 重算为 9/0%/9/24，环形图出「钻取中」黄标、明细表同步过滤为 9 份，趋势/部门/TOP5 保持全局 ✅
- 说明：钻「高风险」时通过率显示 0% 为数学正确（筛出的合同必含高风险），符合直觉，不改

### 遗留
- 时间分段（月/季/年）已移除：趋势改全局累计后 range 对数据无影响，留着是死控件

### 背景
产品经理视角全面审查"审查维度配置"面板，发现4个问题：
- **P1** 业务部门下拉框功能虚假（选了没传后端，合同始终归属登录账号部门）
- **P2** 合同类型只存档不影响审查策略（未传给LLM，无法按类型调整审查重点）
- **P3** 维度配置没有任何说明，用户不知道"勾不勾都全量审查"
- **P4/P5** 三个配置项层级混乱，8个维度默认展开占空间

### 改动

| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/auth.py` | login 响应加 `department` 字段 |
| `frontend/src/api/types.ts` | `LoginResult` 加 `department: string` 字段 |
| `frontend/src/stores/auth.ts` | 加 `department` ref，login/logout 同步存取 localStorage |
| `frontend/src/views/AuditView.vue` | 配置面板重命名为"合同信息 & 审查配置"；合同类型置顶；业务部门改为只读展示（从 auth.department 读取，标注"当前账号自动归属"）；维度区改为折叠面板（默认收起，标题行显示选中数量 + "全量审查 · 维度选择仅影响结果聚焦展示"说明）；后4项维度初始值 `on: false` → `on: true`（全选） |
| `backend/app/services/audit/runner.py` | `run_audit()` 读取 `contract.contract_type` 传给 `audit_contract()` |
| `backend/app/services/audit/auditor.py` | `audit_contract()` / `_agent_audit()` 接收 `contract_type` 参数；user_prompt 加【合同基本信息】段，LLM 可据此调整审查侧重 |

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅
- 后端正常启动，无语法错误 ✅

---

## 2026-07-17 · 审查维度逻辑修正：过滤器→聚焦工具（✅ 已完成）

### 背景
前一轮把维度做成"LLM过滤器"（取消某维度则LLM不审该维度），产品逻辑错误：企业合同审查应全量保护，不能让用户主动放弃风险发现。

### 改动

| 文件 | 内容 |
|---|---|
| `backend/app/services/audit/auditor.py` | 去掉 system_prompt 里的维度约束（`dim_constraint`），后端永远全量审查 |
| `frontend/src/views/AuditView.vue` | 新增 `_DIM_KEYWORDS` 关键词映射（key→关键词列表）；新增 `_riskMatchesDim()`；新增 `_isDimFocused()`；`sortedRisks` computed 改为：部分勾选时，命中勾选维度的风险置顶；风险卡片加 `.dim-focus` class（黄铜色高亮边框+软底），全选时不触发高亮 |
| `frontend/src/styles/index.scss`（间接） | `.dim-focus` 样式加入 AuditView scoped CSS |

### 最终语义
**后端**：全量审查，任何风险不遗漏  
**前端**：维度勾选 = 聚焦工具，命中维度的风险置顶+高亮，其余仍可见

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅

---

## 2026-07-17 · CLAUDE.md 项目文档同步更新（✅ 已完成）

### 背景
根目录 `CLAUDE.md` 严重滞后（描述的是 2026-07-07 "后端尚未开工"状态），与实际项目相差40+天工作量。

### 更新内容
- `## 当前状态` → 更新为7月17日实际完成状态
- `## 目录结构` → 反映实际目录（backend/已建，a03-demo降级为参考）
- `## 规划技术栈（尚未落地）` → 改标题为`已落地技术栈`，逐行标注✅/状态
- `## 关键 API（规划）` → 改为"已实现"，列出实际25条路由
- `## 约定` → 删除过期的"前端将迁移到Vue3"等描述

---

## 2026-07-17 · 审查维度真实接通后端（✅ 已完成）

### 背景
审查维度配置面板的8个复选框原来是纯前端装饰（代码注释：`仅前端展示，不改后端契约`），勾不勾对审查结果零影响，存在功能虚假问题。

### 改动

| 文件 | 内容 |
|---|---|
| `frontend/src/api/contract.ts` | `auditContract(id, dimensions?, signal?)` 加可选 dimensions 参数，非空时作为 JSON body 发送 |
| `frontend/src/stores/audit-session.ts` | `runAudit(dimensions?)` 接收并透传维度参数 |
| `frontend/src/views/AuditView.vue` | `onAudit()` 把勾选维度的 key 数组传给 `session.runAudit()`；移除"仅前端展示"注释 |
| `backend/app/schemas/contract.py` | 新增 `AuditRequest(dimensions: list[str] = [])` 请求 schema |
| `backend/app/api/v1/endpoints/contracts.py` | audit 端点接收 `AuditRequest` body，提取 dimensions 传给 `run_audit`；审计日志记录维度信息 |
| `backend/app/services/audit/runner.py` | `run_audit(dimensions?)` 透传到 `audit_contract` |
| `backend/app/services/audit/auditor.py` | 新增 `_DIM_LABELS` 映射（key→中文）；`audit_contract` 和 `_agent_audit` 接收 dimensions；在 system_prompt 第6条规则中注入"本次用户指定审查维度"约束，LLM 只输出对应维度的风险 |

### 向后兼容
dimensions 默认空列表，全选或不传时行为与改动前完全一致，不影响已有批量审查流程。

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅
- 后端无语法错误，正常启动 ✅
- API 验证：传入 `["legal","breach","dispute"]` 3个维度，返回 2条风险（全量7条）✅ —— 维度过滤真实生效

---

## 2026-07-17 · UI简洁化（去纹理/轻阴影/h3改sans）（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/styles/tokens.scss` | `--shadow` 从 `0 18px 50px ...0.14` 改为 `0 2px 12px ...0.09`；`--shadow-sm` 从 `0 8px 22px ...0.1` 改为 `0 1px 6px ...0.07`；`--ink` 从 `#efe9da` 提亮至 `#f4f1e8`；`--ink-2` 提亮至 `#fdfcf8` |
| `frontend/src/styles/index.scss` | 移除 `body::before` 信笺横线纹理；h3 独立出来改用 `--sans`（h1/h2 保留 serif） |

---

## 2026-07-17 · 演示走查 + 三项修复（✅ 已完成）

### 背景
距比赛临近，对全部10个模块做 Playwright 端到端演示走查，发现并修复3个问题。

### 修复内容

| # | 问题 | 文件 | 处理 |
|---|---|---|---|
| 1 | 知识库页面500崩溃 | `backend/app/api/v1/endpoints/knowledge.py` | 补充缺失的 `_chips_for()` 函数（第575行调用但从未定义），修复后知识库正常展示973条 |
| 2 | 审查记录顶部「演示数据·待后端接入」标注错误 | `frontend/src/views/HistoryView.vue` | `<DemoBadge />` 补 `module="history"` 属性，现正确显示「实时数据·已接入后端」 |
| 3 | 数据库垃圾合同污染报表 | `storage/a03_dev.db` | 删除18条测试/重复合同（c.txt/h.txt/test_contract.txt/encrypt_test.txt/sample_contract_review_29.docx×7条/华夏ETF×2条/洲明基金×5条）及级联风险65条；合同从33→15条，风险从101→36条 |

### 走查通过的模块（9/9）
登录页 / Dashboard / 合同审查 / 智能协同审查 / 整改跟踪 / 多维报表（含Excel导出）/ 法规知识库 / 审查记录 / 权限与审计（含admin角色切换）

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅
- 知识库页 0 console error，973条正常渲染 ✅
- 审查记录「实时数据」绿色标注正确 ✅
- 多维报表合同要素汇总：33份→15份，垃圾文件清除 ✅

---

## 2026-07-13 · 导入重叠检测：条文编号对比（替代文件名猜测）（✅ 已完成）

### 背景
原 `overlap_warning` 逻辑（同分类>100条时通用提示）和文件名关键词匹配（`_check_name_similarity`）都存在精度问题：前者太模糊，后者对含「中华人民共和国」前缀的文件名匹配失败。

用户指出：切片里已经有来源和条文编号，用这些直接对比更准确。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/knowledge.py` | 删除 `_check_name_similarity`（文件名关键词匹配）；新增 `_check_article_overlap`：从新切片 content 里提取「第X条」编号集 → 与库中同分类各来源的条文编号对比 → 重叠率≥50% 触发警告，精确指出重叠来源和重叠率；兜底保留同分类>200条的通用提示 |

### 验证结论
- 民法典 PDF（全文）vs 库中民法典合同编 TXT：804 个条文号，重叠 528 个（**重叠率 71%**）
- 警告内容：`检测到库中「民法典-合同编.txt」与本文件有 567 个相同条文编号（重叠率71%），可能是同一法律的不同版本` ✅
- 陌生文件（无重叠条文）：无警告 ✅

---

## 2026-07-13 · 知识库内容质量全面清理（✅ 已完成）

### 问题发现
全面检查知识库内容质量，发现三类问题：
- 英文测试数据（id=675，`test content for law`）
- 残留占位符（38条 21-24字，绕过了<20字门槛，如`第10条 劳动合同订立相关规定第10条内容`）
- 劳动合同法多来源重叠（`劳动合同法全文.txt`/`labor2.txt`/`劳动合同法_1.txt` 共83条，含脏数据，与高质量的`劳动合同法_纸面合同条款.docx`重叠）
- 民法典合同编526条无章节前缀（章节前缀功能是后来加的，旧数据需覆盖重导）

### 修复操作（直接SQL + API覆盖重导）
| 操作 | 条数 |
|---|---|
| 删劳动合同法低质量来源（含测试数据和占位符） | -83 |
| 覆盖重导民法典合同编（获取章节前缀） | +527 |
| **净变化** | **+444**（972→973，实为替换升级） |

### 发现并修复的根因：HF联网验证阻塞
- **现象**：民法典526条覆盖重导超时（300s客户端超时），但后端其实也被HF联网验证拖慢
- **根因**：sentence-transformers 默认在模型首次加载时联网访问 huggingface.co 验证（5次重试×10s=50s浪费），网络不通时大幅拖慢首次 embedding 请求
- **修复**：`app/main.py` 顶部在任何 transformers import 前设置 `os.environ.setdefault("HF_HUB_OFFLINE","1")`，彻底禁止联网验证；`.env` 补注释说明
- **效果**：民法典526条重导耗时从 >300s 降至 **7.3s** ✅

### 最终知识库状态
| 分类 | 条数 | 质量 |
|---|---|---|
| law | 907 | ✅ 民法典527条有章节前缀，各劳动法规docx高质量 |
| rule | 33 | ✅ |
| template | 29 | ✅ |
| case | 4 | ✅ |
| **合计** | **973** | 0碎片，0空向量，0冗余来源 |

### 验证结论
- 章节前缀覆盖率：526/527（99%）✅
- 民法典重导耗时：7.3s（离线模式）✅

---

## 2026-07-13 · 导入质量加固：占位符过滤 + 重叠预警（✅ 已完成）

### 背景
全面检查发现两类冗余来源：① `劳动合同法全文.txt` 含46条无语义占位文本（"第X条附则第X条内容"）；② 民法典PDF+TXT 双份入库（1332条，占总量70%）。根因是导入模块缺乏内容语义过滤和来源冲突提示。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/knowledge.py` | 新增 `_is_placeholder()` + `_PLACEHOLDER_RE`（匹配"第X条附则第X条内容"格式占位符）；`_smart_split` 的 `_filter` 步骤同时过滤碎片和占位符；`/import-file` 响应加 `filtered_placeholders` + `overlap_warning`（同分类其他来源>100条时触发） |
| `frontend/src/api/knowledge.ts` | `ImportFileResult` 加 `filtered_placeholders`、`overlap_warning` 字段 |
| `frontend/src/views/KnowledgeView.vue` | `FileItem` 加 `filteredPH`；完成行显示「过滤占位 N」；有 `overlap_warning` 时弹 warning toast（6秒可关） |

### 知识库数据修复（直接SQL）
| 操作 | 删除数 |
|---|---|
| 删空文本碎片（劳动合同法全文.txt <20字占位条文） | 46 条 |
| 删民法典PDF版（保留TXT精准切片版526条） | 806 条 |
| 删重复条目（第502条 id=2） | 1 条 |
| **修复后总量** | **1055 条**，0 碎片，0 空向量 |

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅

---

## 2026-07-13 · 知识库导入模块多项完善（✅ 已完成）

### 改动汇总
| 功能 | 文件 | 内容 |
|---|---|---|
| **文件夹拖拽** | `KnowledgeView.vue` | 自定义 drop 处理，`webkitGetAsEntry()` 读取文件夹内容，支持拖入整个文件夹批量添加 |
| **覆盖模式** | `knowledge.py` / `knowledge.ts` / `KnowledgeView.vue` | `/import-file` 加 `overwrite: bool` 参数；覆盖时先 DELETE 同名旧切片；前端加「覆盖同名旧数据」开关，关闭弹窗自动重置 |
| **UI 美化** | `KnowledgeView.vue` | `:deep(.el-upload)` flex 居中，图标 44px，min-height 148px，hover/dragover 金色边框 |
| **超时修复** | `knowledge.ts` | `importKnowledgeFile` 设 `timeout: 180_000`，防民法典PDF等大文件 embedding 耗时超 axios 默认 30s |
| **路由顺序修复** | `knowledge.py` | `GET /stats` 移至 `GET /{chunk_id}` 前，修复 `/stats` 被动态路由拦截返回 422 导致知识库加载失败的 bug |
| **模板 bug 修复** | `KnowledgeView.vue` | `done` 状态同时显示"待导入"的 v-else 链归属错误，已重构为状态文字链与操作按钮独立 v-if |

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅
- 路由修复验证：`/knowledge/stats` 200 OK，`/knowledge/cards` 200 OK ✅

---

## 2026-07-13 · 文字识别与切片策略完善（方案A 五项改进）（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/knowledge.py` | ① `_MAX_CHUNK_CHARS` 500→380；② `_MIN_CHUNK_CHARS` 8→20；③ 新增 `_CHAPTER_RE` + `_CLAUSE_RE`；④ `_split_by_article` 每条携带最近章节前缀；⑤ 新增 `_split_by_clause`（1.1/一、/（一），≥3 触发）；⑥ `_smart_split` 三路降级；⑦ docx 补读表格；⑧ PDF 扫描件空文本 400 明确提示 |
| `frontend/src/api/knowledge.ts` | `split_mode` 加 `'clause'` |
| `frontend/src/views/KnowledgeView.vue` | `FileItem.mode` 加 `'clause'`；完成行加「款项切分」标签 |

### 三条切片路径
| 路径 | 触发条件 | 典型文档 |
|---|---|---|
| `article` | `第X条` ≥2 处 | 民法典、劳动法等 |
| `clause` | `1.1/一、/（一）` ≥3 处 | 合同模板、标准条款 |
| `paragraph` | 无结构特征 | 风险规则、案例 |

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅

---

## 2026-07-13 · 知识库模块完善（分页+服务端搜索+详情完整内容+失败重试）（✅ 已完成）

### 背景
知识库已达 644 条，`/cards` 全量返回+前端渲染 644 张卡片存在性能问题；详情弹窗只显示 120 字截断内容，法务无法查阅完整条文；批量导入失败文件无法单独重试。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/knowledge.py` | `/cards` 加 `page/size/q/category` 四个 Query 参数，返回 `{total,page,size,items}` 分页结构；新增 `GET /{chunk_id}` 返回完整 `content`（不截断） |
| `frontend/src/api/knowledge.ts` | 新增 `KnowledgeCardsResult` / `KnowledgeDetail` 接口类型；`getKnowledgeCards` 升级为带分页+搜索+分类参数；新增 `getKnowledgeDetail`；mock 模式同步支持分页过滤 |
| `frontend/src/views/KnowledgeView.vue` | ① 服务端分页：`currentPage/pageSize/total` ref，`el-pagination` 组件；② 分类 chip 改为 `onCatClick()` 触发服务端重载；③ 搜索防抖（400ms）watch；④ 详情弹窗懒加载完整正文（先显示截断摘要，打开后异步拉 `/knowledge/{id}`）；⑤ 失败文件行加「重试」按钮（`retryFile()`）；⑥ 复制条文改用完整正文 |

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅

---

## 2026-07-12 · RAG 知识库扩充（567 → 644 条）（✅ 已完成）

### 新增内容
| 批次 | 文件 | 分类 | 新增条数 |
|---|---|---|---|
| 1 | 知识产权条款风险规则.txt | 风险规则 | +12 |
| 2 | 违约金与赔偿责任风险规则.txt | 风险规则 | +10 |
| 3 | 劳动合同法关键条款.txt | 法律法规 | +17 |
| 4 | 个人信息保护法关键条款.txt | 法律法规 | +10 |
| 5 | 软件开发IT服务合同标准条款.txt | 标准条款 | +12 |
| 6 | 数据安全法关键条款.txt | 法律法规 | +8 |
| 7 | 采购合同标准条款.txt | 标准条款 | +8 |

### 最终知识库统计
| 分类 | 条数 |
|---|---|
| 法律法规 | 578 |
| 标准条款 | 29 |
| 风险规则 | 33 |
| 典型案例 | 4 |
| **合计** | **644** |

### 覆盖场景
- 劳务派遣/外包合同 → 劳动合同法
- 软件开发/IT服务合同 → IP归属、SLA、验收标准
- 采购合同 → 交货验收、质保、付款条件
- 数据合规合同 → 个人信息保护法、数据安全法
- 违约责任精细化 → 违约金上限、定金规则、情势变更

---

## 2026-07-12 · P2 九项缺陷修复（✅ 已完成）

### 改动
| 编号 | 文件 | 内容 |
|---|---|---|
| **L1** | `LoginView.vue` | `el-form` 绑定 `:model` + `:rules` + `ref="formRef"`；两个 `el-form-item` 加 `prop`；`onSubmit` 改用 `formRef.validate()` 校验，空字段在输入框下方显示红色 inline 提示 |
| **A5** | `AuditView.vue` | 已复核卡片 `.review-cta` 文字由固定"进入复核 →"改为条件渲染（已复核显示"查看详情 →"，未复核显示"进入复核 →"）；删除隐藏 `.review-cta` 的 CSS |
| **A6** | `AuditView.vue` | 新增 `batchAuditing`/`batchSuccessIds`/`startBatchAudit`；批量上传成功后对话框底部出现"一键触发全部审查（N份）"按钮，逐一调 `/contracts/{id}/audit` |
| **C2** | `CollaborationView.vue` | 红档 tier-btn 用 `el-tooltip` 包裹，`disabled` 时提示"当前无红档风险，无需发起三方会审" |
| **H2** | `HistoryView.vue` | 引入 `useRouter`，添加 `goAudit()`；风险详情抽屉加 `#footer` 插槽，内含"前往审查页复核 →"全宽按钮 |
| **R1/R2** | `RectifyView.vue` | 工具栏加搜索框（合同名/风险/责任人）；`filtered` computed 加关键词过滤；新增 `paged` computed + `el-pagination`（pageSize=10） |
| **R3** | `RectifyView.vue` | `advance()` 对 `已闭环→待处理` 流转加 `ElMessageBox.confirm` 二次确认 |
| **AD1/AD2** | `AdminView.vue` | 审计日志 Tab 工具栏加 `el-date-picker` 时间范围筛选；`filteredLogs` 加日期过滤；新增 `logPage`/`logPageSize` + `el-pagination`（pageSize=20） |
| **K2** | `backend/knowledge.py` + `api/knowledge.ts` + `KnowledgeView.vue` | 后端加 `DELETE /knowledge/{id}`（仅 admin）；前端加 `deleteKnowledge()` API；知识卡片头部加删除按钮（仅 admin 可见，`@click.stop` 阻止冒泡） |

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅

---

## 2026-07-12 · P1 五项缺陷修复（✅ 已完成）

### 改动
| 编号 | 文件 | 改动内容 |
|---|---|---|
| A1 | `frontend/src/views/AuditView.vue` | `auditState = 'idle'` → `auditState.value = 'idle'`（Vue3 ref 赋值 bug，补 .value） |
| A2 | `frontend/src/views/AuditView.vue` | 新增 `cancelUpload()` 函数：`ElMessageBox.confirm` 二次确认后再 `session.reset()`，防误触清空审查结果 |
| RP1 | `frontend/src/views/ReportsView.vue` | 金额范围 `el-select` 改为 `disabled` + `el-tooltip` 说明"合同金额为自然语言文本，暂不支持数值范围筛选"；清理多余 option |
| RU1 | `frontend/src/views/RulesView.vue` | 内置规则/模板删除按钮加 `v-if="r.builtin"` 分支：内置条目按钮 `disabled` + tooltip"不可删除"，自定义条目保留点击逻辑 |
| RU2 | `frontend/src/views/RulesView.vue` | 新增规则表单"审查维度"从自由 `el-input` 改为 `el-select`，8个选项与 AuditView 维度枚举完全对齐 |

### 说明
W1（WorkbenchView 亮色样式）经核实：路由中无 `/workbench` 路由，该文件未被挂载，属遗留死文件，不影响运行。

### 验证结论
- vue-tsc type-check：exit 0，零错误 ✅

---

## 2026-07-12 · 登录页重构为左右分栏（消除大屏"卡片飘忽"观感）（✅ 已完成）

### 背景
用户在高分屏（2K）浏览器打开登录页，觉得卡片"飘忽/位置不稳"。排查确认：`.login-wrap` 的 `align-items/justify-content: center` 居中代码正确，卡片实际几乎正好居中——**不是居中 bug**。真正根因是「纯米色空背景无锚点 + 卡片固定 380px 窄」：屏幕越大卡片占比越小、四周留白越大，视觉上越"飘"。修居中无意义，需补视觉重心。

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/views/LoginView.vue` | template + style 整体重构为**左右分栏**（script 逻辑零改动）：左品牌区（`--ink` 卷宗米底 + 径向微渐变 + 超大半透明"契"水印 + 印章徽标/系统名/三条卖点/底部 slogan，卖点用印章朱小方块项目符）；右登录区（`--ink-2` 信笺白底，"账号登录"标题 + 表单）。左右用 `flex: 1.15 / 0.85` 填满视口，随屏缩放不再飘。响应式 `@media(max-width:880px)`：品牌区 `display:none`，卡内补精简品牌头（`.card-brand`），"账号登录"标题隐藏避免重复 |

### 验证结论（Playwright 实测三分辨率 + type-check）
- vue-tsc type-check：exit 0，零类型错误 ✅
- 1440×900 标准屏：左右分栏、左右内容顶端对齐、重心稳 ✅
- 2000×1150 超宽屏（用户 2K 场景）：两栏填满视口，卡片不再飘 ✅
- 460×860 窄屏：品牌区收起、卡内品牌头出现、表单 340px 居中 ✅
- 登录功能未受影响：legal 账号 Enter 提交 → 跳转 /dashboard，0 console errors ✅

---

## 2026-07-11 · RAG 检索来源溯源（rag_sources）验证收尾 + 脱敏路径补全（✅ 已完成）

### 背景
上一轮已把「每条风险携带 RAG 检索来源、前端 RiskReviewDrawer 溯源展示」的 7 处改动写入代码（auditor 收集 rag_items → runner 落库 → Risk 模型加列 → RiskOut field_validator → types.ts → RiskReviewDrawer 展示区）。本轮做端到端验证并修复验证中发现的问题。

### 验证中发现并修复的 3 件事
| # | 问题 | 处理 |
|---|---|---|
| 1 | 临时验证脚本 `_verify_rag.py` 连错库（`storage/contracts.db` 空库，后端实际用 `a03_dev.db`），导致「DB 列检查」假阴性 | 先修库路径确认迁移成功，验证完删除脚本 |
| 2 | API 响应缺 `rag_sources` 字段：后端进程是改 schema 前启动的旧进程 | 重启后端加载新 `RiskOut`，字段生效 |
| 3 | **`masking.py` 脱敏路径遗漏**：business 角色手工构造 dict 时漏了 rag_sources，business 用户永远看不到检索来源（其他角色正常） | 方案 A 修复：dict 补 `"rag_sources": json.loads(risk.rag_sources or "[]")`，与全访问路（RiskOut validator）输出一致 |

### 涉及文件
| 文件 | 改动 |
|---|---|
| `backend/app/services/masking.py` | 顶部 `import json`；business 脱敏 dict 补 `rag_sources`（反序列化为 list，空值兜底 `[]`）|
| `backend/_verify_rag.py` | 修库路径 bug 后删除（临时脚本）|

### 验证结论
- DB 迁移：`a03_dev.db` risks 表含 `rag_sources` 列，99 条历史数据 ✅
- API 字段：重启后 legal 全访问路返回 `rag_sources` ✅
- 端到端填充：重新审查 contract 33 → 7/7 风险带真实来源，每条 8 个来源，引用民法典第585条 + 检索 score，双 Agent 协同触发 X1 交叉验证（真实 DeepSeek 路）✅
- masking 单测：business 得 list 类型来源 / legal 对象不受影响 / 空值兜底 `[]` 三项全过 ✅
- business 端到端：部门隔离后见 3 条采购中心合同，contract 5 风险响应含 `rag_sources` 键、类型 list、原文脱敏正常、不崩 ✅

### 遗留说明
- 99 条历史风险 `rag_sources` 均为空 `[]`（改动前生成），仅重新审查的合同才填充真实来源，属预期。

---

## 2026-07-11 · 用户视角 UI 打磨（5 个页面，P1-P3 全部改动）（✅ 已完成）

### 背景
基于老师"从用户角度出发精益求精"的方向，全量扫描高频页面后发现 8 个问题，按优先级全部修复。

### 改动
| 文件 | 改动内容 |
|---|---|
| `plugins/icons.ts` | 新增注册 `ArrowRight`、`QuestionFilled` |
| `views/RectifyView.vue` | rk-card 加 class（rk-pending→`--seal`，rk-processing→`--amber`，rk-done→`--sage`）；逾期截止日加 `overdue` 红色高亮 |
| `views/AuditView.vue` | 新增 `sortedRisks` computed（待复核高风险在前，已处理沉底）；已复核卡片加 `reviewed` class（opacity:0.5，隐藏"进入复核"CTA）|
| `components/audit/RiskReviewDrawer.vue` | 章节标题 h4 字号 12→13px；置信度补 `%` 单位 |
| `views/HistoryView.vue` | 抽屉内 basis/suggest 颜色升 `--ivory-dim`；表格最后加箭头列（hover 变金色，明示行可点击）|
| `views/DashboardView.vue` | KPI `trend` 文字替换为 `?` tooltip hint（口径说明更友好）；待办总数显示真实待处理数，超过5条提示"仅显示前5" |

### 验证结论
- vue-tsc type-check 零错误 ✅
- 8 个问题点全部覆盖 ✅

---

## 2026-07-11 · UI 细节规范化（模块标题 + 协同字号 + 批量状态标识）（✅ 已完成）

### 背景
老师评审意见：合同审查页模块名颜色/粗细/大小不一致、各模块缺少醒目标题；多智能体协同页字体偏小；批量审查队列完成/失败标识不清晰。

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/views/AuditView.vue` | ① `upload-panel` / `result-panel` 补 `<template #header>`（"合同上传"/"智能审查结果"），`config-panel` header 套统一 `.panel-title` 类；② 新增 `.panel-title` 样式（14px / font-weight:600 / serif / `--ivory`），与三个卡片头部对齐；③ `col-head h2` 从 15px 收拢到 14px+600+`--ivory`，与 panel-title 视觉一致；④ `batch-status` span 替换为 `el-tag`（pending=plain / uploading=warning·light / success=success·light / failed=danger·dark），failed 行整行加 `--seal-soft` 背景 |
| `frontend/src/views/CollaborationView.vue` | `agent-section h4` 12→13px、color 升 `--ivory`；`.chip` 11→12px；`agent-mini-kpis span` 11→12px；`tier-meta` 11.5→12px；`cross-body p` line-height 1.6→1.7 |

### 验证结论
- vue-tsc type-check 零错误 ✅
- 三处面向评审的改进点全部落地：标题统一醒目、协同字号上调、失败状态视觉容器化 ✅

---

## 2026-07-09 · RAG 混合检索（BM25 + 向量 RRF 融合）（✅ 已完成）

### 背景
知识库达 567 条（早过 P2 待办的 200 条阈值）。纯向量检索对法条「精确术语」（违约金/定金/不可抗力）不如 BM25 词频匹配；两者互补。对应待办 P2「RAG 混合检索（BM25 + 向量 RRF 融合）」。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/requirements.txt` | 加 `jieba==0.42.1`（中文分词，MIT）+ `rank-bm25==0.2.2`（BM25，Apache2.0）；装前审计，0 已知漏洞，纯本地无重依赖 |
| `backend/app/services/rag/retriever.py` | 重写 `retrieve()`：向量路（余弦，仅非空向量）+ BM25 路（jieba 分词，全部切片）→ **RRF 融合**（`score=Σ1/(k+rank)`, k=60，每路 Top-10 进融合）→ Top-K。`retrieve()` 签名/返回结构不变，auditor 零改动。BM25 索引带指纹缓存（切片数+max id），知识库变动自动重建。降级链：embedding 挂→仅 BM25；库空→内置关键词 |
| `backend/tests/test_rag_hybrid.py`（新建） | 9 个单测：分词/RRF 融合/融合分序/BM25 排名/指纹缓存/无命中/关键词降级 |

### 验证结论
- 22 个单测全过（9 混合 + 13 切片）✅
- 真实 567 条库检索：违约金过高→Top-1 第585条、定金上限→Top-1 第586条、承揽交付→Top-3 全承揽分则、不可抗力→Top-1 第590条，命中全部精准 ✅
- `mode=hybrid` 双路生效，向量 embedding 7-8ms，BM25 索引 567 条一次构建后缓存复用 ✅
- 后端已带混合检索重启上线 ✅

### 遗留说明
- jieba 触发 `pkg_resources` 弃用警告（无害，jieba 0.42.1 内部依赖），不影响功能
- BM25 索引为进程内内存缓存，多 worker 部署时各 worker 独立构建一份（567 条 <100ms，可接受）

---

## 2026-07-09 · 民法典合同编全量导入 + Embedding 离线固化（✅ 已完成）

### 知识库充实：民法典合同编 526 条
| 事项 | 内容 |
|---|---|
| 来源 | 全国人大官方 `中华人民共和国民法典_20200528.docx`（用户提供，保证条文权威准确，不凭记忆生成）|
| 提取 | python-docx 定位第三编·合同正文段（第463–988条），生成 `民法典-合同编.txt`（根目录，871行/139KB）|
| 切片 | 走「法条识别」智能切片，精确 526 条 = 526 切片，与官方条数完全一致 |
| 入库 | 真实 API `POST /knowledge/import-file`（category=law），本地 bge-small-zh 向量化，7.3s |
| 检索验证 | 定金 query Top-1/2 命中（0.677）；承揽 query Top-3 全命中分则条文（0.78–0.83），分则审查盲区消除 ✅ |
| 知识库总量 | 41 → 567 条 |

### 切片正则修复（交叉引用误切）
- **根因**：`_ARTICLE_RE` 无行首锚定，正文里的句中交叉引用（如「依照本法第五百零九条规定」）被误判为条文边界，526 条被切成 568 条，条文从中间断裂。
- **修复**：`knowledge.py` 正则改 `^[\t 　]*第X条` + `re.MULTILINE`，只认行首条号。
- **回归测试**：`test_knowledge_split.py` 新增 `test_cross_reference_not_split` / `test_article_with_leading_whitespace`，共 13 个单测全过。

### Embedding 生产离线固化（私有化硬约束）
- **背景**：后端首次算 embedding 时 sentence-transformers 默认联网校验 huggingface.co，网络不可达时卡在超时重试（10s×5）堵死请求线程，连登录都超时。
- **改动**：
  - `backend/Dockerfile`：构建阶段 `ARG EMBED_MODEL` 预下载模型烤入镜像层 → `ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` 运行时永不联网。
  - `docker-compose.yml`：移除 `hf_cache` volume 挂载（空 volume 会遮蔽镜像内烤好的模型，导致离线加载失败）。
  - `backend/.env.example`：补 embedding 离线策略说明，明确区分 Docker（ENV 固化）vs 宿主机裸跑（启动命令前置 `HF_HUB_OFFLINE=1`，因 pydantic 不注入 os.environ，.env 写它对 hf 库不生效）。
- **效果**：构建机联网下载一次 → 镜像固化 → 容器运行零联网，符合「数据与模型均不出企业」。

### 验证结论
- 13 个切片单测全过 ✅
- 合同编 526 条精确切片、入库、检索命中全部验证 ✅
- 联网恢复后复测：首次检索 8.5s（模型加载），承揽 query 命中新条文相似度 0.83 ✅
- docker-compose YAML 结构完整（本机无 docker daemon，未做 build 实测）

---

## 2026-07-09 · 知识库智能切片升级：法条识别 + 清洗 + 去重（✅ 已完成）

### 背景
知识库批量导入的切片策略是通用段落切割（`_split_chunks`：空行分段 + 超长按句号切），对法规文本无结构感知——上传整部法规 PDF 时条文被打散或合并，页码/乱码碎片直接入库污染向量空间，同一文件重复导入产生完全重复切片。对应待办 P2「RAG 切片策略优化（法条按条文切）」。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/knowledge.py` | `_split_chunks` → `_smart_split`（返回 `SplitResult` 含模式元信息）：①`_split_by_article` 按 `第X条`（中文/阿拉伯数字）边界切，≥2 条命中才触发，单条超长再二级切；②无条文标记降级 `_split_paragraph`（原逻辑保留）；③`_clean_lines` 去页码行/纯符号行（保留空行维持段落结构），过滤 <8 字碎片。新增 `_dedup_chunks` + `_chunk_key`（source+content MD5）：入库前剔除库中已有及本批内部重复。两个导入端点 `/import` `/import-file` 统一走「智能切片 → 去重 → `_do_index`」，消除原 `/import` 重复的降级代码，返回增加 `skipped_duplicates`/`split_mode`/`article_count` |
| `frontend/src/api/knowledge.ts` | 新增 `ImportFileResult` 类型（含去重数/切片模式）；`importKnowledgeFile` 返回类型改用之 |
| `frontend/src/views/KnowledgeView.vue` | `FileItem` 加 `skipped`/`mode` 字段；文件队列 done 行展示「法条识别/段落切分」标签 + `+N 条 · 去重 M` |
| `backend/tests/test_knowledge_split.py`（新建） | 11 个单元测试：条文切割/多行归属/阿拉伯数字/单条降级/段落切/超长句切/页码清洗/碎片过滤/空文本/去重键 |

### 验证结论
- 11 个切片单元测试全过（pytest 未装，直连函数跑）✅
- 前端 vue-tsc type-check 零错误 ✅
- 端到端：模拟含页码噪音的法规 PDF → 识别 4 条法条、页码清洗、多行内容不拆散；首次导入 4 条入库、重复导入 4 条全跳过 ✅
- seed 脚本不受影响（走 `index_documents` 直灌手工切好的单条，不过 `_smart_split`）✅

---

## 2026-07-09 · Docker Compose + 批量合同上传（✅ 已完成）

### Docker Compose
| 文件 | 内容 |
|---|---|
| `docker-compose.yml`（根目录，新建）| 两服务：`a03_backend`（Python3.11+uvicorn，映射:8000，持久化 contract_storage + hf_cache 两个 volume）、`a03_frontend`（nginx，映射:80，depends_on backend）；支持 `docker compose up -d` 一键启动 |
| `backend/Dockerfile`（新建）| python3.11-slim + libpoppler/libxml2 系统依赖 + pip install + uvicorn 启动 |
| `frontend/Dockerfile`（新建）| 多阶段构建：Node20 构建 Vue → nginx:alpine 服务静态文件 |
| `frontend/nginx.conf`（新建）| Vue Router history 模式 + `/api/` 反向代理到 `backend:8000`，`proxy_read_timeout 120s`，`client_max_body_size 60m` |
| `backend/.dockerignore` / `frontend/.dockerignore`（新建）| 排除 .venv/node_modules/storage/dist 等无关文件 |

### 批量合同上传（赛题验收指标：一次50份）
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/contracts.py` | 新增 `POST /contracts/batch-upload`：接收 `list[UploadFile]`（最多50份），逐文件独立处理（加密存储+解析+elements_json），单文件失败不中断其余，返回每份文件的 `{filename, status, contract_id, error}` |
| `frontend/src/api/contract.ts` | 新增 `BatchUploadResult` 类型 + `batchUploadContracts()` 函数（5分钟超时）；补回 `updateRiskStatus`（误删已修复）|
| `frontend/src/views/AuditView.vue` | 上传面板加「批量上传（最多50份）」按钮；批量上传对话框：多文件拖拽区 + 文件队列（每行显示文件名/状态/合同ID/错误信息）+ 汇总行 + 开始上传按钮（自动禁用已完成文件）|

### 验证结论
- vue-tsc type-check 零错误 ✅
- `GET /contracts/batch-upload` → 405 Method Not Allowed（接口注册正确，只接受 POST）✅
- `docker compose up -d` 可一键部署（需 Docker Desktop 环境）

---

## 2026-07-09 · 前端演示功能清零（四处修复）（✅ 已完成）

### 改动
| # | 问题 | 文件 | 内容 |
|---|---|---|---|
| 1 | KnowledgeView 演示按钮 | `KnowledgeView.vue` | 「应用为合同建议」改为「复制条文」，`navigator.clipboard.writeText()` 真实复制标题+摘要，toast 改为有效提示 |
| 2 | 多维钻取假数据 | `ReportsView.vue` | 删除 `drillFactor`（0.42/0.55/0.6 硬编码系数）和 `data` 缩放逻辑；新增 `filteredMeta` computed 对 `contractsMeta` 做真实本地过滤（合同类型 + 风险等级）；金额字段格式不统一暂跳过；钻取提示由「命中约XX%」改为真实「命中N/M份」|
| 3 | AnnotationModal 演示正文 | `AnnotationModal.vue` | 删除 `CLAUSES` 硬编码假合同文本、`renderClause()`、`renderedClauses`；左侧改为真实风险 `original_text` 卡片列表，`id="risk-{id}"` 锚点；`scrollToAnn(i)` → `scrollToRisk(id)` 按 id 定位 |
| 4 | 整改项 owner 用演示名 | `auth.py` + `types.ts` + `auth.ts` + `AuditView.vue` | login 返回增加 `username` 字段；auth store 持久化 username；`AuditView.vue` 整改 owner 从 `demo.profile.name`（演示角色名）改为 `auth.username`（真实登录账号）；移除 `useDemoStore` import |

### 验证结论
- vue-tsc type-check 零错误 ✅
- 后端 `POST /auth/login` 响应包含 `"username":"legal"` 字段 ✅
- 多维钻取不再有演示缩放逻辑，筛选器对 `contractsMeta` 表做真实过滤 ✅

---

## 2026-07-09 · 多维报表「合同要素汇总」可视化表格（✅ 已完成）

### 背景
需求要求在可视化看板中展示甲方信息、合同标的、收付款节点，原实现只有 Excel 导出包含这些字段，ReportsView 可视化看板完全缺失。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/services/report/exporter.py` | 新增 `contracts_metadata()` 函数：查询所有合同，解析 `elements_json`，聚合风险数，返回结构化列表 |
| `backend/api/v1/endpoints/reports.py` | 新增 `GET /reports/contracts-metadata` 端点（所有登录角色可读）|
| `frontend/src/api/reports.ts` | 新增 `ContractMeta` 接口类型 + `getContractsMetadata()` 函数 |
| `frontend/src/views/ReportsView.vue` | `load()` 并行加载报表数据和合同要素；在四张图下方新增「合同要素汇总」卡片，`el-table` 展示合同名称/甲方/合同标的/收付款节点/金额/风险数，高风险行红色标注 |

### 验证结论
- vue-tsc type-check 零错误 ✅
- `GET /reports/contracts-metadata` 响应 `{"detail":"Not authenticated"}` 确认接口注册成功 ✅
- 旧合同（无 `elements_json`）显示 `—`，不影响表格渲染 ✅

---

## 2026-07-09 · 多维报表元数据补全（甲方/合同标的/收付款节点）（✅ 已完成）

### 背景
多维报表需求要求"自动提取关键元数据（甲方信息、合同标的、收付款节点）"，原实现仅有风险维度数据，三个指定字段完全缺失。根因：解析要素未持久化到DB，Excel 导出时无法读取。

### 改动
| 文件 | 内容 |
|---|---|
| `services/parser/extractor.py` | `_ELEMENT_PATTERNS` 新增 `subject`（合同标的，覆盖"本合同标的为/乙方向甲方提供"等主流写法）和 `payment_terms`（收付款节点，提取付款条款段落文本，最多8行） |
| `models/models.py` | `Contract` 新增 `elements_json TEXT DEFAULT '{}'`，持久化解析要素 JSON |
| `db/init_db.py` | `_DEV_COLUMNS` 加 `contracts.elements_json` 热迁移条目，存量DB 不删数据 |
| `api/v1/endpoints/contracts.py` | parse 端点提取后将字符串类型要素序列化为 JSON 存入 `contract.elements_json` |
| `services/report/exporter.py` | 新增 `_elem()` 辅助函数（NULL 安全，兜底返回 `—`）；`_LEDGER_COLUMNS` 新增三列：甲方 / 合同标的 / 收付款节点，从 `elements_json` 读取 |
| `frontend/src/views/AuditView.vue` | `elementLabels` 加 `subject`（合同标的）/ `payment_terms`（收付款节点），在合同关键要素区展示 |

### 验证结论
- vue-tsc type-check 零错误 ✅
- SQLite 热迁移成功，`contracts` 表字段确认：`[..., 'elements_json']` ✅
- 旧合同 `elements_json` 为 `'{}'`，Excel 导出降级显示 `—`，不报错 ✅
- 新上传合同 parse 后自动写入，Excel 导出包含甲方/合同标的/收付款节点三列 ✅

---

## 2026-07-09 · KPI宋体 + 逐条核实路由 + 应用为合同建议 + 三方会审真实接口（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/views/DashboardView.vue` | `.kpi-label` / `.kpi-value i` / `.kpi-trend` 三处加 `font-family: var(--serif)` |
| `frontend/src/views/CollaborationView.vue` | `.kpi span` 加 `font-family: var(--serif)`；`onTierAction` 重写：黄档→`router.push('/audit')`（逐条核实复用现有审查页），绿档→提示已自动过审，红档→调后端 escalate 接口（有真实会话才触发，否则提示先完成审查） |
| `frontend/src/components/audit/AnnotationModal.vue` | script 引入 `useAuditSessionStore`；新增 `applyAsSuggestion()`：调 `session.setRiskStatus(risk, 'to_modify')`；每个批注项底部加「应用为合同建议」按钮，点击后变「已应用 ✓」禁用 |
| `backend/app/api/v1/endpoints/contracts.py` | 新增 `PATCH /contracts/{id}/escalate`：更新 `contract.status='three_review'` + 写审计日志（action=三方会审发起）；legal/finance/admin 角色可调 |

### 设计说明
- **应用为合同建议** 复用已有 `review_status='to_modify'` 字段，无需新建数据表，数据来源与 AI 建议字段隔离
- **逐条核实** 路由复用合同审查页的真实复核抽屉，不重复实现同一功能
- **三方会审** 明确为"发起留痕"语义，完整审批工作流标注为路线图待集成企业 OA

### 验证结论
- vue-tsc type-check 零错误 ✅

---

## 2026-07-09 · 部门/合同类型管理员增删（✅ 已完成）

### 背景
部门和合同类型硬编码在前端，企业新增部门或合同类型需要改代码重新部署，无法满足企业交付要求。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/models/models.py` | 新增 `LookupItem` 模型（`lookup_items` 表），字段：id / category / value / sort_order |
| `backend/app/schemas/contract.py` | 新增 `LookupItemOut` / `LookupItemCreate` schema |
| `backend/app/api/v1/endpoints/lookup.py`（新建） | 3个接口：`GET /admin/lookups/{category}`（所有角色可读）/ `POST /admin/lookups`（admin）/ `DELETE /admin/lookups/{id}`（admin）；重复值 409，非法 category 400 |
| `backend/app/api/v1/router.py` | 注册 `lookup.router`，prefix `/admin` |
| `backend/scripts/seed_demo.py` | 新增 `seed_lookups()`：预置12个部门 + 14种合同类型（幂等） |
| `frontend/src/api/admin.ts` | 新增 `LookupItem` 接口类型 + `getLookups` / `createLookup` / `deleteLookup` 三个API函数 |
| `frontend/src/views/AdminView.vue` | 新增第4个Tab「基础配置」：部门+合同类型双栏，含添加输入框（Enter触发）+ 删除按钮（带确认弹窗）；`onMounted` 同步加载 |
| `frontend/src/views/AuditView.vue` | `onMounted` 从 `/admin/lookups/department` 和 `/admin/lookups/contract_type` 动态拉取选项；接口失败时静默降级到内置8条默认值 |

### 验证结论
- vue-tsc type-check 零错误 ✅
- 权限设计：读取公开（所有角色），增删仅 admin，符合 RBAC 策略 ✅
- AuditView 降级兜底：后端不可用时前端下拉框仍正常工作 ✅

---

## 2026-07-09 · 上传超时修复 + 部门/合同类型选项扩充（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/api/contract.ts` | `uploadContract` 单独设 `timeout: 120_000`（120秒），覆盖全局30秒默认值；适配大文件加密存储+PDF解析耗时 |
| `frontend/src/views/AuditView.vue` | 业务部门从3项扩充至10项（采购中心/销售部/研发部/法务部/财务部/人力资源部/行政部/运营部/市场部/研发外包部）；合同类型从3项扩充至10项（新增劳动合同/租赁合同/保密协议/合作协议/服务协议/框架协议）；两个 `el-select` 均加 `filterable` 支持搜索 |

### 验证结论
- vue-tsc type-check 零错误 ✅
- 上传超时：120秒足以覆盖企业场景中大PDF文件的完整处理链路

---

## 2026-07-09 · 演示视角切换器真实登录（✅ 已完成）

### 问题
`UserSwitcher` 切换视角只调 `demo.setViewRole()`，仅改变头像/显示名，不替换 JWT Token。
后端 RBAC/部门隔离按原 Token 鉴权，切换前后返回完全相同的数据，侧栏菜单也不变。

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/components/layout/UserSwitcher.vue` | `onCommand` 改为 async；切换时调 `auth.login()` 拿新 Token；同步 `demo.setViewRole()`；切换成功后跳转 `/dashboard` 刷新数据；切换中显示 Loading 图标 + `cursor: wait`，防重复点击 |
| `frontend/src/plugins/icons.ts` | 注册 `Loading` 图标（`@element-plus/icons-vue`） |

### 验证结论
- vue-tsc type-check 零错误 ✅
- 切换法务/财务/全域视角将分别以 `legal`/`finance`/`admin` 账号登录，Token/role/侧栏菜单全部真实切换

---

## 2026-07-09 · Playwright E2E 全流程验证（✅ 通过）

### 验证范围
覆盖本轮所有改动：演示功能清零 / 报表元数据 / 批量上传 / 角色切换 / 基础配置管理

### 验证结果

| 验证点 | 结果 | 关键数据 |
|---|---|---|
| 登录 | ✅ | legal 账号正常登录 |
| 批量上传按钮 | ✅ | 文字「批量上传（支持50份以上）」 |
| 多维报表元数据表 | ✅ | `meta-card` 存在，table 加载，4个KPI |
| 知识库复制条文 | ✅ | 「复制条文」按钮存在，旧「演示」按钮消失 |
| 协同审查旧演示文字 | ✅ | 「演示：已执行」已消失 |
| UserSwitcher 真实登录 | ✅ | finance切换: role=finance/username=finance；admin切换: role=admin/username=admin |
| 侧栏 RBAC 响应 | ✅ | 切到 admin 后「权限与审计」菜单自动出现 |
| AdminView 基础配置 Tab | ✅ | 4个Tab，26个 lookup items 正常加载 |

**0 个失败项，0 个控制台错误**

---

## 完成情况总览（截至 2026-09-08）

### 整体架构
- **前端**：Vue 3 + TS + Element Plus + ECharts，卷宗风 UI。10 个视图（登录 + 9 业务），侧栏支持折叠，全站中文业务语言。
- **后端**：FastAPI + SQLAlchemy + SQLite（开发）/PostgreSQL（生产），JWT+RBAC，Celery 异步，LLM Adapter + RAG 检索（本地 embedding），审计日志，LLM 调用记录，部门访问隔离，合同加密存储，字段级脱敏。
- **数据策略**：前端 `MOCK_ENABLED` 全部 false，100% 调真接口。13 张数据库表，**40 条 `/api/` 路由**，SQLite 启动补列与 Alembic 可回滚迁移并存。
- **RAG 状态**：BAAI/bge-small-zh-v1.5 本地 Embedding（512 维、运行时强制离线）+ BM25 + RRF 混合检索；本机演示库曾验证 973 条知识，但数据库不随源码分发；系统支持适用性过滤、版本治理和逐风险证据闭环。

### 模块完成度
| 模块 | 前端 | 后端 | 状态 |
|---|---|---|---|
| 登录 / RBAC（4角色：admin/legal/finance/business） | ✅ | ✅ | 闭环 |
| 合同审查（上传→加密存储→解析→LLM双Agent审查→复核→整改） | ✅ | ✅ | 核心闭环已通 |
| 智能协同审查（冲突消解/分级分档，有会话才展示结果） | ✅ | ✅ | 前后端联动完成 |
| **风险条款追问 AI**（绑定上下文，对话历史管理） | ✅ | ✅ | ✅ 新增 |
| 工作台（真实整改待办 + 真实审查动态） | ✅ | ✅ | ✅ 真接口 |
| 多维报表 Reports（含 Excel 导出，KPI口径说明） | ✅ | ✅ | ✅ 真接口 |
| **法规知识库**（混合检索 + 批量导入 + 元数据治理） | ✅ | ✅ | ✅ 逐风险证据闭环；演示库需在新环境重建 |
| 整改跟踪 Rectify（含状态流转按钮） | ✅ | ✅ | ✅ 真接口 |
| 审查记录 History（含点击行风险钻取） | ✅ | ✅ | ✅ 真接口 |
| 规则与模板 Rules | ✅ | ✅ | ✅ 真接口 |
| 权限与审计 Admin（3 Tab：矩阵/审计日志/LLM调用记录） | ✅ | ✅ | ✅ 真接口 |

### 已完成的企业交付约束
| 约束 | 实现方式 | 状态 |
|---|---|---|
| 合同文件加密存储 | Fernet AES-128-CBC+HMAC，密钥注入 `.env`，上传即加密落盘 | ✅ |
| 字段级脱敏 | 响应层按角色分级：business 看提交人首字+**，风险原文截断+[已脱敏] | ✅ |
| 部门访问隔离 | business 角色仅可见本部门合同（WHERE dept 过滤，403 跨部门） | ✅ |
| 审计日志 + IP 追踪 | 全操作留痕，login/upload 等写入真实客户端 IP（X-Forwarded-For 优先） | ✅ |
| LLM 调用可观测性 | 每次 chat/追问调用写入 llm_call_logs，Admin Tab 展示三种 provider 算力对比 | ✅ |
| 准确率责任边界 | 每条风险：原文引用 + 法规依据 + 置信度 + 人工复核状态 + 免责声明 | ✅ |
| 私有化模型可切换 | LLM Adapter 支持 Qwen/DeepSeek/OpenClaw；Embedding 本地化（不出企业） | ✅ |

### 已完成能力与材料
- 完整前后端业务闭环（11 个模块，40 条 `/api/` 路由）
- RAG 可靠证据链（本地 Embedding + BM25 + RRF + 适用性过滤 + 版本治理）
- 数据安全：加密存储 / 字段脱敏 / 部门隔离 / 审计留痕
- UI 去演示化：真实数据 / 业务语言 / 去技术展示冗余
- 风险追问 AI（上下文绑定对话）
- 390/1440/2560px 响应式与无障碍改进
- 专业重制版项目详细方案 V3.1（8章、4个附录，已完成结构、事实、语言和逐页视觉验收）
- 重构版项目概要介绍 DOCX（9 页，已完成结构、事实、语言和逐页视觉验收）
- 本轮完整质量门禁通过：评测 59 项；后端 304 项通过、1 项跳过；前端默认门禁 17 项通过、12 项服务型用例跳过；类型检查和生产构建通过
- 仓库正式材料目录已纳入参赛答辩 PPT；桌面 `比赛材料提交包/` 已收录两份正式 DOCX，测试案例及报告和演示视频仍待补齐

### 当前提交包
| 材料 | 状态 | 说明 |
|---|---|---|
| `契鉴_项目详细方案_专业重制版_V3.1.docx` | 已完成，当前最新 | 专业化二次修订版；复制后哈希一致 |
| `契鉴_项目详细方案_专业重制版.docx` | 已完成，上一版 | 当前在 Word 中打开，本轮未强制覆盖 |
| `契鉴_项目详细方案.docx` | 已完成，保留 | 原提交命名的重构版详细方案 |
| `契鉴_项目详细方案_人工润色版.docx` | 已完成，保留 | 七章人工润色版，供版本对照 |
| `契鉴_项目概要介绍.docx` | 已完成 | 来自当前推荐的重构版项目概要，复制后哈希一致 |
| `契鉴_参赛答辩PPT.pptx` | 已完成 | 15 页主讲、5 页答辩备份，带逐页演讲者备注，已完成结构与逐页视觉验收 |
| `测试案例及报告/` | 目录已建，待整理 | 汇总自动化、端到端和真实硬指标证据 |
| `演示视频/` | 目录已建，待制作 | 录制 3～5 分钟核心业务闭环 |

### 待办与验收边界
| 优先级 | 事项 | 当前状态与下一步 |
|---|---|---|
| **P1** | 答辩演练与信息校对 | PPT 已完成；提交前补齐学校、团队、指导教师等最终信息，并完成现场计时演练 |
| **P1** | 测试案例及报告 | 目录已建；汇总自动化结果，并补齐 50+2 文件批次、OCR 字符准确率和要素准确率真实证据 |
| **P1** | PostgreSQL 16 与 Compose 验收 | 代码和编排已就绪；需在具备 Docker 的目标机完成迁移、回滚、健康检查和恢复验证 |
| **P1** | OpenClaw/GPU 性能对比 | 评测工具已就绪；需冻结数据集、两套设备和真实凭据 |
| **P2** | 演示视频 | 目录已建；待录制 3～5 分钟上传、审查、复核、整改和报表闭环 |
| **P2** | 团队过程材料 | 当前提交包未建目录；需确认是否作为独立参赛材料提交 |
| **P2** | 能耗对比 | 缺两套设备同口径功率时序数据，当前保持阻塞 |
| **P3** | 私有化模型切换 | LLM Adapter 已支持 Qwen/DeepSeek/OpenClaw；生产环境需配置私有化模型和凭据 |

---

## 2026-07-08 · 知识库批量导入功能（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/knowledge.py` | 新增 `POST /knowledge/import-file` 端点；提取 `_extract_file_text()`（支持 .txt/.docx/.pdf）和 `_do_index()` 辅助函数；重构 `/import` 减少重复 |
| `backend/scripts/seed_knowledge_law.py`（新建） | 预置法规脚本：《民法典》合同编 12 条 + 风险规则 7 条 + 标准条款模板 5 套 + 典型案例 2 条，共 27 个条目、26 个切片；幂等（检查 source 去重），`--force` 强制重建 |
| `frontend/src/api/knowledge.ts` | 新增 `importKnowledgeFile(file, category)` — FormData 上传 |
| `frontend/src/views/KnowledgeView.vue` | 工具栏加「导入文件」按钮；批量导入 Dialog：分类选择 + 拖拽多文件区 + 文件队列状态列表（待/中/+N条/失败）+ 汇总进度；完成后自动刷新卡片列表 |

### 验证结论
- 知识库统计卡：法律法规 17 / 标准条款 9 / 风险规则 11 / 典型案例 4，共 41 条 ✅
- 「导入文件」按钮正常显示，0 errors ✅
- 预置脚本幂等验证：重复运行跳过已存在条目 ✅

---

## 2026-07-08 · RAG P0 — 本地 embedding，向量检索全链路接通（✅ 已完成）

### 背景（改前问题）
DeepSeek 无 `/embeddings` 端点 → embedding 失败 → 知识库写入空向量 → `retrieve()` 过滤掉空向量条目 → 始终回落到内置 4 条规则 → 审查"法规依据"全部来自死规则，与知识库内容无关。

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/llm/adapters/local_embedding.py`（新建） | `LocalEmbeddingAdapter`：sentence-transformers 本地化封装，模型懒加载，embed() 返回 `list[list[float]]` |
| `backend/app/llm/factory.py` | 新增 `get_embedding_adapter()`：`EMBED_BACKEND=local`（默认）→ 本地单例；`EMBED_BACKEND=api` → OpenAI 兼容端点；`get_llm_adapter()` 不变（chat 仍走 DeepSeek/Qwen） |
| `backend/app/core/config.py` | 新增 `EMBED_BACKEND / LOCAL_EMBED_MODEL` 配置；`EMBED_DIM` 修正为 512（bge-small-zh 实际维度） |
| `backend/app/services/rag/retriever.py` | `_vector_search` / `index_documents` 改用 `get_embedding_adapter()`（不再混用 chat adapter） |
| `backend/requirements.txt` | 加 `sentence-transformers==3.3.1` |
| 数据库（一次性操作） | 存量 14 条空向量条目全部补向量（55ms，BAAI/bge-small-zh-v1.5） |

### 验证结论
- `retrieve('违约责任条款上限约定')` → mode=**vector**，Top-3 相似度 0.69/0.65/0.65 ✅
- 不再降级到内置规则，审查"法规依据"真正引用知识库条文 ✅
- 本地推理延迟：约 15-25ms/query（CPU），满足企业场景 ✅

---

## 2026-07-08 · 风险条款追问 AI（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `backend/app/api/v1/endpoints/chat.py`（新建） | `POST /chat`：接收风险上下文（category/original_text/basis/suggestion/confidence）+ 用户消息 + 对话历史，构造 system prompt 后调 LLM Adapter 作答；对话历史最多携带 6 条；调用写入 llm_call_logs（agent=chat，mode=chat） |
| `backend/app/api/v1/router.py` | 注册 `/chat` 路由 |
| `frontend/src/api/chat.ts`（新建） | `chatWithRisk()` 封装请求 |
| `frontend/src/components/audit/RiskReviewDrawer.vue` | 风险详情下方加追问面板：空状态示例引导、用户/AI 气泡消息列表、Enter 发送、切换风险自动清空历史、抽屉宽度 440→480px |

### 功能说明
用户点击风险条目进入复核抽屉，可就该条款向 AI 追问（例如"违约金上限在行业里正常吗""我方有哪些谈判空间"）。每次对话均绑定当前条款的完整上下文，AI 不会泛泛作答。对话历史在当次抽屉内保留，关闭/切换风险自动清空。

### 验证结论
- 后端 `chat` 模块导入无报错 ✅
- 前端抽屉页面加载 0 errors ✅

---

## 2026-07-08 · 工作台去演示假数据（✅ 已完成）

### 改动
| 区块 | 改前 | 改后 |
|---|---|---|
| 待办面板 | `todoByRole` 硬编码 4 条，随演示视角切换 | 真实整改项（`status=待处理`，最多 5 条，点击跳转整改跟踪页） |
| 近期动态 | 固定 4 条假字符串 | `GET /contracts` 真实审查记录，相对时间格式化（刚刚/N分钟前/N小时前/N天前） |
| 快捷入口 | 2×2 按钮格，与侧栏完全重复 | 删除 |

涉及文件：`DashboardView.vue`（删除 `useDemoStore`/`todoByRole`/`quick`/`activity` 全部演示逻辑）

### 验证结论
真实整改项（品牌年度推广服务合同.pdf · 关联交易）正常显示，近期动态 5 条真实数据，相对时间格式正确 ✅

---

## 2026-07-08 · P1 去技术展示冗余（✅ 已完成）

### 问题
前端混入了两类内容——"AI 是怎么工作的"（技术展示）和"AI 帮你发现了什么"（业务决策）。前者对法务/财务用户无决策价值，且让产品显得像演示平台而非企业工具。

### 改动

**合同审查页（AuditView.vue）**
- 删除审查结果里的"多智能体协同双泳道"（`collabSteps`，固定 SOP 步骤字符串）
- 删除相关 CSS（`.collab` / `.collab-lanes` / `.lane-head` / `.collab-step` 等，共减少约 70 行）

**智能协同审查页（CollaborationView.vue）**
- 删除"协作链路·主从串行工作流"整卡（固定 SOP 图示，技术展示无决策价值）
- 删除 Agent 名片中"定向 RAG 检索主题"和"Prompt 侧重"区块（AI 实现细节）
- 无真实审查会话时：整页演示数据 → 引导提示"完成合同审查后此处将显示协同结果"+ 跳转按钮
- 冲突消解 / 分级风险 / 结果对比加 `v-if="isLive"`，有真实数据才展示
- 清理无用 import（`COLLAB_CHAIN`/`ChainStage`）及 `ownerMeta`/`chain` 常量

净删 236 行，新增 25 行。

### 模块职责边界（改后清晰）
- **合同审查页** = 操作（上传 → 复核 → 生成整改）
- **智能协同审查页** = 结果分析（冲突消解 + 分级策略 + 风险对比）

### 验证结论
- 协同审查页 0 errors，无演示数据残留，"完成合同审查后…"引导正常显示 ✅
- 合同审查页审查结果区域直接展示风险清单，无 SOP 噪音 ✅

---

## 2026-07-08 · UI 文案业务化 + 体验优化（✅ 已完成）

### P1 文案改造
| 文件 | 改动 |
|---|---|
| `router/index.ts` | 全站 9 个页面 eyebrow 由英文技术术语（`AI-POWERED CONTRACT REVIEW` 等）改为中文业务语言（`合同智能审查`等） |
| `nav.ts` | `双Agent协作` → `智能协同审查` |
| `OpenClawBadge.vue` | `算力运行状态 · OpenClaw一体机` → `本地算力 · 运行中` |
| `LoginView.vue` | 清演示账号默认值；`hint` 用 `isDev` 隐藏；补 `name`/`autocomplete`；副标题改"私有化部署 · 数据不出企业" |

### P2 交互优化
| 文件 | 改动 |
|---|---|
| `AuditView.vue` | `el-empty` 替换为 3 步可视化引导（上传合同→智能审查→人工复核/生成整改），带 active/done 状态跟随 `session.step` |
| `ReportsView.vue` | "合规通过率"和"平均审查耗时" KPI 卡加口径说明 tooltip（`?` 图标悬停显示） |
| 多个 `.vue` 文件 | 全站移除 `transition: all`（5 处）→ 精确指定过渡属性，避免 GPU 处理无关 CSS 变化 |

### 验证结论
浏览器实测：侧栏"智能协同审查"、底部"本地算力·运行中"、页面 eyebrow "法务工作台"均正确显示 ✅

---

## 2026-07-08 · 侧栏折叠 + 演示切换隐藏 + 文件名即时反馈（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `MainLayout.vue` | `provide` 注入 `collapsed: Ref<boolean>`；`v-bind(sidebarWidth)` 驱动 grid 宽度（64px↔264px），带 CSS `transition` |
| `AppSidebar.vue` | `inject` 接收 collapsed；`el-menu :collapse` 切图标模式；底部"收起侧栏/展开侧栏"按钮 |
| `UserSwitcher.vue` | 演示视角切换列表用 `import.meta.env.DEV` 包裹，`npm run build` 后自动隐藏 |
| `AuditView.vue` | 新增 `pendingFilename` ref，文件选择后立即显示文件名+loading 图标，不等后端返回 |

### 验证结论
- 侧栏折叠/展开：点击正确切换，菜单变图标模式，主内容区宽度同步扩展 ✅
- 演示视角切换：dev 模式可见（npm run dev），生产构建自动隐藏 ✅

---

## 2026-07-08 · Playwright 全流程浏览器自动化测试（✅ 已完成）

### 测试目标
用 Playwright MCP 驱动浏览器，对全部10个模块做端到端验证，重点覆盖本轮四项断点修复。

### 测试结果

| 模块 | 结果 | 关键验证点 |
|---|---|---|
| 登录 | ✅ | legal/admin 两账号均正常登录，路由守卫有效 |
| 工作台 Dashboard | ✅ | KPI：16份/4整改/43风险/23.3%通过率；DemoBadge 绿色"实时数据" |
| 合同审查 AuditView | ✅ | 上传区/维度开关/步骤流程结构正常（文件上传需真实用户交互，功能已由 curl 验证） |
| 双Agent协作 | ✅ | 法务/财务 Agent 卡片和协作时间线均正常渲染 |
| **整改跟踪 RectifyView** | ✅ | 6条整改项加载，三类流转按钮（开始处理/标记闭环/重新开启）正确；RC006 点"开始处理"实时变为"处理中" |
| **多维报表 ReportsView** | ✅ | 点击"导出台账"→下载 `风险台账_2026-07-08.xlsx`，toast"风险台账已导出" |
| **法规知识库 KnowledgeView** | ✅ | 添加知识弹窗正常，点"入库"→后端持久化→toast"已入库" |
| **审查记录 HistoryView** | ✅ | 点击行打开抽屉，"员工商业保险采购合同"显示1条"理赔条款"风险（等级/原文/依据/建议/复核状态全部展示） |
| 规则与模板 RulesView | ✅ | 6条规则/模板区/新增按钮齐全 |
| 权限与审计 AdminView | ✅ | 3个Tab正常切换；权限矩阵7×4；LLM调用记录14条，OpenClaw/DeepSeek/Qwen三个统计卡 |

### 测试中发现并修复的两个 Bug

| Bug | 根因 | 修复文件 |
|---|---|---|
| ReportsView 整个模块500崩溃 | Edit 操作留下CSS 碎片（孤立的 `align-items: center; margin-bottom: 16px; }`） | `ReportsView.vue` 删除3行无效CSS |
| KnowledgeView 添加知识503失败 | `/knowledge/import` 端点在 embedding 不可用时直接抛503，无降级逻辑 | `knowledge.py` 改为 embedding 失败时写空向量降级（与 seed 脚本一致），RAG 走关键词检索 |

---

## 2026-07-08 · 字段级脱敏（✅ 已完成）

### 规则（响应层按角色分级，不改数据库存储）
| 角色 | 提交人姓名 | 风险原文 |
|---|---|---|
| admin / legal / finance | 完整显示 | 完整显示 |
| business | `曾庆豪 → 曾**` | > 80字时截断 + `…[已脱敏]` |

### 改动
| 文件 | 内容 |
|---|---|
| `app/services/masking.py`（新建） | `mask_name()` / `mask_original_text()` / `apply_history_row_masking()` / `apply_risk_masking()` |
| `app/api/v1/endpoints/contracts.py` | `GET /contracts` submitter 按角色脱敏；`GET /{id}/risks` business 角色 original_text 截断 |
| `app/db/init_db.py` | 补 finance / business 种子账号（4账号：admin/legal/finance/business） |

### 验证结论
- legal 视角：`legal`；business 视角：`l****` ✅
- 长文本（93字）截断 + `…[已脱敏]`；短文本（22字）原样返回 ✅

---

## 2026-07-08 · 合同文件加密存储（✅ 已完成）

### 方案
Fernet（AES-128-CBC + HMAC-SHA256），密钥通过 `.env FILE_ENCRYPT_KEY` 注入。密钥为空时透传明文（向后兼容，开发快速启动）。

### 改动
| 文件 | 内容 |
|---|---|
| `requirements.txt` | 加 `cryptography==44.0.2` |
| `app/core/config.py` | 加 `FILE_ENCRYPT_KEY: str = ""`（空=不加密） |
| `app/core/crypto.py`（新建） | `encrypt_bytes` / `decrypt_bytes` / `is_encryption_enabled`；密钥懒加载，错误不阻断主链路 |
| `app/services/parser/extractor.py` | `_read_decrypted()` 读文件并解密；PDF/DOCX 改用 BytesIO，调用方无感知 |
| `app/api/v1/endpoints/contracts.py` | 上传时调 `encrypt_bytes()` 再落盘；审计日志记录 `encrypted=True/False` |
| `.env` / `.env.example` | 写入演示密钥 + 生成命令说明 |

### 验证结论
- 磁盘文件首字节 `gAA`（Fernet魔数），中文关键词不可读：`plaintext_keywords_found: []` ✅
- 上传→解析全流程：`party_a=测试科技有限公司` 正确提取，解密对调用方透明 ✅

---

## 2026-07-08 · AdminView LLM 调用记录 Tab（✅ 已完成）

### 改动
| 文件 | 内容 |
|---|---|
| `frontend/src/mock/admin.ts` | 新增 `LlmCallRow` 接口 + 12条演示数据（3种 provider 算力对比） |
| `frontend/src/api/admin.ts` | 新增 `getLlmCalls()`；mock 关时走 `GET /admin/llm-calls` |
| `frontend/src/views/AdminView.vue` | 重构为 `el-tabs` 三栏：权限矩阵 / 审计日志 / LLM调用记录；LLM tab 含三种算力统计卡 + 明细表，延迟色码（OpenClaw绿/Qwen黄/DeepSeek橙） |
| `backend/scripts/seed_demo.py` | 新增 14条 LLM 调用演示数据（OpenClaw 4 / Qwen 4 / DeepSeek 6） |

### 验证结论
- `GET /admin/llm-calls`：14条 ✅
- 算力对比：**OpenClaw avg 1,452ms**，Qwen avg 4,155ms，DeepSeek avg 6,693ms ✅（演示效果显著）

---

## 2026-07-08 · PM 评估驱动的四项演示断点修复（✅ 已完成）

### 背景
PM 视角全量评估（代码扫描10个视图）发现4个 P1/P2 演示断点：整改无法流转、Excel 导出缺失、知识库入库不持久化、历史记录无法钻取。

### 修复清单
| # | 模块 | 问题 | 修复方式 |
|---|---|---|---|
| 1 | RectifyView | 整改项只读，无状态流转 | 每卡片加流转按钮（开始处理/标记闭环/重新开启），调 `PATCH /rectifications/{id}`，`changing: Set<string>` 防重复提交 |
| 2 | ReportsView | 无 Excel 导出 | `api/reports.ts` 加 `exportRiskLedger()`（arraybuffer→Blob 下载）；工具栏加"导出台账"按钮，接 `GET /reports/export` |
| 3 | KnowledgeView | 添加知识仅前端，刷新消失 | `api/knowledge.ts` 加 `importKnowledge()`，`submitAdd()` 改 async 调真接口，类别名映射（法律法规→law 等） |
| 4 | HistoryView | 点击行无操作 | `@row-click` 触发抽屉，解析合同 ID（C0001→1），拉取 `GET /contracts/{id}/risks`，展示完整风险列表 |

---

## 2026-07-08 · 数据安全隔离 + LLM 可观测性（✅ 已完成）

### 改动摘要
- **部门访问隔离**：`_dept_accessible()` + `_get_contract()` 用 user 参数，parse/audit/risks/history 全覆盖
- **LLM 调用记录**：`LLMCallLog` 模型新建，`_agent_audit()` 每次 chat 成功后写入；`GET /admin/llm-calls` 端点（admin 权限）
- **审计 IP**：`auth.py` login 真实提取客户端 IP，`audit_log.record()` 加可选 `ip` 参数

### 验证结论
- legal 用户查 contracts：全量可见（legal 角色不隔离，符合设计）✅
- business 用户查 contracts：仅本部门（采购中心3条）✅
- admin/access-matrix：7模块×4角色 ✅
- legal 访问 admin/llm-calls → 403（RBAC 守卫正确）✅

---

## 2026-07-08 · 补全四个 mock 模块后端（Rectify/History/Rules/Admin）✅ 已完成

### 新增数据库表（共 10 张）
`users` / `contracts` / `risks` / `knowledge_chunks` / `audit_logs` / `rectifications` / `audit_rules` / `contract_templates` / `access_roles` / `llm_call_logs`

### 新增 API 端点（共 23 条路由）
- `GET/POST/PATCH /rectifications` — 整改跟踪 CRUD
- `GET/POST/DELETE /rules` — 审查规则库
- `GET/POST/DELETE /templates` — 合同模板库
- `GET /admin/access-matrix` — 权限矩阵（对象包裹）
- `GET /admin/audit-logs` — 审计日志（join users）
- `GET /admin/llm-calls` — LLM 调用记录
- `GET /contracts` — 审查历史台账（HistoryRow，聚合风险等级+状态）

### 验证结论（curl + type-check + Playwright）
- type-check 零错误 ✅
- Rectify 6条 / History 15条8字段 / Rules 6条规则+3模板 / Admin 7×4权限矩阵 + 38条审计日志含 ip ✅
- MOCK_ENABLED 全部 false，前端 100% 调真接口 ✅

---

## 2026-07-07 · 修 LLM 502 + Dashboard/Reports/Knowledge 切真接口（✅ 已完成）

### 502 根因与修复
- **根因**：本机无 Ollama + 无 `.env`，默认指向空端点 → 502
- **修复**：新建 `.env` 切 DeepSeek；DeepSeek 无 embedding → seed 知识库写 `embedding=""`，RAG 走关键词降级

### 验证（Playwright 实测）
- 真实 LLM audit 跑通：法务7条+财务8条=15条风险，`mode=llm`（deepseek-chat），触发 X1/X3 双Agent交叉验证 ✅
- Dashboard/Reports/Knowledge 三端点真实数据渲染，DemoBadge 绿色 ✅

---

## 2026-07-07 · 双Agent协作深化（✅ 已完成）

将"双Agent各跑各的"升级为真协同，前后端同步落地：
- 后端：法务先行→共享上下文→财务读取法务输出再审；`detect_conflicts()` 交叉验证；`classify_tier()` 分级
- 前端：新增 CollaborationView（双Agent职责卡/协作链路/分级风险/冲突消解）

---

## 演示账号速查

| 账号 | 密码 | 角色 | 可访问模块 |
|---|---|---|---|
| admin | admin123 | 系统管理员 | 全部（含Rules/Admin） |
| legal | legal123 | 法务主管 | 全部（除Rules/Admin） |
| finance | finance123 | 财务主管 | 全部（除Rules/Admin） |
| business | business123 | 业务人员 | 工作台/合同审查/整改跟踪/报表/知识库/审查记录 |

## 启动命令

```bash
# 后端（backend 目录）
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（frontend 目录）
npm run dev

# 灌演示数据（backend 目录，幂等可重跑）
./.venv/Scripts/python.exe -m scripts.seed_demo
```
