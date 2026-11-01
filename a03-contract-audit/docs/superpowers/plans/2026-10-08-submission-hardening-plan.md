# 2026-10-08 源码加固实施与验收计划

用户已确认四项范围及设计。正式项目为 `a03-contract-audit/`，基线 `6bcf1a4`，实现分支 `codex/submission-hardening`。不修改原始 ZIP，不安装依赖，不改数据库表结构或 CI/CD。

## 实际接口与完成标准

| 任务 | 实际实现 | 验收 |
|---|---|---|
| 首个管理员 | `python -m scripts.bootstrap_admin --username ops-admin`；getpass两次；至少12字符/最多72 UTF-8字节；已有管理员拒绝；事务锁、审计、回滚、生产配置复用和错误脱敏 | `test_bootstrap_admin.py` |
| 上传容量 | `MAX_UPLOAD_MB=50`、`MAX_BATCH_FILES=200`、`MAX_BATCH_MB=500`；配置正整数；`GET /imports/limits`认证读取；全部上传端点容量口径统一 | `test_import_capacity.py`、导入/批次API、`upload-limits.spec.ts` |
| 证据闭环 | `verify_support(..., mode=..., contract_text=...)`；默认manual_only；deterministic仅有限绝对免责句式与完整民法典506条；版本/规则ID/模式/阶段/原因码追踪 | `test_evidence_validation_modes.py`、`test_evidence_hardening.py`、原证据回归 |
| 抽取与密码 | 保持 `party_a/party_b/subject/amount/duration/payment_terms` 六字段与原文区间；总价/保证金/单价/框架/日期冲突回归；hash拒绝超72字节、verify=False、登录422 | 抽取四suite、`test_security.py`、`test_password_api.py` |

## 实施步骤

- [x] 新行为先观察失败回归，再实现；TDD过程记录在本轮 `.planning/submission-hardening/progress.md`。
- [x] 管理员与上传容量：独立实现及规格复查，修复首次管理员、字符长度、追加数量协议问题。
- [x] 抽取与密码：独立实现；复查发现保证金结构化误取、总价异名冲突、无固定总额及等价日期问题，追加失败回归后修复。
- [x] 证据：修复泛词重叠误采信、元数据覆盖、人工复核回读和事务失败回滚；有限规则须全文回读并排除条件/引用/例外，主体不得相同，法源须含完整506两项。
- [x] API、脱敏、追问、报表计数及Word/Excel、前端风险/历史/协作/报告共用当前证据口径；旧版仅supported标记不能提升为已核验。
- [x] 前端桌面/手机浏览器验证：有限规则/历史降级/人工复核；上传自定义容量、空状态、上传队列、限制接口失败。采用隔离模拟API，不代表真实业务或模型验证。
- [x] 更新 `.env.example` 和 `docs/deployment.md`：生产首次建号、密码边界、上传容量和Nginx人工同步、有限核验能力边界。
- [x] 全部规格复查与独立代码质量审查关闭开放问题。
- [x] 运行完整质量门禁及记录新鲜计数：后端1633项通过；前端132项通过、39项条件跳过；类型与构建通过，整体退出码0。
- [x] 检查diff与禁入文件，提供可复现打包脚本及验收说明。源码ZIP在完整门禁通过后生成，实际产物和校验记录以仓库交付索引为准。

## 统一验证入口

在正式项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

该入口包含评测专项、全部后端测试、前端Playwright、类型检查与生产构建。前端专项：

```powershell
Set-Location frontend
npm.cmd test -- tests/risk-evidence.spec.ts tests/risk-evidence-trace-e2e.spec.ts tests/upload-limits.spec.ts tests/contract-inbox-e2e.spec.ts tests/contract-inbox-workflow-e2e.spec.ts
```

不使用旧测试计数替代本轮验收。真实PostgreSQL、Compose/Nginx容器、真实52文件、真实模型、OCR精度、OpenClaw/GPU、能耗均不属于本轮已验证结果。容量单位为MiB；Nginx默认520m覆盖默认500MiB，自定义更大值需人工同步所有代理。

## 提交边界

不自动提交、推送或部署。源码包从Git已跟踪文件与本轮非忽略新文件取材，排除 `.env`、密钥、合同原件、数据库、storage、outputs、运行日志、模型缓存、node_modules、.venv、.git。本轮验收说明说明合成测试和未验证项目；禁止将回归通过数宣传为业务准确率。
