# 合同审查法律知识库定向增强实施计划

> **执行要求：** 使用 `executing-plans` 按任务顺序实施，每个任务先写失败测试，再做最小实现并单独提交。真实开发库同步属于数据替换操作，必须在 dry-run、备份和用户再次确认后执行。

**目标：** 用权威法源可重复构建合同审查法律知识库，修复合同编条号和孤立切片，并实现父子切片、Embedding 版本治理、精确条号路由与混合检索结果收敛。

**架构：** 新增独立的法源清单、法律条文父表、解析切片服务和原子同步命令。`KnowledgeChunk` 继续作为检索子切片，关联完整法条父记录；通用上传接口复用切片器，但只有受控同步命令可以写入权威法源元数据。检索器先识别明确条号，再执行精确或混合检索，并按父法条归组。

**技术栈：** Python 3、FastAPI、SQLAlchemy、Alembic、SQLite/PostgreSQL、NumPy、jieba、rank-bm25、pytest/unittest。

**设计依据：** `docs/superpowers/specs/2026-09-08-contract-review-legal-knowledge-design.md`

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/resources/legal_sources/manifest.json` | 法源名称、范围、正式网址、版本、日期、文件和哈希清单 |
| `backend/resources/legal_sources/civil-code.txt` | 全国人大正式《民法典》规范化 UTF-8 文本 |
| `backend/resources/legal_sources/contract-interpretation-2023.txt` | 最高法合同编通则司法解释规范化 UTF-8 文本 |
| `backend/app/services/rag/legal_sources.py` | 清单读取、哈希校验、条号规范化、法条解析和自适应父子切片 |
| `backend/scripts/verify_legal_sources.py` | 只读法源完整性校验命令 |
| `backend/app/services/rag/legal_sync.py` | 构建校验、向量复用、原子同步和 dry-run 报告 |
| `backend/scripts/sync_legal_knowledge.py` | 命令行入口，不包含业务规则 |
| `backend/app/models/models.py` | `LegalSource`、`LegalArticle` 和检索子切片关联字段 |
| `backend/app/db/init_db.py` | SQLite 开发环境补列 |
| `backend/alembic/versions/20260908_01_legal_knowledge_sources.py` | PostgreSQL/SQLite 正式迁移 |
| `backend/app/services/rag/retriever.py` | 条号精确路由、Embedding 签名校验和父法条归组 |
| `backend/app/api/v1/endpoints/knowledge.py` | 通用上传复用自适应切片器 |
| `backend/tests/test_legal_sources.py` | 法源、条号、范围和父子切片测试 |
| `backend/tests/test_legal_sync.py` | 原子同步、幂等、回滚和向量复用测试 |
| `backend/tests/test_rag_legal_retrieval.py` | 精确路由、混合检索、归组和降级测试 |

## 任务 1：建立法源与父法条数据模型

**文件：**

- 修改：`backend/app/models/models.py`
- 修改：`backend/app/db/init_db.py`
- 新增：`backend/alembic/versions/20260908_01_legal_knowledge_sources.py`
- 修改：`backend/tests/test_rag_hardening_unittest.py`

1. 在迁移测试中先断言 `legal_sources`、`legal_articles` 表以及 `knowledge_chunks` 新列存在，运行：

   ```powershell
   Set-Location backend
   .\.venv\Scripts\python.exe -m pytest tests/test_rag_hardening_unittest.py -k "alembic or legal_source" -q
   ```

   预期：新表或新列尚不存在，测试失败。

2. 新增 `LegalSource`：`source_id`、`title`、`issuing_authority`、`official_url`、`publication_date`、`effective_date`、`version_status`、`retrieved_at`、`file_sha256`。新增 `LegalArticle`：`id`、`source_id`、`article_number`、`article_sort`、`chapter_title`、`content`、`content_hash`，并建立 `(source_id, article_number)` 唯一约束。

3. 为 `KnowledgeChunk` 增加：

   ```python
   legal_article_id: Mapped[int | None]
   chunk_index: Mapped[int | None]
   chunk_count: Mapped[int | None]
   chunk_schema_version: Mapped[str | None]
   retrieval_text: Mapped[str | None]
   embedding_signature: Mapped[str | None]
   ```

   `legal_article_id` 外键指向 `legal_articles.id`；非权威知识记录允许全部为空。

4. 在 Alembic 迁移和 `_DEV_COLUMNS` 中实现相同结构，升级与降级测试均应通过。运行：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_rag_hardening_unittest.py -k "alembic or legal_source" -q
   ```

