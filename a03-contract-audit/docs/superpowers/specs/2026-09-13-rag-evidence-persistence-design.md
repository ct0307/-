# RAG 证据持久化闭环设计

## 目标

把当前仅存在于内存中的合同条款、来源锚点、Agent Claim 和检索尝试写入数据库，并通过既有风险查询接口返回，使每条风险能够回答“结论来自哪一条合同原文、位于哪一页、经过几次检索、为何采信”。

## 范围

本阶段只建设后端证据数据闭环，不引入新的 OCR、向量或 Agent 依赖，不修改 CI/CD，不实现 PDF 页面渲染和前端坐标高亮。前端高亮将在本阶段接口稳定后单独实施。

## 方案选择

采用“合同条款关系表 + 风险证据快照”的组合方案：

- `contract_clauses` 保存每次审查生成的稳定条款记录，包含条款 ID、层级路径、邻接关系、字符范围和 `SourceAnchor` 列表。
- `risks` 保存 Claim、法源 Evidence ID、最多两次检索尝试，以及已绑定的合同条款证据快照。
- 风险证据快照不依赖外键。重新审查可替换当前条款记录，同时保留已人工确认风险的历史定位信息。

不采用“所有锚点完全拆表”的方案。当前查询模式始终以风险或条款为入口，JSON 快照能保持 SQLite/PostgreSQL 兼容，减少表连接和迁移复杂度；后续出现大规模坐标检索需求时再拆分。

## 数据模型

`ContractClause` 字段：

- `contract_id`、`audit_generation`：确定条款所属合同和审查版本。
- `chunk_id`、`clause_id`、`clause_path_json`：稳定标识与层级结构。
- `content`、`block_type`、`char_start`、`char_end`：正文及全文范围。
- `parent_chunk_id`、`previous_chunk_id`、`next_chunk_id`：父子和邻接关系。
- `source_anchors_json`：页码、坐标、Word 段落/表格索引等定位信息。

`Risk` 新增字段：

- `claim_id`、`claim_status`。
- `source_window_id`、`source_clause_ids_json`。
- `evidence_ids_json`、`retrieval_attempts_json`。
- `contract_evidence_json`：风险匹配到的条款 ID、路径、锚点、匹配方式和分数。

## 数据流

1. 解析器返回 `DocumentParseResult(text, blocks)`。
2. 发布审查结果前，用 `build_contract_chunks(text, blocks)` 生成条款。
3. 在同一数据库事务中替换当前合同条款、创建风险记录并绑定合同证据。
4. 优先按风险原文精确匹配条款；精确匹配失败时仅使用 Agent 窗口中的 `source_clause_ids` 作为低置信度提示，不伪造精确坐标。
5. 风险接口对 JSON 字段做类型化反序列化；业务角色不返回检索查询原文，避免扩大合同敏感信息暴露。

## 一致性与失败策略

- 条款与风险必须随审查发布事务一起提交；过期 generation 或发布失败时全部回滚。
- 重新审查只替换当前合同的条款记录和待复核风险，不删除已确认/已忽略风险。
- 没有可靠原文匹配时 `contract_evidence` 为空或仅标记 `clause_hint`，继续要求人工复核。
- JSON 反序列化失败时 API 返回空列表，不使风险列表整体失败。

## 验收标准

- DOCX/PDF 解析块可形成数据库条款和来源锚点。
- Claim、Evidence ID、检索尝试在审查结束后可从数据库恢复。
- 风险能绑定精确条款；不精确时明确标记提示匹配。
- Alembic 可从基线升级到 head 并降级；SQLite 旧库可无损补列/建表。
- 新增专项测试、后端完整测试和项目质量门禁通过后，才可声明本阶段完成。
