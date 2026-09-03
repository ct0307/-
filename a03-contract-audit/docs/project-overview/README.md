# 契鉴项目概要介绍

本目录用于生成和验收比赛用《契鉴_项目概要介绍》。默认 `legacy` profile 保留原 12 页材料；`redesign` profile 生成按评委阅读路径重构的 9 页版本，二者互不覆盖。

## 文件说明

- `content/overview.md`：原 12 页正文与图片引用。
- `content/overview-redesign.md`：重构版 9 页正文与图片引用。
- `scripts/build_docx.js`：Word 生成器。
- `scripts/validate_document.py`：DOCX/PDF 结构与事实校验。
- `契鉴_项目概要介绍.docx`：正式 Word 交付物。
- `契鉴_项目概要介绍_重构版.docx`：重构版 Word 交付物。
- `契鉴_项目概要介绍.pdf`：同步预览与视觉验收版本。

## 生成 Word

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' docs/project-overview/scripts/build_docx.js
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' docs/project-overview/scripts/build_docx.js --profile redesign
```

默认生成原 12 页版本。`--profile redesign` 生成独立的 9 页重构版；`--output <path>` 可覆盖当前 profile 的输出位置，路径相对 `docs/project-overview/` 解析。

生成器复用 `docs/contract-solution/node_modules/` 中已经安装并锁定版本的 `docx 9.6.1`，不需要安装外部依赖。

## 校验

```powershell
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' docs/project-overview/scripts/validate_document.py docs/project-overview/契鉴_项目概要介绍.docx docs/project-overview/契鉴_项目概要介绍.pdf
& 'C:\Users\chentao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' docs/project-overview/scripts/validate_document.py --profile redesign docs/project-overview/契鉴_项目概要介绍_重构版.docx
```

校验范围包括页面结构、章节、关键事实、责任边界、图片、替代文字、页眉页脚、页码、表格宽度和 PDF 页数。

## 事实边界

- 自动化测试、数据库表和 API 路由采用 `PROGRESS.md` 截至 2026-07-31 的稳定证据。
- 973 条知识是本机演示库历史验证结果，数据库不随源码分发。
- OCR 字符准确率、52 份冻结文件吞吐、目标 Compose 环境和硬件对照保持“待实测/外部验收”口径。
- 系统输出属于辅助审查意见，不构成法律裁决。