5. 单独提交：

   ```powershell
   git add backend/app/models/models.py backend/app/db/init_db.py backend/alembic/versions/20260908_01_legal_knowledge_sources.py backend/tests/test_rag_hardening_unittest.py
   git commit -m "feat: add legal source and article models"
   ```

## 任务 2：实现权威法源清单与法条解析器

**文件：**

- 新增：`backend/app/services/rag/legal_sources.py`
- 新增：`backend/scripts/verify_legal_sources.py`
- 新增：`backend/tests/test_legal_sources.py`
- 新增：`backend/tests/fixtures/legal_sources/sample-law.txt`
- 新增：`backend/tests/fixtures/legal_sources/manifest.json`

1. 先覆盖这些失败场景：源文件缺失、SHA-256 不符、条号重复、范围缺条、范围越界、司法解释条数与清单不一致。

2. 定义不可变数据结构：

   ```python
   @dataclass(frozen=True)
   class SourceSpec:
       source_id: str
       title: str
       issuing_authority: str
       official_url: str
       file: str
       file_sha256: str
       included_ranges: tuple[tuple[int, int], ...]
       expected_article_count: int
       publication_date: date
       effective_date: date
       version_status: str
       retrieved_at: date

   @dataclass(frozen=True)
   class ParsedArticle:
       source_id: str
       article_number: str
       article_sort: int
       chapter_title: str
       content: str
       content_hash: str
   ```

3. 实现 `load_manifest(path)`、`verify_source_file(spec, base_dir)`、`parse_articles(spec, text)` 和 `validate_article_set(spec, articles)`。条号正则只识别行首“第 X 条”，并支持中文数字、阿拉伯数字和“条之一”。`verify_legal_sources.py --manifest PATH` 依次调用这些纯函数，只输出校验报告，不连接数据库。

4. 运行：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_legal_sources.py -q
   ```

   预期：所有法源校验与解析测试通过。

5. 提交：

   ```powershell
   git add backend/app/services/rag/legal_sources.py backend/scripts/verify_legal_sources.py backend/tests/test_legal_sources.py backend/tests/fixtures/legal_sources
   git commit -m "feat: validate and parse authoritative legal sources"
   ```

## 任务 3：实现法条父子切片

**文件：**

- 修改：`backend/app/services/rag/legal_sources.py`
- 修改：`backend/tests/test_legal_sources.py`
- 修改：`backend/app/api/v1/endpoints/knowledge.py`
- 修改：`backend/tests/test_knowledge_split.py`

1. 先增加第 511 条结构化夹具，断言：短条文只有一个子切片；长条文先按款、再按项切分；每个子切片继承条号、父记录键、序号和总数；任一切片不超过 380 字；无法识别结构时才按句界和字符降级。

2. 实现：

   ```python
   @dataclass(frozen=True)
   class LegalChunk:
       article_key: tuple[str, str]
       article_number: str
       chunk_index: int
       chunk_count: int
       display_content: str
       retrieval_text: str
       chunk_schema_version: str = "legal-v1"
   ```

   `retrieval_text` 由规范名称、编章标题、条号和子切片正文组成；`display_content` 只保存正式原文。通用上传的 `_smart_split` 调用同一低层切片函数，避免两套规则漂移。

3. 运行：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_legal_sources.py tests/test_knowledge_split.py -q
   ```

4. 提交：

   ```powershell
   git add backend/app/services/rag/legal_sources.py backend/app/api/v1/endpoints/knowledge.py backend/tests/test_legal_sources.py backend/tests/test_knowledge_split.py
   git commit -m "feat: add article-aware parent child chunking"
   ```

