# OCR 质量闭环与强制超时设计

## 目标

扫描 PDF 的 OCR 质量必须从解析层完整传递到数据库、审查结果和前端，低置信度合同必须明确进入人工复核状态。生产 OCR 必须在配置时限内可被操作系统级终止，不能依赖推理返回后的事后计时。

本设计不承诺 OCR 准确率达到 90%，不改变现有准确率评测口径，也不把引擎冒烟结果当作比赛验收结论。

## 模块边界

### 解析结果

在 `app/services/parser/extractor.py` 新增不可变的 `DocumentParseResult`：

- `text: str`：最终合并文本。
- `source: Literal["native", "ocr", "mixed"]`：文本来源。
- `ocr_confidence: float | None`：使用 OCR 时的平均置信度。
- `requires_review: bool`：是否必须人工复核。
- `review_reason: str | None`：稳定、可展示的复核原因。

新增 `extract_document(file_path) -> DocumentParseResult` 作为核心接口。保留 `extract_text(file_path) -> str`，内部调用 `extract_document()` 并仅返回文本，兼容回填脚本和非核心调用方。

PDF 解析内部返回结构化结果；DOCX、TXT 和文本型 PDF 返回 `source="native"`、`ocr_confidence=None`、`requires_review=False`。混合 PDF 只要任一补识别页面质量低于门槛，就标记为需复核。

### 持久化

在 `contracts` 表增加：

- `parse_source VARCHAR(16) NOT NULL DEFAULT 'native'`
- `ocr_confidence FLOAT NULL`
- `requires_review BOOLEAN NOT NULL DEFAULT false`
- `review_reason VARCHAR(255) NULL`

通过新的 Alembic revision 增量升级和回滚，不修改已发布首迁移。SQLite 测试和 PostgreSQL 生产使用同一 ORM 定义。

### 审查质量门

`run_audit()` 使用 `extract_document()`，先把解析质量写入合同，再执行现有文本长度校验和审查。

当 `requires_review=True` 时：

1. 允许继续生成自动审查结果，但结论只作为待复核建议。
2. 幂等写入一条 `agent="system"`、`tier="red"`、`review_status="pending"` 的“扫描件识别质量不足”风险。
3. 合同最终状态写为 `review_required`，不能写为普通 `done`。
4. 重跑审查时先清理旧风险，再根据本次解析质量重新生成系统风险，避免重复。

文本严重残缺的现有路径也统一使用 `review_required`，不再以 `done` 表示可信完成。

批次项仍可进入 `done`，表示机器任务已结束；合同级 `requires_review` 表示业务结果尚未人工确认。这样不扩张批次状态机，也不会让恢复调度重复执行已完成任务。

### API 与前端

`ContractOut` 和同步 `AuditResponse` 增加：

- `requires_review: bool`
- `ocr_confidence: float | None`
- `review_reason: str | None`

`BatchItemOut` 增加同名质量字段，由批次查询通过合同关系或显式装配返回。

前端审查结果区显示醒目的人工复核告警和 OCR 置信度；批次文件行显示“需人工复核”状态，但任务进度仍按 `done` 计入完成。普通文本合同不显示额外标记。

## OCR 强制超时

### 执行边界

生产路径在 `engine is None` 时通过独立 Python 子进程执行 RapidOCR。测试或显式注入引擎时保留进程内执行，便于单元测试和替代引擎集成。

父进程通过标准输入传递 PDF 字节，子进程通过带固定协议版本和标记的单行 JSON 返回 `OCRResult`。合同字节和 OCR 文本不写入临时文件，也不放入命令行参数。

子进程入口只负责：

1. 读取标准输入。
2. 调用进程内 OCR 实现。
3. 输出结构化成功或错误消息。
4. 使用明确退出码结束。

父进程使用 `subprocess.Popen`：

- `communicate(input=data, timeout=OCR_TIMEOUT_SECONDS)` 等待结果。
- 超时先 `terminate()`，短暂等待后仍未退出则 `kill()`。
- 无论成功、失败或超时都执行 `wait()` 回收资源。
- 限制标准错误截断长度，日志不记录合同原文。
- 仅解析带固定结果标记的最后一行，避免第三方库日志污染协议。

现有进程内总时间检查继续保留，作为注入引擎和子进程内部的第二层保护；真正的强制边界由父进程负责。

### 错误语义

- 超时：抛出 `OCRTimeout`，异步任务按现有重试策略处理，最终失败时保留可读错误。
- 子进程启动或模型不可用：映射为 `OCRUnavailable`。
- PDF、页数、像素限制：保持 `OCRError/OCRLimitExceeded` 现有语义。
- 非法或缺失子进程响应：抛出 `OCRError`，不返回部分可信结果。

## 数据流

```text
文件
  -> extract_document
      -> 原生文本 ---------------------------> DocumentParseResult
      -> OCR 子进程 -> OCRResult -> 质量映射 --^
  -> Contract 解析质量字段
  -> run_audit
      -> 自动风险
      -> 低置信度系统风险
  -> ContractOut / AuditResponse / BatchItemOut
  -> 审查告警 / 批次复核标记
```

## 测试与验收

### 后端

- 文本 PDF、DOCX、TXT 返回 `native` 且不要求复核。
- 扫描 PDF 和混合 PDF 正确保留来源、置信度与复核原因。
- 低置信度端到端写入合同字段和红色系统风险，合同状态为 `review_required`。
- 高置信度 OCR 不生成质量风险，合同仍为 `done`。
- 重跑不重复生成系统风险。
- API 和批次响应包含质量字段。
- 慢子进程在时限附近被终止并抛出 `OCRTimeout`，验证没有存活子进程。
- 子进程异常、非法响应、模型不可用均映射为稳定错误。
- Alembic 空库升级、增量升级和完整回滚通过。

### 前端

- 普通合同不显示 OCR 告警。
- 低置信度合同显示置信度、原因和“需人工复核”。
- 批次任务完成与业务待复核状态同时正确展示。
- 空状态、错误状态和移动端布局无重叠。

### 完成门槛

- 后端全量测试、前端测试、类型检查和生产构建通过。
- `git diff --check` 通过。
- Compose YAML 服务结构保持不变。
- 没有明文合同临时文件。
- 文档和硬指标矩阵明确区分“质量闭环已实现”与“准确率待真实数据验收”。

## 风险控制

1. 子进程每份扫描合同会重新加载模型，增加固定延迟。先以可靠终止为优先，并在 50+2 实测中记录模型加载成本；没有真实数据前不引入常驻 OCR 服务。
2. 新合同状态可能影响只识别 `done` 的消费者。前端和历史报表必须把 `review_required` 映射为“待人工复核”，批次任务终态保持不变。
3. Windows 与 Linux 的进程终止语义不同。测试覆盖当前 Windows 环境，Docker 验收机再验证 Linux 容器中的 terminate/kill 路径。

## 非目标

- 不在本次实现 SQLite 到 PostgreSQL 的历史数据迁移工具。
- 不新增 OCR 微服务或外部 npm/Python 依赖。
- 不修改冻结金标准和准确率计算公式。
- 不合并 `master`，实现完成并验证后先创建 PR 审查。
