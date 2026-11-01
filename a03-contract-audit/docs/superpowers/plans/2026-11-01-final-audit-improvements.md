# 复赛审查效率与专业复核实施计划

**目标：** 落实受控批量调度与法务/财务可读的审查结果，保留质量边界。

**架构：** 复用现有线程池、独立会话和任务执行权；前端通过展示工具将业务摘要与技术追溯分层，不改变后端判定。Vue3/TypeScript/Element Plus、FastAPI/SQLAlchemy、pytest、Playwright，不新增依赖。

## 任务1：受控合同调度（主代理）

- [x] 创建 backend/tests/test_local_audit_concurrency.py：事件同步证明两合同可同时开始，第三项排队；52项均执行且峰值受限，失败一项不阻断其他项；配置拒绝0和5；Celery仍走delay。
- [x] 从backend运行 `.venv/Scripts/python.exe -m pytest tests/test_local_audit_concurrency.py -q`，确认缺少配置/调度行为导致失败。
- [x] 修改 backend/app/core/config.py、backend/app/tasks/dispatcher.py、backend/.env.example，新增 `AUDIT_LOCAL_CONCURRENCY: int = Field(default=2, ge=1, le=4)`，用该配置构造本地审查线程池。
- [x] 检查真实SQLite任务隔离和既有领取/恢复测试；如存在写锁或跨线程问题，先复现再局部修复，不绕过执行权门禁。已复现并修复竞争重复领取。
- [x] 运行新增测试与 test_import_dispatcher.py、test_batch_service.py、test_batch_api.py 等相关回归；最终定向回归92项通过。

## 任务2：专业复核展示（前端代理）

- [x] 检查 RiskOut、AuditView、RiskReviewDrawer、risk-evidence/audit-trace工具及现有Playwright测试。
- [x] 先写业务状态和未定位原文回归，运行确认失败，再修改组件。
- [x] 新增集中展示工具：未知时点、失效、未生效、定位失败和事实冲突的业务解释；摘要去重和技术折叠，不删除原始诊断。
- [x] 列表优先显示待办与复核摘要；100%标注机器处理。详情优先问题/建议/原文/依据，提供法务和财务关注提示，不虚构字段或来源。
- [x] 正常、待核、空、错误、375px和1280px界面回归；运行 `npm.cmd run type-check` 及相关Playwright。最终专项22项通过，标签／说明综合状态一致。

## 任务3：集成与验收（主代理）

- [x] 检查 diff、权限、真实性和兼容性；按规格与代码质量分别复查。
- [x] 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality_gate.ps1`，等待完成并读取退出码与摘要。最终退出0，五步骤全部通过。
- [x] 通过浏览器实测审查列表→详情→技术展开及视角切换；记录控制台和桌面/移动端证据。
- [x] 新建 docs/engineering-hardening/final-audit-improvements-acceptance.md，汇总命令、结果和真实52份/模型质量/生产环境未验收项，更新本轮规划状态。

本轮不自动提交或部署；保留用户原有改动。若环境导致某项验收无法执行，保留明确缺项，不降低质量门槛。
