# Git 工作树清理清单

更新时间：2026-09-04

本清单用于后续安全清理工作树。本轮目录治理没有删除工作树、删除分支、推送或修剪 Git 登记。

## 仓库状态

| 项目 | 状态 |
|---|---|
| 当前整理分支 | `codex/workspace-organization` |
| 整理分支相对 `master` | 完成本次验收提交后领先 7 个提交 |
| `master` 相对 `origin/master` | 领先 22 个提交 |
| 主工作区未跟踪内容 | `.planning/`、`a03-contract-audit/outputs/`；新规则合并后将被忽略 |

## 工作树分类

| 分支 | 工作树 | 与 `master` 关系 | 本轮处置 |
|---|---|---|---|
| `master` | `C:/Users/chentao/Desktop/浙江省外包赛` | 主工作区 | 保留 |
| `codex/workspace-organization` | `C:/Users/chentao/Desktop/浙江省外包赛/.worktrees/workspace-organization` | 待合并 | 完成验收后按分支收尾流程处理 |
| `codex/materials-redesign` | `C:/Users/chentao/Desktop/浙江省外包赛/.worktrees/materials-redesign` | 已并入 `master` | 含未跟踪验收产物，待归档与用户确认后移除 |
| `codex/contract-solution` | `C:/Users/chentao/.config/superpowers/worktrees/浙江省外包赛/contract-solution` | 已并入 `master` | Git 标记为 `prunable`，目标不可访问；待用户确认后修剪登记 |
| `codex/enterprise-hard-indicators` | `C:/tmp/codex-worktrees/enterprise-hard-indicators` | 已并入 `master` | 按既定边界保留，不在本轮删除 |
| `codex/collaboration-acceptance-package` | `C:/Users/chentao/Desktop/浙江省外包赛/a03-contract-audit/.worktrees/collaboration-acceptance-package` | 尚有 1 个未合并提交 | 必须保留，不得删除 |

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

未经另行授权，不删除任何分支，不处理 `enterprise-hard-indicators` 和 `collaboration-acceptance-package` 工作树，不推送或强推。
