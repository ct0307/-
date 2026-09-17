# 真实数据与证据报告实施计划

> 用户要求尽量不使用子 agent，已停止唯一后端子 agent，后续实现、审查和验证由主线程完成。已确认设计：.planning/real-data-reports/review-proposal.md。

**目标：** 清理准确识别的演示业务记录，交付基于真实任务与证据的选择导出、报告预览和付款联动检查。

**架构：** 后端统一构造一次报告数据快照，页面、Excel 与 Word 共用；报告范围由合同集合和权限决定，风险按最新任务隔离。前端恢复只持久化账号与合同/任务标识，重新查询真实结果。数据清理使用 SQLite 一致性备份和精确事务。

**技术栈：** 现有 Vue/Pinia、FastAPI/SQLAlchemy、openpyxl/python-docx、pytest/Playwright；不新增依赖。

## 任务与边界
- [x] 1. scripts/cleanup_demo_data.py 与测试：识别批准 ID 的种子签名，备份、完整性检查、事务清理及清单。验证 12 合同、23 风险、14 调用、6 整改，不影响 58 任务。
- [x] 2. backend/app/services/report/ 下建立证据快照与渲染模块；reports.py 增加选择预览与 Word 导出，修正全局报表统计。测试空选、越权、失败最新任务、旧代风险、长文本和公式注入。
- [x] 3. frontend/src/stores/audit-session.ts、utils/session.ts、views/CollaborationView.vue：完成结果按账号保存标识，刷新真实加载，空/错/零风险状态明确，去除自动 DEMO 数据回退。新增恢复回归。
- [x] 4. frontend/src/api/reports.ts、views/ReportsView.vue 与独立组件：合同勾选与筛选；同范围快照预览、风险矩阵、证据卡与收付款节点；Excel/Word 下载。
- [x] 5. 现有 contract_logic.py 基础上补充明确付款事件与跨条款矛盾，金额使用 Decimal；正反例防止不同基数、不同批次、重复引用误报。将解析结果展示在报告中。
- [x] 6. README、相关测试、完整质量门禁、真实浏览器和样例回读完成：后端1295、前端101通过/38跳过、类型与构建通过。
- [ ] 7. Word逐页视觉验收：本机转PDF持续等待，用户停止桌面操作，本轮不继续；结构与内容核对已通过，Excel摘要已视觉检查。

## 测试命令
后端：backend/.venv/Scripts/python.exe -m pytest tests/test_report_scope.py tests/test_evidence_reports.py tests/test_cleanup_demo_data.py tests/test_contract_logic.py -q（backend 工作目录）。
前端：npm.cmd test -- tests/report-selection.spec.ts tests/completed-audit-recovery.spec.ts；npm.cmd run build（frontend 工作目录）。
全量：powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality_gate.ps1。

## 接口契约
POST /reports/preview 请求 {contract_ids: number[] | null}，空数组返回 422，null 表示全部可访问合同。响应为 ReportSnapshot，含 report_id、generated_at、contract_ids、summary、contracts、risks、rectifications、matrix、notes。GET /reports/export?contract_ids=1&contract_ids=2&format=xlsx|docx 保留旧接口，并可接受 report_id 校验快照是否变化（409 时需刷新预览）。后端不信任客户端传入统计。

## 执行裁定
- 现有工作区包含用户未提交内容，创建 codex 分支并在原工作区增量编辑以保持已运行服务与本地数据库位置；不迁移、重置或提交既有内容。
- 用户已确认设计和删除清单，无需重复确认。
- 文档生成复用已确认方案的 python-docx，不安装 Skill 示例中的 Node 包。
- 报告为审查证据快照而非可变财务模型，导出统计固定在同一次数据读取；Excel 明细以安全文本写入。
- P2 版本对比依赖不可变快照和版本关联；硬件提速依赖设备。先实现经确认的 P1 主线并准确记录 P2 未验收项，避免称已完成。

## 可视化看板联动修正（2026-09-17）

用户要求恢复看板，并随实时勾选合同展示。本轮只修改 ReportsView.vue 与报表浏览器测试，保留后端数据口径和权限控制。

- 默认自动加载全部可见合同；跟随勾选模式下，单选或多选自动刷新，取消全部勾选恢复全量。
- 保留明确的当前筛选／全部可见范围；再次勾选合同自动切回跟随勾选。合同选择区可展开，默认收起，让首屏直接展示指标和图表。
- 指标、四张图表、风险矩阵、证据、付款与整改共用同一数据快照；导出使用相同范围和快照标识。
- 连续勾选合并为250毫秒后的请求；更新期间显示加载状态并禁用导出，旧响应不能覆盖新选择。空范围、超过200份显式选择、请求失败均不可导出；离开页面取消延迟刷新。
- 回归覆盖默认看板、单选、跨页多选、取消勾选、筛选空结果、错误重试、迟到响应、离开页面和移动端。真实服务另行验证默认全量、三合同／单合同联动及Excel/Word下载，截图位于 outputs/live-dashboard/。
- 此处“实时联动”指勾选变化自动刷新，不是数据库后台推送；新导入或任务变化后可点击“刷新合同列表”更新。
