# 局部 LangGraph 试点实施计划

> **For agentic workers:** 使用 subagent-driven-development 分工实施并审查，按下列检查项跟踪；不自动提交。

**目标：** 修复预算误分类和阶段反馈，交付与正式服务隔离、具备持久恢复测试的 LangGraph 原型。

**架构：** 生产链路只做明确的基础修复。原型置于 backend/integration/langgraph_pilot，使用独立虚拟环境、SQLite 检查点及独立业务仓库，通过注入操作回放合成数据，生产集成另行晋级。

**技术栈：** Python 3.13、现有 FastAPI/Pydantic、LangGraph 1.2.19、SQLite checkpoint 3.1.3、unittest/pytest。

**执行记录：** 任务 1～5 已完成。独立原型最终 35 项、浏览器新增 5 项通过；完整门禁修复一次测试期望漏项后重跑通过：评测100、后端1780、前端170项通过，44项按默认服务条件跳过，类型检查及构建通过。人工权限仅为隔离夹具，真实 A/B 与生产桥接不在本轮宣称完成范围。保留当前分支与全部未提交改动。

## 任务 1：预算错误分类

文件：backend/app/services/audit/protocol.py、review_pipeline.py、failure.py；相关前端错误文案如有独立白名单；新增 backend/tests/test_audit_budget_classification.py。

- [x] 写测试：共享预算只有一次额度，第二个模型请求被拒绝，issue.code 保持 AUDIT_BUDGET_EXHAUSTED，不能保存有效检查点或自动重试。
- [x] 用 backend/.venv/Scripts/python.exe -m pytest tests/test_audit_budget_classification.py 验证失败原因是错误码丢失。
- [x] 在 ReviewIssueCode、_map_error_code、_issue、失败文案中保留准确机器码，明确不自动重试。
- [x] 跑新增及 review_pipeline、audit_failure、agent_workflow 测试。

核心行为：`WindowReviewer._map_error_code('AUDIT_BUDGET_EXHAUSTED') == 'AUDIT_BUDGET_EXHAUSTED'`。

## 任务 2：真实阶段反馈

文件：backend/app/services/audit/auditor.py、review_pipeline.py、progress.py 与匹配的前端阶段文案/类型；新增相关回归测试。

- [x] 先测试窗口内部 discovery/enrichment 阶段在窗口完成前送达，并保持调度线程数据库写入及已有执行围栏。
- [x] 阶段反馈与真实事件绑定，不制造基于时间的完成百分比；避免 SQLite 工作线程写入和事务长占用。
- [x] 窗口开始前将阶段从 parsing 更新到审查阶段，完成百分比保持单调。
- [x] 验证正常、错误、空结果及旧执行者不能覆盖状态。若改前端执行类型检查、构建和浏览器验证。

接口方向：在 WindowReviewer 注入只投递内存事件的 stage callback，由调度线程汇聚后调用既有 progress_callback。

## 任务 3：独立依赖环境

目录：outputs/langgraph-evaluation-20261101/prototype-venv；锁文件已审计且用户已明确同意安装。

- [x] 从官方 PyPI 按 --require-hashes、--only-binary 安装精确锁文件，保留安装日志。
- [x] 运行该环境 python -m pip check 并核对关键版本，禁止变更 backend/.venv 和正式 requirements。
- [x] 关闭 LANGSMITH_TRACING、LANGCHAIN_TRACING_V2 等外部追踪配置。

## 任务 4：图原型与持久仓库

新增：backend/integration/langgraph_pilot/{__init__,state,repository,graph,replay}.py，以及 tests/test_pilot.py。使用标准 unittest，避免新增测试依赖。

- [x] 先写无冲突零额外复核、单次冲突复核、预算/时限、节点失败后恢复、人工中断权限、版本/执行权失效和发布幂等测试，观察失败。
- [x] 实现 RunIdentity、候选结构和 Operation 协议；不导入生产配置或密钥。
- [x] 用 SQLite 事务持久化调用预留/响应、运行身份、授权、事件和发布快照；检查点独立保存。
- [x] 图节点：校验 → 分页发现 → 补充一项 → 条件冲突复核 → 候选快照 → 人工中断 → 发布桥接。每页有上限，预算跨重启不重置。
- [x] 未知外部响应保持预留且禁止静默重复调用；不承诺无幂等供应商的恰好一次。
- [x] 人工恢复先在仓库验证用户、合同、代次、中断和决策再 resume；未经批准不能发布。模型不能批准证据。
- [x] 成功检查点之后恢复跳过已完成节点；使用子进程验证重新打开 SQLite 后恢复。
- [x] 回放输出仅为流程证据，不是模型准确率和提速证明。

验证命令：独立环境 python -m unittest discover -s backend/integration/langgraph_pilot/tests -v。

## 任务 5：验收与文档

- [x] 完成规格审查和代码质量审查，修复发现。
- [x] 正式代码改动运行 scripts/quality_gate.ps1，原型独立跑全部恢复测试及 pip check。
- [x] 新增 docs/engineering-hardening/langgraph-pilot-acceptance.md，区分已修复、已实现原型、尚未生产集成及尚未做真实 A/B。
- [x] 更新 .planning/langgraph-evaluation-20261101 三份记录及设计状态，核对旧基线保持原样。
- [x] 确认 8000/5173 服务仍可访问；不部署、不提交、不重启用户服务。
