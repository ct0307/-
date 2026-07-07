"""合规审查：核心业务，多智能体协同编排。

对应前端原型的"法务 Agent 查合规 + 财务 Agent 对账目"双泳道协同：
按角色分维度审查，各自带定向 RAG 依据独立调 LLM，结果打 agent 标签汇总成一份报告。

流程：合同要素 + 分角色 RAG 依据 → 各 Agent LLM 出结构化风险 → 汇总。
每条风险包含（企业责任边界要求）：
  - 归属 agent（legal/finance）
  - 原文引用（original_text）
  - 依据来源（basis，来自 RAG 检索的法规/规则）
  - 风险等级（level: high/medium/low）
  - 置信度（confidence: 0-100）
  - 建议修改（suggestion）

真实版每个 Agent 走 LLM chat；某 Agent 不可用或返回无法解析时，仅该角色降级到
对应 Mock 规则（另一角色不受影响），保证审查链路始终可用 —— 企业可用性刚需。
所有结论统一标注"仅供参考，以人工复核为准"。
"""
import json
import re

from app.core.logging import get_logger
from app.llm.base import LLMError
from app.llm.factory import get_llm_adapter
from app.services.rag.retriever import retrieve

log = get_logger("audit")

DISCLAIMER = "本结论由系统自动生成，仅供参考，以人工复核为准。"

_VALID_LEVELS = {"high", "medium", "low"}

# 智能体定义：角色 → 关注维度 + 定向 RAG 检索主题 + 角色化 prompt 侧重。
# 与前端原型规则库的 agent 分派（legal/finance）一致。
_AGENTS = {
    "legal": {
        "name": "法务专家 Agent",
        "focus": "违约责任、争议解决、知识产权归属、保密条款、验收标准、合同主体资格",
        "topics": ["违约 违约责任 违约金", "争议 仲裁 诉讼 管辖", "知识产权 著作权 保密", "合同主体 甲方 乙方"],
    },
    "finance": {
        "name": "财务会计 Agent",
        "focus": "合同金额、付款节点、发票绑定、违约金上限、币种与大小写一致性、预算合规",
        "topics": ["金额 价款 币种", "付款 发票 结算", "违约金 上限 赔偿", "期限 履约"],
    },
}


def audit_contract(elements: dict, contract_text: str) -> list[dict]:
    """多智能体协同审查：法务 + 财务 Agent 各出风险，汇总返回。

    每个 Agent 优先 LLM；不可用或解析失败仅该角色降级到 Mock（不影响另一角色）。
    """
    all_risks: list[dict] = []
    for role in _AGENTS:
        try:
            risks = _agent_audit(role, elements, contract_text)
            log.info("audit.agent_done", agent=role, mode="llm", risk_count=len(risks))
        except (LLMError, ValueError) as exc:
            log.warning("audit.agent_fallback", agent=role, error=str(exc)[:120])
            risks = _mock_audit(role, elements)
            log.info("audit.agent_done", agent=role, mode="mock", risk_count=len(risks))
        all_risks.extend(risks)
    log.info("audit.done", total=len(all_risks), agents=list(_AGENTS))
    return all_risks


def _agent_audit(role: str, elements: dict, contract_text: str) -> list[dict]:
    """单个 Agent 审查：定向 RAG 依据 + 角色 prompt → chat → 解析，打 agent 标签。"""
    cfg = _AGENTS[role]

    # 该角色关注维度的定向 RAG 依据
    seen: set[str] = set()
    basis_lines: list[str] = []
    for topic in cfg["topics"]:
        for item in retrieve(topic, top_k=2):
            key = item["source"] + item["content"][:20]
            if key not in seen:
                seen.add(key)
                basis_lines.append(f"- {item['content']}（依据：{item['source']}）")
    basis_block = "\n".join(basis_lines) if basis_lines else "（无检索到的依据，请基于通用合同合规常识判断并说明）"

    system_prompt = (
        f"你是{cfg['name']}，专门从以下维度审查企业合同的合规风险：{cfg['focus']}。\n"
        "严格遵守：\n"
        "1. 只依据给定资料判断，禁止编造法规或依据；\n"
        "2. 只输出属于你职责维度的风险，不越界评价其他维度；\n"
        "3. 每条风险必须给出原文引用、依据来源、风险等级、修改建议、置信度；\n"
        "4. 输出严格的 JSON 数组，不要输出任何解释性文字或 Markdown；\n"
        "5. 数组每个元素字段：level(取值 high/medium/low)、category(风险类别)、"
        "original_text(合同中的相关原文或'（全文未检出）')、basis(依据来源)、"
        "suggestion(修改建议)、confidence(0-100 的整数置信度)。\n"
        "结论仅供参考，最终以人工复核为准。"
    )
    user_prompt = (
        f"【给定的法规/规则依据】\n{basis_block}\n\n"
        f"【已抽取的合同要素】\n{json.dumps({k: v for k, v in elements.items() if not k.startswith('has_')}, ensure_ascii=False)}\n\n"
        f"【合同全文】\n{contract_text[:8000]}\n\n"
        f"请以{cfg['name']}的视角，输出 JSON 数组形式的风险清单。"
    )

    adapter = get_llm_adapter()
    resp = adapter.chat(system_prompt, user_prompt)
    raw = _parse_risk_json(resp.text)
    return [_normalize(r, role) for r in raw]


