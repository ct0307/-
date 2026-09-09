# 《契鉴》项目详细方案工作区

本目录用于维护《契鉴——企业级合同合规审查与多维报表生成智能体系统项目详细方案》的可追溯源稿、图表资产、构建脚本和最终交付物。

## 文档定位

详细方案面向比赛评审、企业管理者、产品研发与运维安全人员，完整说明问题背景、需求边界、产品方案、系统设计、实施路径和验收标准。全文采用目标态需求与规划视角，不记录开发进度、提交历史、阶段性完成比例、临时知识数量或测试数量。

AI 输出定位为合同审查辅助意见，不构成自动法律裁决，也不替代法务、财务或业务责任人的专业判断。所有关键风险必须能够回到合同原文、适用规则、知识版本和人工处置记录。

## 目录职责

| 路径 | 职责 |
|---|---|
| `research/source-register.md` | 登记政策、法律、行业报告和竞品官方资料，记录适用范围与正文落点 |
| `research/scoring-matrix.md` | 将 A 类赛题四项评分映射到章节、图表和可验证证据 |
| `content/` | 保存 17 个一级章节的 Markdown 源稿 |
| `content-redesign/` | 保存 7 个一级章节的参赛重构版 Markdown 源稿 |
| `content-professional/` | 保存 8 个一级章节和附录的专业重制版 Markdown 源稿 |
| `assets/diagrams/` | 保存统一样式的业务、技术、数据与实施图表 |
| `assets/screenshots/` | 保存经裁切和脱敏的“界面设计示意” |
| `scripts/` | 保存图表生成、DOCX 构建、字段刷新与自动验证脚本 |

## 写作边界

- 现有代码仅用于校验技术可行性、模块边界和演进约束，不作为正文中的成果陈述。
- 市场、政策、法律与竞品结论必须能够追溯到 `source-register.md`；来源没有公开说明的能力统一标记为“公开资料未说明”。
- 详细方案定义测试样本、方法、公式、阈值、判定规则和证据形式；实际测试结果由独立测试报告承载。
- 不覆盖原产品需求分析文档，不修改 `PROGRESS.md`，不把开发日志并入方案正文。
- 不虚构客户案例、用户访谈、知识产权、收入、市场份额、准确率或效率数据。

## 构建流程

首次使用时，在项目根目录安装本目录锁定的构建依赖。安装前应核对 npm 来源、审阅 lockfile，并执行 `npm audit`：

```powershell
npm --prefix docs/contract-solution install
npm --prefix docs/contract-solution audit
```

生成图表和 DOCX：

```powershell
npm --prefix docs/contract-solution run build
powershell -NoProfile -ExecutionPolicy Bypass -File docs/contract-solution/scripts/update_word_fields.ps1
```

默认命令继续生成原 17 章版本。生成 7 章重构版时使用：

```powershell
npm --prefix docs/contract-solution run build:docx:redesign
npm --prefix docs/contract-solution run build:docx:professional
```

重构版输出为项目根目录的 `契鉴_项目详细方案_重构版.docx`，不会覆盖原稿。也可以直接调用构建脚本，并用 `--output` 指定相对本目录的输出路径。

专业重制版输出到 `outputs/professional-redesign/契鉴_项目详细方案_专业重制版.docx`。该版本采用八章工程结构，不记录实时测试结果或竞赛化表述。

## 验证流程

```powershell
npm --prefix docs/contract-solution run validate:screenshots
python docs/contract-solution/scripts/validate_document.py docs/contract-solution/契鉴_项目详细方案.docx docs/contract-solution/契鉴_项目详细方案.pdf
python docs/contract-solution/scripts/validate_document.py --profile redesign 契鉴_项目详细方案_重构版.docx outputs/materials-redesign/契鉴_项目详细方案_重构版.pdf
python docs/contract-solution/scripts/validate_document.py --profile professional outputs/professional-redesign/契鉴_项目详细方案_专业重制版.docx
```

验收门槛为：17 个一级章节、正文 2.5 万至 3.5 万中文字符、40 至 50 页、20 至 30 张有效图片、10 至 15 张表；禁用进度表述、空标题、缺图、断链和无来源关键结论均为 0。

重构版门槛为：7 个一级章节、正文 2.7 万至 3.3 万中文字符、35 至 40 页、22 至 28 张有效图片、8 至 10 张表。重构版允许带日期和条件的本轮验证结果，但必须区分已验证、已实现待实测和依赖外部条件。
