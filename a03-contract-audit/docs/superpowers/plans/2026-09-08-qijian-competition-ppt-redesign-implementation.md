# 《契鉴》竞赛PPT重制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 `ppt-master` 生成一份15页主讲、5页答辩备份、带演讲备注且通过视觉和结构验收的新PPTX。

**Architecture:** 现有PPT、获奖参考稿、设计方案和事实材料作为只读来源，新建独立PPT Master工程。先锁定事实与20页叙事，再以完整SVG为页面设计源，经早期门禁、最终门禁、备注拆分和PPTX导出形成新交付物。

**Tech Stack:** PPT Master 6.3、SVG、PowerPoint/PPTX、Python、PowerPoint COM渲染。

---

### Task 1: 初始化独立工程并导入来源

**Files:**
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/`
- Read: `.planning/competition-ppt/projects/qijian-competition_ppt169_20260908/`
- Read: `a03-contract-audit/docs/competition-materials/fact-ledger.md`
- Read: `a03-contract-audit/docs/contract-solution/research/scoring-matrix.md`
- Read: `a03-contract-audit/docs/contract-solution/research/source-register.md`

- [ ] **Step 1:** 运行 `project_manager.py init qijian-competition-redesign-v2_ppt169_20260908 --format ppt169`。
- [ ] **Step 2:** 使用 `project_manager.py import-sources` 导入现稿、获奖参考稿、设计文档、事实台账、评分矩阵、来源登记和原PPT素材目录。
- [ ] **Step 3:** 检查命令输出中的 `skipped` 项，确认 `sources/` 与 `analysis/source_profile.json` 完整。

### Task 2: 核验事实和核心风险案例

**Files:**
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/analysis/case_evidence_matrix.md`
- Modify: `.planning/competition-ppt-redesign-v2/findings.md`

- [ ] **Step 1:** 搜索合同、风险、Agent输出、依据、人工处置、整改和报表证据，记录文件路径与记录标识。
- [ ] **Step 2:** 只有全部标识可证明同源时采用贯穿案例；否则将第6至10页改写为真实能力闭环并明确“演示数据”。
- [ ] **Step 3:** 对每项硬指标映射“已验证、已实现待实测、依赖外部条件”，禁止将自动化测试替代准确率或生产验收。

### Task 3: 创建并锁定20页设计规格

**Files:**
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/design_spec.md`
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/spec_lock.md`

- [ ] **Step 1:** 按已确认的自由设计、现场答辩、520秒主讲和20页页序编写完整I-X Design Spec。
- [ ] **Step 2:** 为每页写明页面任务、关系、构图、原生对象、素材、事实边界、演讲要点和Audience move。
- [ ] **Step 3:** 从Design Spec生成Spec Lock，固定画布、颜色、字体、字号、间距、页脚和截图规则。
- [ ] **Step 4:** 运行 `project_manager.py validate <project_path>`，预期结果为校验通过且无缺失字段。

### Task 4: 制作P01-P05并运行早期门禁

**Files:**
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/svg_output/01_*.svg` 至 `05_*.svg`

- [ ] **Step 1:** 启动Live Preview并运行文字标定，记录预览URL和各字体角色容量。
- [ ] **Step 2:** 依次制作封面、问题价值、总体方案、产品实证和完整流程页。
- [ ] **Step 3:** 运行 `svg_quality_checker.py <project_path> --stage early --json validation/svg_quality_early_report.json`。
- [ ] **Step 4:** 对早期报告中的阻塞项执行一次合并修复，再运行早期门禁验证。

### Task 5: 制作P06-P20并运行最终门禁

**Files:**
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/svg_output/06_*.svg` 至 `20_*.svg`

- [ ] **Step 1:** 制作P06-P10核心证据链，确保案例标识和事实状态一致。
- [ ] **Step 2:** 制作P11-P15证据状态、技术可信、创新差异、交付计划和结尾页。
- [ ] **Step 3:** 制作P16-P20测试、指标、架构安全、竞品来源和团队实施备份页。
- [ ] **Step 4:** 在P05、P10、P15后重新读取Spec Lock并保持后续页面一致。
- [ ] **Step 5:** 运行最终 `svg_quality_checker.py` 并将报告写入 `validation/svg_quality_report.json`，预期0个阻塞错误。

### Task 6: 添加备注并导出PPTX

**Files:**
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/notes/total.md`
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/exports/*.pptx`

- [ ] **Step 1:** 按520秒预算编写15页主讲备注，并为5页备份写答辩提示。
- [ ] **Step 2:** 运行备注拆分脚本，确认20页均有对应备注。
- [ ] **Step 3:** 运行 `finalize_svg.py` 与 `svg_to_pptx.py`，预期导出20页且postflight为 `passed` 或 `passed-with-warnings`。

### Task 7: 逐页视觉与内容验收

**Files:**
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/rendered/`
- Create: `.planning/competition-ppt/projects/qijian-competition-redesign-v2_ppt169_20260908/validation/final_review.md`

- [ ] **Step 1:** 使用PowerPoint渲染全部20页为1600×900 PNG，确认页数和画布正确。
- [ ] **Step 2:** 检查文字截断、重叠、低对比、边距、截图清晰度、状态非颜色依赖和视觉节奏。
- [ ] **Step 3:** 使用文本提取检查页序、错别字、占位符、证据状态和演讲备注覆盖。
- [ ] **Step 4:** 修复发现的问题并重新执行最终门禁、导出和渲染。
- [ ] **Step 5:** 报告新PPTX路径、验证证据和仍待外部实测的指标。
