# RAG 工作流专业审查报告

> 历史归档：本报告反映 2026-09-15 的代码与测试状态。2026-10-06 归档时未重新逐项审查，不代表当前待修缺陷或最新验收结论。后续实现以当前代码、回归测试及版本记录为准。

- 项目：`a03-contract-audit`（合同智能审查系统）
- 范围：后端 RAG 全链路 —— 知识入库、检索、审查消费、降级与证据校验
- 审查方式：静态代码精读（未运行动态评测）
- 日期：2026-09-15

---

## 一、RAG 全链路概览

```
【入库链 · 离线/受控】
resources/legal_sources/manifest.json（schema 校验、官方域名白名单、SHA-256、条号范围、预期条数）
  → verify_source_file（防路径穿越 + 哈希校验 + UTF-8 校验）        legal_sources.py
  → parse_articles（逐行条号正则、章节跟踪、重复条号检测）           legal_sources.py
  → validate_article_set（缺条/超范围/条数三项硬校验）               legal_sources.py
  → split_legal_article（380 字、款项→句界→硬切三级拆分，
     retrieval_text = 书名+章节+条号+正文，display/retrieval 分离）   legal_sources.py
  → prepare_documents（本地 bge-small-zh 向量化，
     content_hash + embedding_signature 缓存复用、维度强校验）        retriever.py
  → 单事务原子替换（删旧 source → 写 LegalSource/LegalArticle/KnowledgeChunk） legal_sync.py

  前端上传民法典的旁路：preview（HMAC 令牌、10 分钟 TTL、绑定文件哈希+用户）→ apply  legal_import.py
  业务知识导入旁路：/knowledge/import（legal/admin 角色）→ 服务端切片 → 同步向量化      knowledge.py

【检索链 · 在线】
build_query_plan（条号抽取 + 5 组领域同义词扩展）                     retriever.py
  → 全表加载 KnowledgeChunk ⋈ LegalArticle
  → 默认拒绝过滤（scope∈{global,scoped}、分类、生效/失效日期、合同类型、审查维度）
  → 条号 exact 短路（命中即直接返回该法条首片，score=1.0）
  → 混合检索：BM25（jieba 分词，正文指纹缓存索引）
              + 向量余弦（仅非空向量，模型/维度匹配校验，阈值 0.35）
  → RRF 融合（k=60，单路召回 Top-30）
  → 合同法域小幅 boost（+0.002）→ 确定性"精排" → 同法条折叠 → Top-K

  降级：embedding 不可用 → 纯 BM25；知识库为空 → 4 条内置关键词规则（reliable=False）

【消费链 · 审查】
audit_contract（法务 Agent 先行 → 共享上下文 → 财务 Agent 二次加工）   auditor.py
  ① 发现阶段：每 Agent 按 4 个主题各 retrieve(top_k=2)，拼 basis_block 进 prompt
  ② 窗口审查：8000 字窗口分页输出候选风险（JSON，quote 必须为原文）
  ③ Grounding：每条风险独立 retrieve(top_k=3)，失败时用改写 query 重试一次
  ④ 证据校验：validate_support_relation（rules-v2，保守规则）
              + 原文子串定位核验 → evidence_status 三态（supported/partially/unsupported）
  ⑤ 二次复核 + 冲突消解 → green/yellow/red 分级归档
```

## 二、做得好的地方（值得保留）

1. **法源治理是生产级思路**：manifest 白名单域名 + SHA-256 + 条号范围/条数三重校验 + 原子替换事务，法源污染风险极低；前端导入用 HMAC 短期令牌绑定文件哈希与用户，越权/掉包面很小。
2. **embedding 签名缓存设计严谨**：`sha256(backend+model+dim+normalization+chunk_schema_version)` 作为复用键，换模型/换维度自动失效重建，避免向量空间混用。
3. **display/retrieval 文本分离**：检索文本带"书名+章节+条号"上下文，展示文本保持原貌，是法律 RAG 的正确实践。
4. **降级链完整且诚实**：embedding 挂→纯 BM25→库空→内置规则；每一级都在 `retrieval_mode`/`reliable` 字段如实标注，内置规则 `reliable=False` 永远不会伪装成"可靠依据"撑起结论。
5. **证据三态 + 人工复核兜底**：`supported/partially/unsupported` 与置信度封顶（70/50）、缺失类风险"正向法条不能证明"的保守规则，责任边界清晰。
6. **作用域默认拒绝**：`scoped` 知识缺目标直接拒绝入库，`unclassified` 不参与检索，方向正确（但见 P1-6 的反作用）。
7. **Prompt 注入防护意识**：system prompt 明确声明合同正文与参考资料为不可信数据。