def _parse_risk_json(text: str) -> list[dict]:
    """从 LLM 文本中提取 JSON 数组，容错代码块围栏与前后噪声。"""
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM 输出未找到 JSON 数组")
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, list):
        raise ValueError("LLM 输出不是 JSON 数组")
    return data


def _normalize(r: dict, agent: str) -> dict:
    """规范化单条风险：字段缺省填默认，取值越界裁剪，打 agent 标签，附免责声明。"""
    level = str(r.get("level", "medium")).lower()
    if level not in _VALID_LEVELS:
        level = "medium"
    try:
        confidence = max(0, min(100, int(r.get("confidence", 60))))
    except (TypeError, ValueError):
        confidence = 60
    return {
        "agent": agent,
        "level": level,
        "category": str(r.get("category", "合规风险"))[:64],
        "original_text": str(r.get("original_text", "")),
        "basis": str(r.get("basis", "（无匹配依据）")),
        "suggestion": str(r.get("suggestion", "")),
        "confidence": confidence,
        "disclaimer": DISCLAIMER,
    }


# 各角色的 Mock 降级规则：(判定函数, 风险模板)。判定为真则命中该风险。
def _mock_audit(role: str, elements: dict) -> list[dict]:
    """角色化 Mock 降级：仅产出该 Agent 职责维度的规则风险。"""
    risks: list[dict] = []

    if role == "legal":
        if not elements.get("has_breach_clause"):
            risks.append(_risk(
                agent="legal", level="high", category="条款缺失",
                original_text="（全文未检出违约责任相关条款）",
                basis=retrieve("违约 违约责任 违约金"),
                suggestion="建议补充违约责任条款，明确违约情形、违约金计算方式及赔偿范围。",
                confidence=88,
            ))
        if not elements.get("has_dispute_clause"):
            risks.append(_risk(
                agent="legal", level="medium", category="条款缺失",
                original_text="（全文未检出争议解决条款）",
                basis=retrieve("争议 仲裁 诉讼 管辖"),
                suggestion="建议增加争议解决条款，明确仲裁机构或诉讼管辖法院。",
                confidence=82,
            ))
        if not elements.get("party_a") or not elements.get("party_b"):
            risks.append(_risk(
                agent="legal", level="high", category="主体缺失",
                original_text="（甲方或乙方主体信息不完整）",
                basis=[{"content": "合同主体应完整明确，否则可能影响合同效力。", "source": "合同主体条款标准", "score": 1}],
                suggestion="建议核对并补全甲乙双方的名称及主体资格信息。",
                confidence=90,
            ))

    elif role == "finance":
        if not elements.get("amount"):
            risks.append(_risk(
                agent="finance", level="high", category="要素缺失",
                original_text="（未检出明确的合同金额）",
                basis=retrieve("金额 价款 人民币"),
                suggestion="建议明确合同金额，大小写一致并标注币种。",
                confidence=85,
            ))
        if not elements.get("sign_date"):
            risks.append(_risk(
                agent="finance", level="low", category="要素缺失",
                original_text="（未检出签订日期）",
                basis=retrieve("期限 履约"),
                suggestion="建议补充合同签订日期，作为生效与期限计算的起点。",
                confidence=70,
            ))

    return risks


def _risk(*, agent: str, level: str, category: str, original_text: str, basis: list[dict], suggestion: str, confidence: int) -> dict:
    """组装单条风险为统一结构。basis 拼成可读的依据来源字符串。"""
    basis_text = "；".join(f"{b['content']}（依据：{b['source']}）" for b in basis) if basis else "（无匹配依据）"
    return {
        "agent": agent,
        "level": level,
        "category": category,
        "original_text": original_text,
        "basis": basis_text,
        "suggestion": suggestion,
        "confidence": confidence,
        "disclaimer": DISCLAIMER,
    }
