# 企业整改闭环实施计划

> 按subagent-driven-development及dispatching-parallel-agents执行固定契约下独立前后端任务；主代理负责集成和验收。用户已授权按所提方案直接修改，不重复询问是否执行。

目标：把整改从状态流转补齐为有计划、有证据、独立验收、可追溯的业务流程。

架构：复用FastAPI／SQLAlchemy、Vue3／Element Plus、现有合同上传和部门授权。原子版本校验与持久事件负责并发及历史，页面读取服务端能力控制操作入口。无需新增依赖。

## 任务1：后端闭环

- [x] 在`backend/tests/test_rectification_closure.py`编写真实SQLite失败用例：本人验收被403阻止、无证据提交被400阻止、旧version被409阻止、风险接受不变已闭环。
- [x] 运行`.venv/Scripts/python.exe -m pytest tests/test_rectification_closure.py -q --tb=short`确认新增断言失败。
- [x] 修改`backend/app/models/models.py`、`backend/app/db/init_db.py`及新增Alembic迁移，增量字段与事件表，保留旧记录。
- [x] 新建`backend/app/services/rectification_workflow.py`集中计划校验、权限能力、证据校验、状态机、版本与事件；整改端点委托服务，更新`backend/app/schemas/contract.py`。
- [x] 扩展失败测试覆盖计划／责任人／材料／签署阶段／退回重提／独立审批／版本冲突／升级及部门隔离，更新与旧行为冲突的既有测试，运行所有整改与授权回归。

## 任务2：前端闭环

- [x] 在`frontend/tests/rectification-closure.spec.ts`先写计划必填、证据必填和业务人员无验收按钮用例；运行`$env:E2E_PORT='41742'; npx.cmd playwright test tests/rectification-closure.spec.ts`确认失败。
- [x] 扩展`frontend/src/mock/rectify.ts`、`frontend/src/api/rectify.ts`及`frontend/src/stores/rectify.ts`，对齐设计契约，mock明确演示性质。
- [x] 新增`frontend/src/components/rectify/RectificationPlanDialog.vue`与详情辅助组件，将`AuditView.vue`一键自动分派改为明确计划表单。保留已确认风险的失败恢复，避免重复生成。
- [x] 更新`RectifyView.vue`，提供责任与验收条件、材料上传／选择、条款对照、独立验收、风险接受、升级及事件时间线；根据服务端能力控制动作，手机抽屉宽度不溢出。
- [x] 更新既有`rectification-workflow.spec.ts`与受影响风险确认回归，执行专项Playwright和`npm.cmd run type-check`。

## 任务3：集成与独立审查

- [x] 按设计核对字段、API和权限，独立检查规格覆盖及代码质量；修复后重跑相关失败用例。
- [x] 补报表快照中的验收字段及风险接受统计语义，避免已接受风险写成已消除。
- [x] 本地数据库备份后，在无在途任务时重启后端；验证增量加列、健康及OpenAPI，保留原服务地址。
- [x] 浏览器实测创建到详情、证据展示、权限、空／错误和375px／1280px；使用独立测试数据，不篡改既有正式风险决定。
- [x] 运行`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality_gate.ps1`，读取退出码、日志和最终摘要。
- [x] 在`docs/engineering-hardening/rectification-closure-acceptance.md`记录结果、使用路径、迁移和能力边界，更新本轮规划。

最终验收：完整门禁5步全部通过、退出0；评测100、后端1885、前端209通过／47跳过，类型检查和构建通过；前端最终专项41项通过。实际浏览器桌面／手机、必填及空状态已检查。独立审查无剩余P1/P2，迁移并发保护专项另经复核。详情及未实测边界以验收记录为准。

本轮不提交、部署、安装依赖或删除文件；不执行生产数据库迁移。不把条款人工对照、上传或提醒登记写成模型核验／外部通知已送达。