## 任务 4：纳入并核验正式法源文本

**文件：**

- 新增：`backend/resources/legal_sources/manifest.json`
- 新增：`backend/resources/legal_sources/civil-code.txt`
- 新增：`backend/resources/legal_sources/contract-interpretation-2023.txt`

1. 从以下正式页面取得原文，不接受第三方转载：

   - 《民法典》：`https://flk.npc.gov.cn/detail?title=%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E6%B0%91%E6%B3%95%E5%85%B8&id=ff808081729d1efe01729d50b5c500bf`
   - 合同编通则司法解释：`http://gongbao.court.gov.cn/Details/f4722cf61c92a585f04b2ecd334f5b.html`

2. 规范化时只移除网页导航、页眉页脚和空白噪声，不改写条文。`civil-code.txt` 保留完整正式文本，由清单的 `included_ranges` 选择第 1—204、386—457、463—988 条；司法解释收录全文。

3. 计算文件哈希并写入清单：

   ```powershell
   Get-FileHash -Algorithm SHA256 backend/resources/legal_sources/civil-code.txt
   Get-FileHash -Algorithm SHA256 backend/resources/legal_sources/contract-interpretation-2023.txt
   ```

4. 运行正式法源校验：

   ```powershell
   Set-Location backend
   .\.venv\Scripts\python.exe -m pytest tests/test_legal_sources.py -q
   .\.venv\Scripts\python.exe scripts/verify_legal_sources.py --manifest resources/legal_sources/manifest.json
   ```

   预期报告：总则 204 条、担保物权 72 条、合同编 526 条；司法解释条数与清单一致；哈希、重复和缺条检查全部通过。

5. 人工抽查每个文件的首条、末条和至少 5 个随机条文，与正式页面逐字核对后提交：

   ```powershell
   git add backend/resources/legal_sources
   git commit -m "data: add verified contract review legal sources"
   ```

## 任务 5：实现 Embedding 签名、批校验与安全复用

**文件：**

- 修改：`backend/app/services/rag/retriever.py`
- 新增：`backend/tests/test_legal_sync.py`

1. 先写测试证明以下行为：Embedding 输入使用 `retrieval_text`；数量、空值、NaN、无穷值和维度异常均拒绝；签名由后端、模型、维度、归一化方式和切片版本决定；内容哈希与签名相同时复用向量，任一变化时重建。

2. 新增纯函数：

   ```python
   def embedding_signature(*, backend: str, model: str, dimension: int,
                           normalization: str, chunk_schema_version: str) -> str:
       payload = {"backend": backend, "model": model, "dimension": dimension,
                  "normalization": normalization,
                  "chunk_schema_version": chunk_schema_version}
       return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
   ```

3. 扩展 `prepare_documents`，允许传入 `retrieval_text` 和已验证的缓存向量；缓存键固定为 `(content_hash, embedding_signature)`，不得仅按条号复用。

4. 运行：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_legal_sync.py tests/test_rag_hardening_unittest.py -q
   ```

5. 提交：

   ```powershell
   git add backend/app/services/rag/retriever.py backend/tests/test_legal_sync.py
   git commit -m "feat: version and reuse legal knowledge embeddings"
   ```

## 任务 6：实现 dry-run 与原子同步命令

**文件：**

- 新增：`backend/app/services/rag/legal_sync.py`
- 新增：`backend/scripts/sync_legal_knowledge.py`
- 修改：`backend/tests/test_legal_sync.py`

1. 使用内存 SQLite 先写失败测试：空库首次同步、重复同步幂等、法源变更仅替换对应来源、解析失败不删旧数据、Embedding 失败不删旧数据、非权威规则/模板/案例不受影响、旧来源名 `民法典-合同编.txt` 只在显式 `--replace-legacy` 时替换。

2. 命令行接口固定为：

   ```text
   sync_legal_knowledge.py --manifest PATH --check-only
   sync_legal_knowledge.py --manifest PATH --dry-run [--replace-legacy]
   sync_legal_knowledge.py --manifest PATH --apply [--replace-legacy]
   ```

   `--dry-run` 输出新增、更新、删除、复用向量、重建向量、逻辑法条和子切片数量，不执行写操作。`--apply` 在解析和向量全部成功后开启单一事务，先 upsert 法源和父法条，再替换对应检索子切片。

3. 运行：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_legal_sync.py -q
   .\.venv\Scripts\python.exe scripts/sync_legal_knowledge.py --manifest resources/legal_sources/manifest.json --dry-run --replace-legacy
   ```