## 三、问题清单（按严重度分级）

### P0-1　条号精确短路污染 Grounding 检索，依据可能张冠李戴

- 位置：`retriever.py:152-167`（exact 分支）× `auditor.py:720-736`（grounding query 构造）
- 问题：grounding 查询 = `类别 + 合同原文 quote(≤500字) + reason(≤300字)`。合同原文几乎必然包含"第 X 条"（合同**自身**的条款编号），`parse_article_reference` 抽取后进入 exact 分支，直接返回**民法典同号法条**（如合同"第三条"→ 民法典第三条"民事主体的人身权利、财产权利……"），完全绕过混合检索。
- 后果：
  - 绝大多数风险的"检索依据"是语义无关的法条，混合检索在 grounding 阶段实质失效；
  - 兜底校验 `validate_support_relation` 多数会判 `unclear` → 大量风险被打入人工复核（误伤召回）；若巧合出现 2 个二元片段重叠，错误法条会被标记为 `supported` 展示给用户（误导性依据）。
- 建议：exact 短路只应在"查询本身就是条号引用"时触发（如 `query.strip()` 整体匹配条号正则，或仅 lookup/chat 显式查法条场景开启）；grounding 场景禁用该分支，或将 quote 中的合同条款号在构造 query 前剥离。

### P0-2　确定性"精排"实际不排序，trace 记录的是未生效分数

- 位置：`retriever.py:284-291`
- 问题：`rerank_results` 仅在 `scorer is not None`（Cross-Encoder）时执行 `ranked.sort(...)`。生产路径 scorer 恒为 None，`rerank_score`（coverage×0.85 + 精确命中×0.10 + RRF×0.05）只写进 `retrieval_trace`，**返回顺序仍是 RRF/boost 原序**。
- 后果：精排缺失；且遥测字段 `rerank_mode=deterministic_evidence_v1` 会让下游误以为发生过精排，属于误导性观测数据。
- 建议：确定性分支同样按 `rerank_score` 排序，或在 trace 中明示 `ordering: "rrf_passthrough"`。

### P1-3　bge 查询侧缺少检索指令前缀，向量路质量打折

- 位置：`local_embedding.py:71-87`
- 问题：BAAI bge-zh 系列官方要求**查询侧**加指令前缀（"为这个句子生成表示以用于检索相关文章："），文档侧不加。当前 query 与 chunk 同样裸编码。grounding 的 query 又是长达 800+ 字符的拼接文本，与训练分布差距更大。
- 建议：query 侧加前缀（适配器增加 `embed_query()` / `embed_passages()` 区分），入库侧保持不变；或评测后换用 `bge-base-zh-v1.5`。

### P1-4　每次 retrieve 全表扫描 + 全量 JSON 向量解析，扩展性封顶

- 位置：`retriever.py:114-131`、`417-459`
- 问题：一次 retrieve = 全表 SELECT（含每行 384 维向量 JSON 串，约 3-4KB/行）+ 全量文档指纹 SHA-256 + 逐行 `json.loads` 解析向量 + numpy 全量余弦。一次完整审查调用 retrieve 约 `4（主题）+ 2×N（每风险 grounding）` 次，30 条风险 ≈ 64 次全表加载。向量以 JSON TEXT 存储、无任何索引；生产目标 PostgreSQL 却未使用 pgvector。
- 建议：短平快方案——进程内缓存"指纹 → (docs, 向量矩阵)"，指纹命中则跳过加载与解析；中期方案——PostgreSQL + pgvector（或 SQLite + sqlite-vec），SQL 侧完成过滤与 ANN 检索，BM25 保留做混合。

### P1-5　向量相似度阈值 0.35 偏低

- 位置：`retriever.py:43`
- 问题：bge-small-zh 上 0.35 处于语义漂移区，弱相关法条易进入 RRF 融合，叠加 P0-2（精排不生效）会直接影响最终 Top-K。建议以标注集评测后上调至 0.45-0.55，或改相对阈值（Top-1 分数的比例）。

### P1-6　知识导入 API 默认 `scope_mode=unclassified` → 导入即"死数据"

- 位置：`schemas/contract.py:183` × `retriever.py:390-392`
- 问题：`/knowledge/import` 的 `scope_mode` 默认 `unclassified`，而检索过滤器默认拒绝 `unclassified`。前端若不显式传 `global`，业务人员导入的规则/模板**永远不会被检索到**，且无任何告警。需核对前端导入表单是否传了 `scope_mode`；无论结果如何，建议导入响应中回显 `retrievable: false` 警告，或将默认改为 `global`（配合人工确认）。

