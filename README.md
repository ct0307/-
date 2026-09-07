# 浙江省外包赛 A03 项目工作区

本仓库的唯一正式项目是 [契鉴企业合同合规审查系统](./a03-contract-audit/README.md)。

## 目录导航

| 目录 | 用途 | 是否正式交付 |
|---|---|---|
| `a03-contract-audit/` | 前后端源码、部署配置、测试和可追溯文档源 | 是 |
| `references/` | 官方赛题与原始需求资料 | 输入资料 |
| `deliverables/` | 最终参赛材料索引 | 是 |
| `.planning/` | 本地 Agent 过程记录 | 否，不入库 |
| `.worktrees/` | 临时 Git 工作树 | 否，不入库 |

## 常用入口

- 项目说明：[a03-contract-audit/README.md](./a03-contract-audit/README.md)
- 项目进度：[a03-contract-audit/PROGRESS.md](./a03-contract-audit/PROGRESS.md)
- 硬指标证据：[hard-indicator-matrix.md](./a03-contract-audit/docs/evaluation/hard-indicator-matrix.md)
- 参赛材料：[deliverables/README.md](./deliverables/README.md)

## 质量门禁

在 `a03-contract-audit/` 目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

质量门禁不替代真实 52 文件、PostgreSQL、OCR 准确率、OpenClaw/GPU 或能耗实测。