4. 提交：

   ```powershell
   git add backend/app/services/rag/legal_sync.py backend/scripts/sync_legal_knowledge.py backend/tests/test_legal_sync.py
   git commit -m "feat: add atomic legal knowledge synchronization"
   ```

## 任务 7：实现条号路由和父法条结果收敛

**文件：**

- 修改：`backend/app/services/rag/retriever.py`
- 新增：`backend/tests/test_rag_legal_retrieval.py`
- 修改：`backend/tests/test_rag_hybrid.py`

1. 先写测试：`民法典第五百八十五条`、`第585条` 和 `585条` 均规范化到“第五百八十五条”；明确条号优先精确结果；自然语言仍走 RRF；同一父法条多个子切片只占一个 Top-K 位置；向量不可用时结果标记为 `bm25`；旧的无父记录知识仍可检索。

2. 实现 `parse_article_reference(query)` 和 `collapse_by_article(results)`。精确路由必须同时受分类、有效期和作用域过滤约束，不得绕过 `_filter_docs`。

3. 检索结果保持现有字段，并增加：

   ```python
   {
       "matched_content": "命中的子切片原文",
       "content": "完整父法条原文",
       "legal_article_id": 123,
       "chunk_index": 1,
       "chunk_count": 2,
   }
   ```

   无父记录的旧知识令 `matched_content == content`，新增字段允许为空，保证审查服务兼容。

4. 运行：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_rag_legal_retrieval.py tests/test_rag_hybrid.py tests/test_audit_evidence.py tests/test_rag_grounding.py -q
   ```

5. 提交：

   ```powershell
   git add backend/app/services/rag/retriever.py backend/tests/test_rag_legal_retrieval.py backend/tests/test_rag_hybrid.py
   git commit -m "feat: route and collapse legal article retrieval"
   ```

## 任务 8：修复开发库并完成验收

**文件：**

- 修改：`PROGRESS.md`，仅记录实际执行证据
- 生成：`outputs/legal-knowledge-sync/`，保持在忽略列表中

1. 运行完整后端测试和质量门禁：

   ```powershell
   Set-Location backend
   .\.venv\Scripts\python.exe -m pytest -q
   Set-Location ..
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
   ```

2. 对当前开发库执行 dry-run，将报告保存到 `outputs/legal-knowledge-sync/dry-run.json`。核对目标仅包含受控法源和旧的 `民法典-合同编.txt`，不得包含规则、模板、案例或用户数据。

3. 在执行真实替换前，向用户报告：数据库绝对路径、备份路径、预计新增/更新/删除数量和是否需要重新生成向量，并取得明确确认。

4. 确认后复制数据库为带时间戳的备份，再执行：

   ```powershell
   Set-Location backend
   .\.venv\Scripts\python.exe scripts/sync_legal_knowledge.py --manifest resources/legal_sources/manifest.json --apply --replace-legacy
   ```

5. 使用只读验收查询和检索测试确认：合同编 526 条、总则 204 条、担保物权 72 条、司法解释条数与清单一致；法律子切片条号非空率 100%；第 511 条全部子切片指向同一父法条；向量签名一致；精确条号与典型自然语言查询均命中正确条文。

6. 只把新鲜验证结果写入 `PROGRESS.md`。不得写成“整部民法典 1260 条已收录”，不得把开发库结果表述为正式比赛环境实测。

7. 最终运行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
   git status --short
   ```

   预期：质量门禁退出码 0；工作区只保留实施前已存在且未纳入本任务的用户改动。