### P1-7　知识导入的向量化在 HTTP 请求内同步执行

- 位置：`knowledge.py:428-441`（`_do_index`）
- 问题：大文件导入时 `prepare_documents`（全量 embedding）阻塞请求，易触发网关/前端超时；合同批量导入已走 Celery，知识导入没有。建议：超过阈值（如 50 片）转 Celery 任务 + 进度轮询，与合同导入链路对齐。

### P2-8　exact 分支只返回法条首片

- 位置：`retriever.py:160-167`：长法条被切成多片时，exact 仅返回 `chunk_index` 最小的一片，其余片（常含"但书"与第二款）不可达。建议 exact 命中后返回该法条全部片或拼接父法条全文（`LegalArticle.content` 已在 JOIN 中取出却未用于此分支）。

### P2-9　BM25 缓存与指纹成本

- 位置：`retriever.py:561-582`：缓存为进程级全局，uvicorn/Celery 多进程各自持有（可接受）；但 `_docs_fingerprint` 每次调用都对全部文档做 SHA-256，与"缓存就是为了省构建成本"的初衷部分抵消。建议以 `(MAX(id), COUNT(*), 内容版本表)` 之类的廉价信号做粗粒度失效判断。

### P2-10　检索词典未做法律领域适配

- 位置：`retriever.py:628-632`：jieba 默认词典会切碎"不安抗辩权""定金罚则""情势变更"等术语，BM25 路的法条精确匹配优势被削弱。建议加载自定义法律词典（`jieba.load_userdict`）。

### P2-11　内置降级规则仅 4 条

- 位置：`retriever.py:73-94`：知识库为空时审查依据覆盖极低（虽然 `reliable=False` 保证了不会误导）。建议至少覆盖 8 个审查维度各一条，或在运行时明确提示"知识库未初始化"而非静默降级。

## 四、修复优先级建议

| 优先级 | 事项 | 预估影响 |
|---|---|---|
| 立即 | P0-1 限制 exact 短路触发条件 | 直接决定 grounding 依据的正确性 |
| 立即 | P0-2 确定性精排真正生效 | Top-K 质量、trace 可信度 |
| 本周 | P1-6 死数据告警/默认值修正；P1-3 bge query 前缀 | 检索质量与可用性 |
| 迭代内 | P1-4 向量缓存/pgvector；P1-7 导入异步化 | 性能与扩展性 |
| 排期 | P1-5 阈值评测；P2 各项 | 持续优化 |

## 五、验证建议（落地后）

1. 构造 10 份含"第 X 条"编号的合同样本，断言 grounding 的 `evidence_ids` 不再指向与风险语义无关的同号法条（回归 P0-1）。
2. 用 `backend` 现有评测工具跑一轮检索命中率（条号命中率 / Top-3 相关率），对比 bge 前缀与阈值调整前后的差异。
3. 对 `/knowledge/import` 不传 `scope_mode` 的请求断言响应含可见性警告。

---

## 附录：修复状态（2026-09-15，提交 bdfa602）

| 问题 | 状态 | 说明 |
|---|---|---|
| P0-1 条号短路劫持 grounding | ✅ 已修复 | exact 短路限 ≤40 字符显式查询；grounding 传 `allow_exact=False` |
| P0-2 精排不排序 | ✅ 已修复（诚实化） | 保留 RRF 顺序（前一轮刻意决策、测试锁定），trace 新增 `ordering` 字段 |
| P1-3 bge query 前缀 | ✅ 已修复 | `EMBED_QUERY_PREFIX`，仅 local 后端查询侧 |
| P1-6 导入即死数据 | ✅ 已修复 | 导入默认 `global`；响应含 `retrievable`/`scope_warning`；前端展示预警 |
| P1-4 全表扫描/pgvector | ⏳ 待迭代 | 建议进程内矩阵缓存或 pgvector/sqlite-vec |
| P1-5 阈值 0.35 | ⏳ 待评测 | 用检索金标评测模块定档 |
| P1-7 导入同步阻塞 | ⏳ 待迭代 | 大文件转 Celery |
| P2-8~11 | ⏳ 排期 | 详见 progress.md |

测试：新增 13 项回归通过；后端全量 1147 项通过；前端 80 passed / 36 skipped、type-check 通过。实施记录见 `.planning/rag-retrieval-fixes-20260915/progress.md`。
