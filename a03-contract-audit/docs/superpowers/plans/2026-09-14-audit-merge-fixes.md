# 审查可靠性合并修复 Implementation Plan

**Goal:** 修复错误成功与反向加锁，验证后合并本地 master。

**Architecture:** 模型 envelope 必填并隔离旧检查点；任务领取按合同再批次项加锁；复用瞬时数据库分类并执行有限重试。

**Tech Stack:** Python、Pydantic、SQLAlchemy、Celery、pytest。

## 执行清单

- [x] 在 backend/tests/test_audit_protocol.py 和 test_review_pipeline.py 增加缺字段拒绝与执行链回归，运行 `.venv/Scripts/python.exe -m pytest tests/test_audit_protocol.py tests/test_review_pipeline.py -q` 确认失败。
- [x] 修改 backend/app/services/audit/protocol.py：`risks: list[RiskCandidate] = Field(max_length=5)`、`has_more: bool`，版本改为 candidate-v3。补全已有合法测试输入的 has_more，运行上述测试确认通过。
- [x] 在 backend/tests/test_audit_job_service.py 增加实际 SQLAlchemy 查询锁顺序、数据库错误分类和领取前重试测试，先确认失败。
- [x] 修改 backend/app/tasks/audit_tasks.py：先锁 Contract 再锁 AuditBatchItem；复用 window_repository.py 的瞬时错误识别；尚未提交领取事务的瞬时失败只调用有限 self.retry，不发布状态。永久错误保留原分类。API 加入相同可重试错误码。
- [x] 领取异常以 `claim_committed = True`（领取 commit 成功后设置）区分所有权；补 flush/commit 失败回归。dispatcher.py 每轮 `push_request(called_directly=False, is_eager=True, retries=attempt, args=(contract_id, dimensions, item_id), kwargs={})`，finally pop_request；真实 Celery retry 测试确认不触发 apply_async 且最多四轮。
- [x] 运行可靠性相关后端测试及 scripts/quality_gate.ps1；检查差异和源文件编码。

## 分支验收结果

2026-09-14 09:49 至 09:56（UTC+08:00），基础提交 7f4452c 加本次修复工作树：完整门禁退出码 0。评测 87 passed；后端 871 passed、1 skipped；前端 71 passed、26 skipped；类型检查和构建通过。独立复审未发现剩余 P1/P2。PostgreSQL 真实并发未实测，不宣称生产并发达标。

## 提交后执行

根工作区确认 master 和已有文件未改变后执行 `git merge --ff-only codex/llm-audit-reliability`；在 master 运行完整质量门禁并确认 HEAD 与目标分支一致。保留分支、工作树及原有未跟踪文件，不推送。
