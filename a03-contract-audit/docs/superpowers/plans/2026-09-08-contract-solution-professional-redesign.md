# 《契鉴》项目详细方案专业重制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成采用八章工程结构、剥离实时结果且不含竞赛化措辞的独立专业重制版 DOCX。

**Architecture:** 现有 Markdown 到 DOCX 的构建链保持不变，新增 `content-professional/` 和 `professional` profile。校验脚本为该 profile 设置独立的结构、事实和页面门槛，最终产物进入忽略目录后复制到桌面提交包。

**Tech Stack:** Markdown、Node.js、docx 9.6.1、Python、python-docx、Microsoft Word、Poppler。

---

### Task 1：建立独立构建与校验配置

**Files:**
- Modify: `a03-contract-audit/docs/contract-solution/scripts/build_docx.js`
- Modify: `a03-contract-audit/docs/contract-solution/scripts/validate_document.py`
- Modify: `a03-contract-audit/docs/contract-solution/package.json`
- Modify: `a03-contract-audit/docs/contract-solution/README.md`

- [ ] 新增 `professional` profile，设为8章、23张图、独立输出和黑白正式版式。
- [ ] 新增专业版固定表格清单，表格只承载真正的行列数据。
- [ ] 新增校验门槛和禁用词检查，禁止竞赛化措辞与实时状态表述。
- [ ] 增加构建命令和README说明，运行语法检查确认配置可加载。

### Task 2：重制第一至第四章

**Files:**
- Create: `a03-contract-audit/docs/contract-solution/content-professional/01-project-overview.md`
- Create: `a03-contract-audit/docs/contract-solution/content-professional/02-requirements-analysis.md`
- Create: `a03-contract-audit/docs/contract-solution/content-professional/03-overall-design.md`
- Create: `a03-contract-audit/docs/contract-solution/content-professional/04-functional-design.md`

- [ ] 第一章仅保留背景、问题、目标、范围、原则和边界。
- [ ] 第二章将业务需求与系统实现解耦，补齐现状流程、目标流程和需求优先级。
- [ ] 第三章集中总体架构、数据状态、集成边界和设计取舍。
- [ ] 第四章按完整合同处理流程编排功能，保留页面、异常和审计证据。
- [ ] 扫描标题、图片、表格与禁用词，确认章节职责没有交叉。

### Task 3：重制第五至第八章及附录

**Files:**
- Create: `a03-contract-audit/docs/contract-solution/content-professional/05-technical-implementation.md`
- Create: `a03-contract-audit/docs/contract-solution/content-professional/06-data-security.md`
- Create: `a03-contract-audit/docs/contract-solution/content-professional/07-deployment-operations.md`
- Create: `a03-contract-audit/docs/contract-solution/content-professional/08-testing-acceptance.md`

- [ ] 第五章只解释技术机制、输入输出、失败方式和降级路径。
- [ ] 第六章集中数据模型、版本、权限、安全、审计、备份和知识治理。
- [ ] 第七章改写为稳定的部署、实施和运行保障方案。
- [ ] 第八章只保留测试与验收方法，删除测试次数、日期和当前状态。
- [ ] 在第八章末尾编排四个附录并保留 `[S01]` 至 `[S06]`。

### Task 4：构建、内容审计与结构校验

**Files:**
- Generate: `a03-contract-audit/outputs/professional-redesign/契鉴_项目详细方案_专业重制版.docx`

- [ ] 运行 `npm.cmd --prefix docs/contract-solution run build:docx:professional`。
- [ ] 扫描 DOCX 正文，确认不含竞赛化措辞、实时测试数量和幕后制作内容。
- [ ] 运行 `validate_document.py --profile professional`，要求结构校验通过。
- [ ] 运行 `git diff --check`，确认源稿和脚本无空白错误。

### Task 5：逐页视觉验收与交付

**Files:**
- Generate: `a03-contract-audit/outputs/professional-redesign/rendered/*.pdf|png`
- Modify: `a03-contract-audit/PROGRESS.md`
- Deliver: `C:/Users/chentao/Desktop/比赛材料提交包/契鉴_项目详细方案_专业重制版.docx`

- [ ] 用 Microsoft Word 导出 PDF，并用 Poppler 生成全部页面 PNG。
- [ ] 逐页检查正文、表格、图片、目录、页眉页脚和附录分页。
- [ ] 将 DOCX 与 PDF 一并交给专业版校验 profile，要求通过。
- [ ] 复制到桌面提交包并核对源/目标 SHA-256。
- [ ] 更新项目进度，记录稳定内容边界、构建结果和视觉验收结论。

### Task 6：专业化二次修订

**Files:**
- Modify: `a03-contract-audit/docs/contract-solution/content-professional/03-overall-design.md`
- Modify: `a03-contract-audit/docs/contract-solution/content-professional/04-functional-design.md`
- Modify: `a03-contract-audit/docs/contract-solution/content-professional/05-technical-implementation.md`
- Modify: `a03-contract-audit/docs/contract-solution/content-professional/07-deployment-operations.md`

- [x] 从真实代码和示例配置核实文件、OCR、模型、任务、轮询和数据环境参数。
- [x] 加入四个机制说明案例，并明确为假设而非实测记录。
- [x] 为关键图补充面向实现与异常路径的解释。
- [x] 将第五章责任边界改为质量反馈与模型治理，将第七章运行边界改为参数校准与方案变更。
- [ ] 重建 DOCX，执行内容、结构、事实边界和逐页视觉检查。
- [ ] 覆盖提交包中的专业重制版并同步项目进度。
