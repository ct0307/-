# 契鉴局部 LangGraph 原型

这是单窗口、单角色的独立编排试点，正式 FastAPI/Celery 不导入本包。操作全部由 `ReplayOperations` 合成回放，不访问模型或真实业务合同；流程测试不能证明法律准确率或提速。

## 运行

从项目根目录执行。当前独立环境已按用户确认创建，无需重复安装：

```powershell
$pilotPython = (Resolve-Path outputs/langgraph-evaluation-20261101/prototype-venv/Scripts/python.exe).Path
$env:PYTHONPATH = (Resolve-Path backend).Path
$env:PYTHONUTF8 = '1'
& $pilotPython -m pip check
& $pilotPython -m unittest discover -s backend/integration/langgraph_pilot/tests -v
& $pilotPython -m integration.langgraph_pilot.worker outputs/langgraph-evaluation-20261101/demo-new demo
```

演示目录必须新建，避免覆盖旧检查点。`worker` 的固定身份、执行令牌、审查人和时间都是合成夹具，不是生产账号或密钥。它会模拟人工批准，以验证恢复授权接口；人工批准不会把未核验依据自动升格。

真实进程崩溃与恢复演示（`crash` 预期退出码为 73）：

```powershell
& $pilotPython -m integration.langgraph_pilot.worker outputs/langgraph-evaluation-20261101/restart-new crash
& $pilotPython -m integration.langgraph_pilot.worker outputs/langgraph-evaluation-20261101/restart-new resume
```

恢复结果的 `new_external_calls` 应为空；已有两次操作响应从调用账本复用，发布记录保持一条。

新机器安装必须先完成依赖确认，使用独立虚拟环境和本目录 `requirements.lock`，指定官方源、`--require-hashes --only-binary=:all:`。该锁只适用于本次 Windows/Python 3.13，其他平台需要重新解析和来源检查；不要直接并入正式后端依赖。

## 文件职责

| 文件 | 职责 |
|---|---|
| state.py | 运行身份、预算、状态与操作协议 |
| repository.py | 独立业务替身、身份围栏、持久调用预留、人工权限及幂等发布 |
| checkpoints.py | 图检查点保存成功后记录提交事件 |
| graph.py | 分页发现、逐条补充、一次定向复核、人工中断及发布桥接 |
| replay.py | 可控合成响应和故障注入 |
| worker.py | 真实子进程退出/恢复和可运行演示 |
| tests/test_pilot.py | 预算、存储、权限、恢复和发布故障回归 |

## 行为边界

- 图检查点与业务替身分别落盘。`durability='sync'` 阻止检查点失败后继续下游；只有真实保存成功才能推进完成计数。提交事件用 checkpoint ID 幂等记录，恢复时补记事件缺口。
- 先持久化调用预留，再执行外部操作，再保存响应。响应落账后、节点检查点前崩溃时可复用响应；供应商是否执行无法确认时保留 pending 预留并交人工，不悄悄重试或释放预算。
- 预算和 UTC deadline 在恢复时必须完全一致；身份包含正文、知识版本、指纹、合同、任务及代次，执行令牌始终向业务替身核验。
- 复核仅在已关联冲突存在时调用一次。模型意见不提高依据可信度；有候选或问题都要进入人工中断。批准仅允许提交待核快照，拒绝不发布。
- 发布按合同/任务/代次唯一，相同快照可幂等重放，不同快照拒绝覆盖。正式系统接入仍需使用原业务事务、权限和质量门禁，不能直接用该替身数据库替换。
- 事件包含 started、computed、committed、failed、interrupted、heartbeat；computed 不是完成。心跳不增加完成数，不记录正文、提示词、响应或密钥。外部云追踪默认强制关闭。
- SQLite 中候选及响应为合成明文；生产加密、保留期限、PostgreSQL 及正式权限集成尚未实现。

设计和验收分别见 `docs/superpowers/specs/2026-11-01-langgraph-pilot-design.md` 与 `docs/engineering-hardening/langgraph-pilot-acceptance.md`。
