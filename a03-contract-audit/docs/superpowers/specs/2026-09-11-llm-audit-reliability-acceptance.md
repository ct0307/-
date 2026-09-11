# 大模型审查可靠性改造验收记录

日期：2026-09-11

## 验收范围

- 单文件上传内容指纹与用户范围幂等。
- 单文件审查持久任务、派发、重试、孤儿恢复和结果恢复。
- 外部推理短事务、generation 与 execution token 双重陈旧发布保护、模型输出上限。
- 风险与质量结果按任务快照隔离，合同、任务摘要和风险原子发布。
- 批量上传在数据库提交前失败时回滚文件，提交成功后不误删已入库文件。
- 派发失败保持可恢复的 queued 状态并使用安全错误码，模型网络异常不泄露内部地址或响应正文。
- 前端遇到任务 404 时清除永久失效的恢复记录。
- 审计日志与业务写入的事务一致性。
- 前端幂等请求、真实错误、未知状态失败关闭和刷新恢复。
- SQLite/Alembic 迁移兼容、前后端构建与页面响应式。

## 自动化证据

| 验收项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `backend/.venv/Scripts/python.exe -m pytest -q` | 334 passed，1 skipped |
| 前端全量 | `$env:E2E_BASE_URL='http://127.0.0.1:5175'; npm.cmd test` | 40 passed |
| 前端类型检查 | `npm.cmd run type-check` | exit 0 |
| 前端生产构建 | `npm.cmd run build` | exit 0 |
| 项目质量门禁 | `scripts/quality_gate.ps1` | evaluation/backend/frontend/type-check/build 全部通过 |
| 独立终审相关回归 | 上传补偿、派发恢复、错误脱敏、任务隔离与前端恢复 | 后端 60 passed，前端 5 passed |
| Alembic 迁移头 | `backend/.venv/Scripts/python.exe -m alembic heads` | `20260911_01 (head)` |
| Git 格式检查 | `git diff --check` | 无错误 |
| 敏感信息检查 | 变更内容密钥模式扫描 | 无匹配 |
| 大文件检查 | 未跟踪文件大于 1 MiB 扫描 | 无结果 |

质量门禁中的前端 Playwright 未设置 `E2E_BASE_URL`，因此跳过 17 个需要服务的用例；已另行在 `5175` 上执行完整 40 项 Playwright 并全部通过。首次 E2E 运行因 DEBUG SQL 输出未及时排空造成终端缓冲阻塞并出现连接超时；排空输出后，代表性失败文件 4 项与最终完整 40 项均通过。

## 浏览器证据

- 页面：`http://127.0.0.1:5175/audit`，代理至本次启动的后端 `http://127.0.0.1:8001`。
- 页面身份：标题为“契鉴 · 企业合同合规审查系统”，主标题为“合同合规审查”。
- API 探活：页面显示 `DEEPSEEK · deepseek-v4-pro`；后端运行状态通过 `probe_configured_model` 生成。
- 桌面：页面非空，无框架错误覆盖层，控制台无 error/warn。
- 交互：审查维度面板可展开，8 个维度均为可操作复选框。
- 移动端：390x844 下 `scrollWidth=380`、`innerWidth=390`，无横向溢出，控制台无 error/warn。
- E2E：幂等请求头、未知网络结果复用 operation key、按 `job_id` 刷新恢复、持久错误详情显示和停止前端等待语义均通过。
- 幂等语义：上传按内容哈希稳定；审查在单次 operation 内稳定，新一轮主动重审使用新 key。
- 页面收尾：已恢复默认视口、8/8 维度和折叠状态，并保留 `/audit` 标签页。

## 已知边界

- 未执行真实 52 文件批量验收。
- 未执行 PostgreSQL、生产 Celery/Redis、多进程故障注入。
- 未执行 OCR 准确率、GPU/OpenClaw 或能耗实测。
- 未以真实合同触发完整模型审查，避免在验收中传输业务数据；模型连通性由运行状态探活证明。
- 构建存在第三方 `@vueuse/core` PURE 注释位置告警，不影响构建退出码。
