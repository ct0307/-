# 契鉴审查链路与核心体验实施计划

> 执行方式：subagent-driven-development，按任务做规格和代码复核；用户已授权本轮实施，无需重新审批既定方案。保留已有改动，不自动提交。

目标：结果可信、原文可查、进度及时，保持现有架构和部署依赖。

技术：FastAPI / SQLAlchemy / pytest；Vue 3 / TypeScript / Element Plus / Playwright。

## 任务1：历史结论与模型禁用错误

- [x] 后端contracts、历史schema、模型策略/审查错误映射及相应tests：先加失败、未完成、低覆盖以及成功无风险测试，观察失败。
- [x] 将完整度与结论分离，未知状态不推导低风险；禁用模型时显示准确可操作原因；保持旧字段兼容。
- [x] 运行相关pytest；前端HistoryView采用对应状态、筛选和上下文跳转。

## 任务2：窗口即时发布

- [x] 在backend/tests/test_audit_window_concurrency.py加入事件同步测试：快窗口在慢窗口释放前触发flush/回调；保留稳定源顺序断言。
- [x] 在auditor.py用as_completed发布，缓存即时计入，数据库仍仅调用线程写入；不扩大并发。
- [x] 运行窗口并发、检查点和审查进度pytest。

## 任务3：完整解析正文

- [x] 后端正文读取接口及测试：真实缓存文本、跨部门403、角色限制、无缓存明确状态、非暴露内部路径。
- [x] frontend/src/api/contract.ts、types.ts、AnnotationModal.vue、AuditView.vue：完整正文、精确定位、未匹配、重试和过期响应防护。
- [x] frontend/tests新增行为测试，覆盖正常、空、失败、键盘和窄屏。

## 任务4：操作优先级与可访问性

- [x] AuditView与HandoffQueue将上传前置，空交接紧凑呈现，风险卡支持键盘且不干扰内部按钮。
- [x] HistoryView保留所选合同上下文，优先展示未完成状态。
- [x] Playwright验证上述可见行为；不为纯布局写镜像实现的测试。

## 任务5：观测与验收

- [x] 核实现有阶段计时和调用日志，补充可离线使用的分析入口与说明，所有统计区分缺失/零值与独立实验/完整链路。
- [x] 运行后端定向pytest、前端相关Playwright和type-check、完整scripts/quality_gate.ps1。
- [x] Browser插件实际验证隔离上传、确认、失败、历史恢复和正文；记录截图、控制台与尺寸，停止本轮测试服务。
- [x] 复核规格覆盖和代码风险，更新.planning中的证据、状态与剩余限制。
