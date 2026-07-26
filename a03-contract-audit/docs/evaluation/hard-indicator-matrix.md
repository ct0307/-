# 赛题硬指标证据矩阵

更新时间：2026-07-26

状态定义：`已验证` 表示存在本轮可重复执行证据；`代码就绪待实测` 表示实现和自动化契约已完成，但缺真实数据或设备；`阻塞` 表示缺少外部前置条件，禁止写成达标。

| 优先级 | 硬指标 | 目标口径 | 当前状态 | 证据/复现 | 剩余条件 |
|---|---|---|---|---|---|
| P1 | 风险法规溯源 | 每条风险绑定原文、法规来源和建议 | 已验证 | `pytest tests/test_audit_evidence.py tests/test_rag_hybrid.py -q` | 用比赛演示合同补最终截图 |
| P1 | 50 份以上异步批次 | 50 有效 + 2 异常；失败隔离、重试、刷新恢复、启动补投、租约去重、幂等 | 代码就绪待实测 | `pytest tests/test_batch_service.py tests/test_batch_api.py -q`；API 上限 200 份 | 准备 52 份冻结文件并在 Compose 环境执行 |
| P1 | 部门数据隔离 | business 只读本部门，越权显式 403 | 已验证 | `pytest tests/test_report_scope.py -q` | 在 PostgreSQL 容器补接口实测 |
| P1 | PostgreSQL 可交付 | 空库迁移、回滚、应用不绕过 Alembic | 已验证 | `pytest tests/test_hard_indicator_smoke.py -q` | 目标 PostgreSQL 16 执行旧 SQLite 数据导入、核对及备份恢复演练 |
| P1 | 扫描件 OCR | 空文本/乱码触发；混合页补识别；低置信度复核 | 质量闭环已验证，准确率待实测 | `pytest tests/test_parser_contracts.py tests/test_ocr_process.py tests/test_ocr_real_integration.py tests/test_audit_runner_quality.py tests/test_contract_quality_api.py -q`；质量元数据持久化、操作系统级强制超时、人工复核状态和前端告警均有自动化证据；供应链审计见 `ocr-dependency-audit.md` | 在交付镜像复跑 Linux terminate/kill 路径；准备冻结扫描件真值集 |
| P1 | 要素准确率 ≥90% | 冻结人工金标准，字段宏平均，分合同/文档类型报告 | 阻塞 | `python -m evaluation.cli ...`；协议见 `element-accuracy-protocol.md` | 至少双人复核的冻结 JSONL 金标准及真实预测结果 |
| P1 | OpenClaw 优于 GPU | 同模型/提示词/数据集/并发；预热 3 次、正式 5 轮；P50/P95/吞吐/成功率/CI | 阻塞 | `pytest tests/test_runtime_status.py tests/test_benchmark_stats.py -q` | OpenClaw、GPU 对照机、模型哈希、冻结数据集与原始调用日志 |
| P2 | 能耗对比 | 只接受功率计或设备导出的时序值 | 阻塞 | 无功率样本时报告固定为 `not_measured` | 两套设备同口径功率时序 CSV |
| P2 | Compose 私有化部署 | PostgreSQL、Redis、backend、worker、frontend 健康启动 | 代码就绪待实测 | Compose YAML 结构解析通过；backend 自动迁移 | 当前机器安装 Docker 或迁移到具备 Docker 的验收机 |
| P2 | 前端真实状态 | 批次和模型状态均来自服务端 | 已验证 | Playwright Store/质量格式测试、低置信度渲染 E2E、type-check、build；390px 无横向溢出和遮挡 | 用比赛真实扫描合同补最终截图 |

## 禁止使用的证据

- `scripts.seed_demo.py` 中的 LLM 调用记录是演示数据，不得用于 OpenClaw/GPU 性能结论。
- 单份示例合同全部字段命中，不等于冻结测试集准确率达到 90%。
- 真实 RapidOCR 图片/PDF 冒烟只证明引擎调用链可用，不等于冻结扫描件字符准确率实测。
- 未运行 50+2 文件批次时，API 上限 200 不能替代吞吐和成功率验收。
