# 参赛交付物索引

本目录是参赛材料的唯一导航入口。大型交付文件保留在各自的可追溯构建目录中，不在这里重复复制。

## 当前推荐材料

| 材料 | 状态 | 说明 |
|---|---|---|
| [《契鉴》网评PPT字体排版优化版（PDF预览）](../a03-contract-audit/outputs/qijian-typesetting-20261003/契鉴_网评PPT_字体排版优化版.pdf) | PDF可用，可编辑版待找回 | 18页；当前本地保留同版PDF，原PPTX文件缺失，暂不作为可编辑交付。附[排版验收说明](../a03-contract-audit/outputs/qijian-typesetting-20261003/排版与验收说明.md)、[工作流说明](../a03-contract-audit/outputs/qijian-workflow-ppt-20261003/修订说明.md)、[报表修订说明](../a03-contract-audit/outputs/qijian-report-upgrade-ppt-20261002/修订与验收说明.md)与[原有证据说明](../a03-contract-audit/outputs/qijian-evidence-revision-20261002/验收与证据说明.md) |
| [项目详细方案重构版](../a03-contract-audit/契鉴_项目详细方案_重构版.docx) | 已完成 | 7 章往届式版本，已完成 Word 分页、结构、事实、语言和逐页视觉验收 |
| [项目概要介绍重构版](../a03-contract-audit/docs/project-overview/契鉴_项目概要介绍_重构版.docx) | 已完成 | 9 页往届式版本，已完成结构、事实、语言和逐页视觉验收 |
| [《契鉴》参赛答辩 PPT](../a03-contract-audit/docs/competition-materials/契鉴_参赛答辩PPT.pptx) | 已完成 | 15 页主讲、5 页答辩备份，16:9，带逐页演讲者备注；5 张原生表格；无动画和旁白；已完成 SVG 与 PowerPoint 逐页视觉验收 |

## 历史材料

| 材料 | 状态 | 说明 |
|---|---|---|
| [原项目详细方案](../a03-contract-audit/docs/contract-solution/契鉴_项目详细方案.docx) | 历史版本 | 17 章版本，保留用于回归和内容追溯 |
| [原项目概要介绍](../a03-contract-audit/docs/project-overview/契鉴_项目概要介绍.docx) | 历史版本 | 12 页版本，保留用于回归和内容追溯 |
| [RAG 工作流审查报告](../a03-contract-audit/docs/reviews/2026-09-15-rag-workflow-review.md) | 历史审查 | 反映 2026-09-15 状态，非当前缺陷清单；保留问题与修复记录供追溯 |

## 本地验收产物

以下及上方 `outputs/` 链接指向本机忽略目录，Git 克隆不会自动包含这些文件；分享时需随交付包提供。

### 2026-10-02 导出报表升级（本地验收）

- [Excel审批报告](../a03-contract-audit/outputs/report-upgrade/审批报告_单合同.xlsx) / [Word审批报告](../a03-contract-audit/outputs/report-upgrade/审批报告_单合同.docx)：演示库合成合同真实接口导出。
- [交付与验收说明](../a03-contract-audit/outputs/report-upgrade/交付与验收说明.md)：角色用途、验证记录与事实边界；产物保存在忽略目录，不重复复制。

## 待制作材料

| 材料 | 状态 | 下一步 |
|---|---|---|
| 测试报告与测试用例 | 待整理 | 汇总自动化、端到端和真实硬指标证据 |
| 团队过程材料 | 待整理 | 记录职责、协作机制、里程碑和产出物 |
| 演示视频 | 待制作 | 录制 3～5 分钟核心业务闭环 |

## 证据边界

- PDF 视觉验收产物位于本地忽略的 `a03-contract-audit/outputs/` 或隔离工作树输出目录；最终提交版未选定前不复制到本目录。
- 真实 52 文件批次、PostgreSQL 16、OCR 准确率、OpenClaw/GPU 和能耗对比仍以 [硬指标证据矩阵](../a03-contract-audit/docs/evaluation/hard-indicator-matrix.md) 的状态为准。
- 自动化门禁通过不等于上述外部硬指标已达标。
- 2026-10-02已另补单请求52份合成原生文档上传解析证据；不替代真实合同全批次模型审查、扫描件或指定设备验收，详见上方网评PPT证据说明。
