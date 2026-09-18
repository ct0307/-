# 审查失败可见性与安全提速实施计划

> 按已批准规格在当前会话顺序执行，各任务先红灯再实现；不使用并行代理、不提交或部署。

**目标：** 失败原因和操作建议可见，服务端仅重试可恢复项，批量优化通过质量门再启用。

**架构：** 失败模块统一读取结构化任务快照并输出安全映射。接口与服务端重试复用同一判定。评测先校验身份与质量，再报告速度。

**技术栈：** FastAPI、Pydantic、SQLAlchemy、Vue、TypeScript、pytest、Playwright。

## 任务 1：统一失败契约

- [x] 新增 backend/tests/test_audit_failure.py：快照超时、拒绝、损坏快照、未知错误、历史原因与脱敏测试。
- [x] 执行 backend/.venv/Scripts/python.exe -m pytest tests/test_audit_failure.py -q，确认模块缺失红灯。
- [x] 新增 backend/app/services/audit/failure.py，返回 error/error_code/retryable/error_action；从已知码生成文案，不输出原始 detail。
- [x] 修改 backend/app/schemas/batch.py 与 runner.py 接入失败模块；测试通过后再改服务端 retry_batch 筛选。
- [x] 在 test_batch_api.py 添加混合失败筛选测试，红灯后修改 batches.py；执行相关后端回归。

## 任务 2：前端失败动作

- [x] 修改 frontend/tests/audit-quality-state-e2e.spec.ts：可重试错误、历史原因、不可重试错误、移动端换行验证。
- [x] 执行 npm.cmd test -- audit-quality-state-e2e.spec.ts，确认缺失展示/错误按钮红灯。
- [x] 修改 frontend/src/api/batches.ts 类型和 frontend/src/views/AuditView.vue：安全原因、错误码、建议、条件重试；兼容旧 API。
- [x] 执行前端用例、type-check，验证 review_required 行为不变。

## 任务 3：性能启用门禁

- [x] 修改 backend/tests/test_audit_performance.py：身份不一致失败、指标缺失 blocked、风险召回下降失败、正式质量相同允许比较。
- [x] 执行性能测试观察红灯，再修改 backend/evaluation/audit_performance.py；保留统计，不把安全指标零值当业务质量通过。
- [x] 添加部署评测协议文档，明确真实公网模型调用需要费用/外发授权，缺条件不启用。
- [x] 运行已有串行/批量 fixture 等价测试，报告实际调用数而非伪造真实耗时。

## 任务 4：验收

- [x] 目标后端/前端回归、完整质量门禁。最终门禁：evaluation 100、backend 1333、frontend 106 通过/38 跳过，type-check 与 build 通过。
- [x] 启动开发服务并用浏览器核对页面、空/失败状态、桌面与移动端截图。空状态通过内置浏览器实测；失败状态通过 Playwright 脱敏接口夹具验证并截图。
- [x] 更新规划记录；保留现有批量开关关闭，明确真实模型/目标数据库实测未执行。
