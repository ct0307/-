# Git 工作树清理清单

更新时间：2026-09-07

本清单记录当前 Git 工作树事实和后续安全边界。工作树或分支删除仍需用户逐项明确确认；本文件不构成删除授权。

## 当前状态

| 分支 | 工作树 | 与 `master` 关系 | 处置边界 |
|---|---|---|---|
| `master` | `C:/Users/chentao/Desktop/浙江省外包赛` | 主工作区；相对 `origin/master` 领先 30 个提交 | 保留；当前资产清理变更尚未提交 |
| `codex/materials-redesign` | `C:/Users/chentao/Desktop/浙江省外包赛/.worktrees/materials-redesign` | 已并入 `master` | 含未跟踪验收产物，归档并再次确认前不得移除 |
| `codex/contract-solution` | `C:/Users/chentao/.config/superpowers/worktrees/浙江省外包赛/contract-solution` | 已并入 `master` | Git 标记为 `prunable`，确认目标不存在后方可修剪登记 |
| `codex/enterprise-hard-indicators` | `C:/tmp/codex-worktrees/enterprise-hard-indicators` | 已并入 `master` | 按既定边界保留，不在本轮处理 |

## 已完成清理

- `codex/workspace-organization` 已完成合并和分支收尾，不再登记工作树。
- `codex/collaboration-acceptance-package` 经审查确认为过期阶段性产物；用户于 2026-09-07 明确输入 `discard` 后，已删除本地分支和工作树。

## 材料重构验收产物

盘点范围：`C:/Users/chentao/Desktop/浙江省外包赛/.worktrees/materials-redesign/a03-contract-audit/outputs/`

| 指标 | 结果 |
|---|---|
| 文件数 | 280 |
| 总大小 | 129,015,418 字节（123.04 MB） |
| 清单 SHA-256 | `85155BF3E97D0B9775EDABA557EADC20D7DE2989674932D77C7D98BB82C1BA61` |
| Git 状态 | 整个 `a03-contract-audit/outputs/` 未跟踪 |

清单哈希计算口径：递归按完整路径排序，对每个文件计算 SHA-256，再对 UTF-8 编码的“文件哈希 + 两个空格 + 相对路径”逐行清单计算 SHA-256。

该目录包含 Word/PDF 回归文件、页面渲染图、接触表、截图、日志和辅助脚本。移除 `materials-redesign` 工作树前，必须将需要保留的文件复制到主项目忽略目录，逐文件核对 SHA-256，并再次获得用户确认。

## 后续允许操作

只有用户再次明确确认后，才允许执行：

1. 归档并核验 `materials-redesign` 的未跟踪验收产物。
2. 从主工作区移除已合并的 `materials-redesign` 工作树。
3. 确认目标路径不存在后执行 `git worktree prune`，修剪 `contract-solution` 失效登记。

未经另行授权，不删除剩余分支，不处理 `enterprise-hard-indicators` 工作树，不推送或强推。
