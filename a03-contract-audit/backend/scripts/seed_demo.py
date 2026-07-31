"""演示数据 seed 脚本：幂等可重跑，为 Dashboard/Reports/Knowledge 灌基线数据。

用法（backend 目录下）：
    python -m scripts.seed_demo

设计要点：
- 幂等：以 filename / (source+content) 为哨兵判重，已存在则跳过，可安全重跑。
- 覆盖面：~12 份合同（4 部门）+ 每份 2~4 条风险（high/medium/low × legal/finance ×
  各 review_status × 各 tier）+ 12 条知识库切片（四类 category）。
- 绕开 embedding：DeepSeek 无 embedding 端点，知识库切片直接写 embedding=""，
  RAG 走已有关键词降级检索。
- category 中英映射：law→法律法规、template→标准条款、rule→风险规则、case→典型案例。
"""
import json
import os
import sys

# 允许 `python scripts/seed_demo.py` 直接跑（把 backend 加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.models import (
    AccessRole, AuditRule, Contract, ContractTemplate,
    KnowledgeChunk, LLMCallLog, LookupItem, Rectification, Risk, User,
)
from app.services.rag.retriever import controlled_seed_scope
from sqlalchemy.orm import Session


log = get_logger("seed")


# ── 合同：12 份，覆盖 4 部门与多种合同类型 ──────────────────────────
# (filename, contract_type, department, status)
_CONTRACTS = [
    ("2026年度办公用品采购框架合同.pdf", "采购合同", "采购中心", "done"),
    ("XX园区安防设备采购合同.pdf", "采购合同", "采购中心", "done"),
    ("原材料供应长期协议.docx", "采购合同", "采购中心", "auditing"),
    ("智能巡检系统软件外包开发合同.pdf", "技术开发合同", "研发外包部", "done"),
    ("移动端App定制开发协议.docx", "技术开发合同", "研发外包部", "done"),
    ("算法模型联合研发合作合同.pdf", "合作合同", "研发外包部", "parsed"),
    ("品牌年度推广服务合同.pdf", "服务合同", "市场运营部", "done"),
    ("线上渠道代运营合作协议.docx", "服务合同", "市场运营部", "done"),
    ("会展活动策划执行合同.pdf", "服务合同", "市场运营部", "auditing"),
    ("办公场地租赁合同.pdf", "租赁合同", "行政人事部", "done"),
    ("劳务派遣服务协议.docx", "劳务合同", "行政人事部", "done"),
    ("员工商业保险采购合同.pdf", "采购合同", "行政人事部", "uploaded"),
]

# ── 风险：按合同 filename 分组，覆盖各维度组合 ─────────────────────
# level: high/medium/low  agent: legal/finance  tier: green/yellow/red
# review_status: pending/confirmed/ignored/to_modify
_RISKS = {
    "2026年度办公用品采购框架合同.pdf": [
        dict(level="high", category="付款条款", agent="finance",
             original_text="乙方交货后，甲方于收到货物后 90 日内付款。",
             basis="风险规则：付款周期超过 60 日显著偏离行业惯例，占用供方资金。",
             suggestion="建议将付款周期缩短至 30 日内，或约定分期付款节点。",
             confidence=88, tier="red", review_status="confirmed"),
        dict(level="medium", category="金额币种", agent="finance",
             original_text="合同总金额人民币壹佰贰拾万元。",
             basis="风险规则 K05：合同金额应大小写一致并明确标注币种。",
             suggestion="补充阿拉伯数字金额 ¥1,200,000.00，确保大小写一致。",
             confidence=76, tier="yellow", review_status="to_modify"),
        dict(level="low", category="争议解决", agent="legal",
             original_text="因本合同产生争议由双方协商解决。",
             basis="标准条款 K04：争议解决条款应明确管辖法院或仲裁机构。",
             suggestion="补充协商不成时提交合同签订地人民法院诉讼。",
             confidence=70, tier="green", review_status="ignored"),
    ],
    "XX园区安防设备采购合同.pdf": [
        dict(level="high", category="质保责任", agent="legal",
             original_text="设备质保期为壹年，质保期外故障维修另行收费。",
             basis="风险规则：安防设备质保期短于行业通行 3 年标准。",
             suggestion="建议将质保期延长至 3 年，并明确质保范围与响应时限。",
             confidence=82, tier="red", review_status="pending"),
        dict(level="medium", category="验收标准", agent="legal",
             original_text="设备安装完成即视为验收合格。",
             basis="典型案例 K08：验收标准模糊易引发履约纠纷。",
             suggestion="约定验收标准、验收期限及不合格处理方式。",
             confidence=74, tier="yellow", review_status="confirmed"),
    ],
    "原材料供应长期协议.docx": [
        dict(level="medium", category="价格调整", agent="finance",
             original_text="原材料价格随市场波动，由供方每季度通知调整。",
             basis="风险规则：单方定价条款加重采购方成本不确定性。",
             suggestion="约定价格调整上限、调整依据及双方确认机制。",
             confidence=79, tier="yellow", review_status="pending"),
        dict(level="low", category="保密条款", agent="legal",
             original_text="双方应对合作信息保密。",
             basis="标准条款 K09：保密义务应明确范围与期限。",
             suggestion="补充保密信息范围及自合同终止起 3 年的保密期限。",
             confidence=68, tier="green", review_status="pending"),
    ],
    "智能巡检系统软件外包开发合同.pdf": [
        dict(level="high", category="知识产权", agent="legal",
             original_text="开发成果的知识产权归属双方另行协商。",
             basis="典型案例 K07：未约定知识产权归属，委托方存在败诉风险。",
             suggestion="明确开发成果知识产权归委托方所有，受托方不得擅自使用。",
             confidence=91, tier="red", review_status="confirmed"),
        dict(level="medium", category="验收付款", agent="finance",
             original_text="项目验收后一次性支付全部开发费用。",
             basis="风险规则：一次性付款不利于风险分摊与进度约束。",
             suggestion="建议按里程碑分期付款，预留质保金。",
             confidence=77, tier="yellow", review_status="to_modify"),
        dict(level="low", category="违约责任", agent="legal",
             original_text="任何一方违约应承担违约责任。",
             basis="标准条款 K03：违约责任应量化违约金标准。",
             suggestion="约定违约金为合同总金额的 20% 及损失赔偿。",
             confidence=65, tier="green", review_status="pending"),
    ],
    "移动端App定制开发协议.docx": [
        dict(level="high", category="源码交付", agent="legal",
             original_text="项目完成后交付可运行程序。",
             basis="风险规则：未约定源代码交付，后续维护受制于受托方。",
             suggestion="明确交付含完整源代码、文档及部署说明。",
             confidence=85, tier="red", review_status="pending"),
        dict(level="medium", category="维护服务", agent="legal",
             original_text="免费维护期一个月。",
             basis="典型案例：维护期过短导致上线后问题无保障。",
             suggestion="建议延长免费维护期至 6~12 个月，并约定响应时限。",
             confidence=72, tier="yellow", review_status="ignored"),
    ],
    "算法模型联合研发合作合同.pdf": [
        dict(level="medium", category="成果分配", agent="legal",
             original_text="研发成果由双方共享。",
             basis="风险规则：共享表述模糊，未明确使用与转让权利边界。",
             suggestion="约定成果的所有权、使用权、转让权及收益分配比例。",
             confidence=73, tier="yellow", review_status="pending"),
    ],
    "品牌年度推广服务合同.pdf": [
        dict(level="high", category="关联交易", agent="finance",
             original_text="推广服务由甲方关联公司 XX 传媒承接，服务费按年度结算。",
             basis="风险规则：关联交易需复查价格公允性，防范利益输送。",
             suggestion="要求提供市场比价，说明定价公允性并履行关联交易审批。",
             confidence=86, tier="red", review_status="confirmed"),
        dict(level="medium", category="效果考核", agent="finance",
             original_text="推广效果以甲方满意为准。",
             basis="典型案例：主观验收标准易引发付款争议。",
             suggestion="约定可量化的推广效果指标（曝光量、转化率等）作为考核依据。",
             confidence=75, tier="yellow", review_status="pending"),
    ],
    "线上渠道代运营合作协议.docx": [
        dict(level="medium", category="收款账户", agent="finance",
             original_text="服务费汇入乙方指定账户，账户信息以邮件通知为准。",
             basis="风险规则：收款账户以邮件变更存在诈骗与资金安全风险。",
             suggestion="收款账户须在合同中固定，变更需书面盖章确认。",
             confidence=80, tier="yellow", review_status="to_modify"),
        dict(level="low", category="合同期限", agent="legal",
             original_text="合作期限一年，到期自动续约。",
             basis="标准条款：自动续约应约定通知期与退出机制。",
             suggestion="补充续约前 30 日书面确认及任一方退出条款。",
             confidence=66, tier="green", review_status="ignored"),
    ],
    "会展活动策划执行合同.pdf": [
        dict(level="medium", category="不可抗力", agent="legal",
             original_text="因不可抗力无法举办的，已付费用不予退还。",
             basis="民法典 K10：不可抗力免责但不应免除返还义务。",
             suggestion="约定不可抗力时按实际发生费用结算，剩余款项退还。",
             confidence=78, tier="yellow", review_status="pending"),
    ],
    "办公场地租赁合同.pdf": [
        dict(level="high", category="押金退还", agent="finance",
             original_text="租赁期满，押金是否退还由甲方决定。",
             basis="风险规则：押金退还应无条件，单方决定权显失公平。",
             suggestion="约定无违约情形下租期届满全额退还押金及退还时限。",
             confidence=84, tier="red", review_status="confirmed"),
        dict(level="low", category="租金递增", agent="finance",
             original_text="租金每年递增 5%。",
             basis="风险规则：租金递增幅度需评估市场合理性。",
             suggestion="确认递增幅度符合区域市场水平，或约定递增上限。",
             confidence=64, tier="green", review_status="pending"),
    ],
    "劳务派遣服务协议.docx": [
        dict(level="high", category="用工责任", agent="legal",
             original_text="派遣人员工伤由用工单位自行处理。",
             basis="风险规则：违反劳务派遣工伤责任由用人单位承担的规定。",
             suggestion="明确工伤责任按《劳动合同法》由派遣单位承担，用工单位配合。",
             confidence=89, tier="red", review_status="pending"),
        dict(level="medium", category="费用结算", agent="finance",
             original_text="服务费含派遣人员工资及社保，按月结算。",
             basis="风险规则：费用构成应明细，防范社保缴纳合规风险。",
             suggestion="要求提供工资与社保缴纳明细，确保合规缴纳。",
             confidence=76, tier="yellow", review_status="confirmed"),
    ],
    "员工商业保险采购合同.pdf": [
        dict(level="low", category="理赔条款", agent="legal",
             original_text="理赔按保险公司条款执行。",
             basis="典型案例：直接援引保险条款而未审查免责范围存在盲区。",
             suggestion="审查保险条款免责范围，确认覆盖企业实际需求。",
             confidence=62, tier="green", review_status="pending"),
    ],
}

# ── 知识库切片：12 条，四类 category，对齐前端 knowledge.ts ──────────
# (category, source, content)  category ∈ law/template/rule/case
_KNOWLEDGE = [
    ("law", "《民法典》第577条", "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。"),
    ("law", "《民法典》第502条", "依法成立的合同，自成立时生效，但是法律另有规定或者当事人另有约定的除外。"),
    ("template", "违约金标准条款范本", "任何一方违反本合同约定，应向守约方支付合同总金额 20% 的违约金；给守约方造成损失的，还应赔偿全部损失。"),
    ("template", "争议解决标准条款范本", "因本合同引起的或与本合同有关的任何争议，双方应友好协商解决；协商不成的，提交合同签订地人民法院诉讼解决。"),
    ("rule", "合同金额币种标注规则", "合同金额应大小写一致并明确标注币种，避免因金额或币种不清引发争议。命中缺失即判中风险。"),
    ("rule", "主体资格完整性校验规则", "合同应完整明确甲乙双方名称及主体资格信息，主体缺失可能影响合同效力，判高风险。"),
    ("case", "软件外包合同知识产权归属案例", "某软件外包纠纷中，因合同未约定开发成果知识产权归属，法院最终判定归受托方所有，委托方败诉。"),
    ("case", "采购合同付款节点纠纷案例", "某采购合同因付款节点约定模糊，供方主张逾期付款违约金未获支持，提示付款条款须明确时间与条件。"),
    ("template", "保密条款标准范本", "双方对因履行本合同知悉的对方商业秘密负有保密义务，保密期限自合同终止之日起 3 年。"),
    ("law", "《民法典》第563条", "有下列情形之一的，当事人可以解除合同：因不可抗力致使不能实现合同目的；一方迟延履行主要债务经催告后仍未履行等。"),
    ("template", "知识产权归属标准条款", "本合同项下开发成果的知识产权归委托方所有，受托方不得擅自使用、转让或披露。"),
    ("rule", "格式条款效力认定规则", "提供格式条款一方免除自身责任、加重对方责任、限制对方主要权利的，该格式条款无效，判高风险提示。"),
]


# ── 整改项：从已确认（confirmed）风险派生，贴合真实闭环语义 ────────────
# (合同名, 风险描述, level, 责任人, status, created, due, note)
_RECTIFICATIONS = [
    ("2026年度办公用品采购框架合同.pdf", "付款条款", "high", "陈嘉禾", "处理中",
     "2026-07-02", "2026-07-10", "已联系采购中心，拟将付款周期由 90 日缩短至 30 日，待供方确认。"),
    ("智能巡检系统软件外包开发合同.pdf", "知识产权", "high", "曾庆豪", "已闭环",
     "2026-06-28", "2026-07-05", "补充条款已明确开发成果知识产权归委托方所有，双方已盖章。"),
    ("品牌年度推广服务合同.pdf", "关联交易", "high", "陈嘉禾", "待处理",
     "2026-07-04", "2026-07-12", "要求关联方提供市场比价材料，履行关联交易审批流程。"),
    ("办公场地租赁合同.pdf", "押金退还", "high", "王督政", "处理中",
     "2026-07-03", "2026-07-11", "已拟定押金无条件退还及退还时限补充协议，待业主签署。"),
    ("XX园区安防设备采购合同.pdf", "验收标准", "medium", "曾庆豪", "已闭环",
     "2026-06-30", "2026-07-07", "已约定验收标准、验收期限及不合格处理方式，条款补充完成。"),
    ("劳务派遣服务协议.docx", "费用结算", "medium", "陈嘉禾", "待处理",
     "2026-07-05", "2026-07-13", "要求派遣单位提供工资与社保缴纳明细，核验合规性。"),
]


def seed_rectifications(db) -> int:
    added = 0
    for contract, risk, level, owner, status, created, due, note in _RECTIFICATIONS:
        exists = (
            db.query(Rectification)
            .filter(Rectification.contract == contract, Rectification.risk == risk)
            .first()
        )
        if exists:
            continue
        db.add(Rectification(
            contract=contract, risk=risk, level=level, owner=owner,
            status=status, created=created, due=due, note=note,
        ))
        added += 1
    db.commit()
    return added


# ── 审查规则：6 条，对齐 mock/rules.ts AUDIT_RULES ─────────────────────
# (name, dimension, level, agent, desc, builtin)
_AUDIT_RULES = [
    ("违约责任缺失检测", "违约责任分析", "high", "法务 Agent",
     "全文未检出违约责任相关条款时，判高风险并提示补充。", True),
    ("争议解决条款检测", "争议解决条款", "medium", "法务 Agent",
     "未约定仲裁或诉讼管辖时，判中风险。", True),
    ("合同金额币种校验", "金额与付款条款", "high", "财务 Agent",
     "金额缺失或未标注币种时判高风险。", True),
    ("签订日期完整性", "法律条款合规性", "low", "法务 Agent",
     "未检出签订日期时判低风险，提示补充。", True),
    ("主体资格完整性", "风险条款识别", "high", "法务 Agent",
     "甲乙方主体信息不完整时判高风险。", True),
    ("保密条款审查", "保密条款审查", "medium", "法务 Agent",
     "涉及商业秘密但无保密条款时判中风险。", False),
]

# ── 合同模板：3 份，对齐 mock/rules.ts CONTRACT_TEMPLATES ──────────────
# (name, type, clauses, builtin)
_CONTRACT_TEMPLATES = [
    ("软件开发外包合同模板", "软件开发外包合同",
     ["甲乙双方主体信息", "开发范围与交付标准", "知识产权归属", "付款节点与方式",
      "违约责任", "保密条款", "争议解决"], True),
    ("采购合同模板", "采购合同",
     ["货物名称规格数量", "合同金额与币种", "交付与验收", "付款条款",
      "质量保证", "违约责任", "争议解决"], True),
    ("技术服务合同模板", "技术服务合同",
     ["服务内容与标准", "服务期限", "服务费用", "知识产权", "保密义务", "违约责任"], False),
]

# ── 权限矩阵：4 角色 × 7 模块 ─────────────────────────────────────────
# 7模块顺序（与 admin.py 端点固定顺序一致）：
_MODULES = ['工作台', '合同审查', '整改跟踪', '多维报表', '法规知识库', '规则与模板', '权限与审计']
_ACCESS_ROLES = [
    ("business", "业务人员", ["只读", "读写", "只读", "只读", "只读", "无", "无"]),
    ("legal",    "法务人员", ["只读", "读写", "读写", "只读", "读写", "只读", "无"]),
    ("finance",  "财务人员", ["只读", "读写", "读写", "读写", "只读", "无",   "无"]),
    ("admin",    "管理员",   ["读写", "读写", "读写", "读写", "读写", "读写", "读写"]),
]


def seed_rules_and_templates(db) -> tuple[int, int]:
    import json as _json
    added_r = added_t = 0
    for name, dim, level, agent, desc, builtin in _AUDIT_RULES:
        if not db.query(AuditRule).filter(AuditRule.name == name).first():
            db.add(AuditRule(name=name, dimension=dim, level=level,
                             agent=agent, desc=desc, builtin=int(builtin)))
            added_r += 1
    for name, tp, clauses, builtin in _CONTRACT_TEMPLATES:
        if not db.query(ContractTemplate).filter(ContractTemplate.name == name).first():
            db.add(ContractTemplate(name=name, type=tp,
                                    clauses=_json.dumps(clauses, ensure_ascii=False),
                                    builtin=int(builtin)))
            added_t += 1
    db.commit()
    return added_r, added_t


def seed_access_roles(db) -> int:
    import json as _json
    added = 0
    for key, label, perms in _ACCESS_ROLES:
        if not db.query(AccessRole).filter(AccessRole.key == key).first():
            db.add(AccessRole(key=key, label=label,
                              perms=_json.dumps(perms, ensure_ascii=False)))
            added += 1
    db.commit()
    return added


# ── LLM 调用演示数据：3 种 provider 算力对比（核心演示亮点）────────────────
# (contract_seq, agent, provider, model, prompt_tokens, completion_tokens, latency_ms)
# contract_seq 指 _CONTRACTS 列表中的顺序（0-based），seed 时映射到真实 contract.id
# OpenClaw：1.4-1.8s  DeepSeek：6-7s  Qwen：4-4.5s
_LLM_CALLS = [
    # DeepSeek 批次（合同 1-3，最新，模拟近期真实调用）
    (0, "legal",   "deepseek", "deepseek-chat", 541, 693, 6520),
    (0, "finance", "deepseek", "deepseek-chat", 612, 748, 7140),
    (1, "legal",   "deepseek", "deepseek-chat", 502, 644, 6210),
    (1, "finance", "deepseek", "deepseek-chat", 588, 712, 6890),
    (2, "legal",   "deepseek", "deepseek-chat", 521, 671, 6380),
    (2, "finance", "deepseek", "deepseek-chat", 603, 731, 7020),
    # Qwen 批次（合同 4-6，模拟私有化 Qwen 本地部署）
    (3, "legal",   "qwen", "qwen3-14b", 511, 658, 4110),
    (3, "finance", "qwen", "qwen3-14b", 598, 724, 4320),
    (4, "legal",   "qwen", "qwen3-14b", 488, 631, 3980),
    (4, "finance", "qwen", "qwen3-14b", 574, 698, 4210),
    # OpenClaw 批次（合同 7-8，模拟 OpenClaw 高速推理算力，时延显著更低）
    (6, "legal",   "openclaw", "openclaw-v2", 441, 580, 1410),
    (6, "finance", "openclaw", "openclaw-v2", 503, 621, 1530),
    (7, "legal",   "openclaw", "openclaw-v2", 458, 596, 1380),
    (7, "finance", "openclaw", "openclaw-v2", 521, 637, 1490),
]


def seed_llm_calls(db, contract_ids: list[int]) -> int:
    """灌入 LLM 调用演示数据。contract_seq 映射到真实 contract.id，幂等判重按 contract_id+agent。"""
    if not contract_ids:
        return 0
    added = 0
    for seq, agent, provider, model, pt, ct, lat in _LLM_CALLS:
        if seq >= len(contract_ids):
            continue
        cid = contract_ids[seq]
        exists = (
            db.query(LLMCallLog)
            .filter(LLMCallLog.contract_id == cid, LLMCallLog.agent == agent,
                    LLMCallLog.provider == provider)
            .first()
        )
        if exists:
            continue
        db.add(LLMCallLog(
            contract_id=cid, agent=agent, provider=provider, model=model,
            prompt_tokens=pt, completion_tokens=ct, latency_ms=lat, mode="llm",
        ))
        added += 1
    db.commit()
    return added


def _ensure_uploader(db) -> User:
    """种子合同的 uploaded_by 挂到 legal 账号（init_db 已建）；缺失则补建。"""
    user = db.query(User).filter(User.username == "legal").first()
    if user is None:
        user = User(
            username="legal",
            password_hash=hash_password("legal123"),
            role="legal",
            department="法务部",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def seed_contracts_and_risks(db, uploader: User) -> tuple[int, int]:
    added_c = added_r = 0
    for filename, ctype, dept, status in _CONTRACTS:
        exists = db.query(Contract).filter(Contract.filename == filename).first()
        if exists:
            continue
        contract = Contract(
            filename=filename,
            storage_path=f"storage/demo/{filename}",  # 演示占位路径，无真实文件
            contract_type=ctype,
            department=dept,
            status=status,
            uploaded_by=uploader.id,
        )
        db.add(contract)
        db.flush()  # 拿到 contract.id
        added_c += 1
        for r in _RISKS.get(filename, []):
            db.add(Risk(contract_id=contract.id, **r))
            added_r += 1
    db.commit()
    return added_c, added_r


def seed_knowledge(db) -> int:
    added = 0
    for category, source, content in _KNOWLEDGE:
        scope_metadata = controlled_seed_scope(category, source)
        exists = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.source == source, KnowledgeChunk.content == content)
            .first()
        )
        if exists:
            exists.scope_mode = scope_metadata["scope_mode"]
            exists.applicable_contract_types = json.dumps(
                scope_metadata["applicable_contract_types"], ensure_ascii=False
            )
            exists.applicable_dimensions = json.dumps(
                scope_metadata["applicable_dimensions"], ensure_ascii=False
            )
            continue
        db.add(KnowledgeChunk(
            category=category,
            source=source,
            content=content,
            embedding="",  # DeepSeek 无 embedding 端点，RAG 走关键词降级
            scope_mode=scope_metadata["scope_mode"],
            applicable_contract_types=json.dumps(
                scope_metadata["applicable_contract_types"], ensure_ascii=False
            ),
            applicable_dimensions=json.dumps(
                scope_metadata["applicable_dimensions"], ensure_ascii=False
            ),
        ))
        added += 1
    db.commit()
    return added


def seed_lookups(db: Session) -> int:
    """预置部门和合同类型选项（幂等：按 category+value 去重）。"""
    _DEPARTMENTS = [
        "采购中心", "销售部", "研发部", "法务部",
        "财务部", "人力资源部", "行政部", "运营部",
        "市场部", "研发外包部", "市场运营部", "行政人事部",
    ]
    _CONTRACT_TYPES = [
        "软件开发外包合同", "技术服务合同", "采购合同",
        "销售合同", "劳动合同", "租赁合同",
        "保密协议", "合作协议", "服务协议", "框架协议",
        "技术开发合同", "合作合同", "服务合同", "劳务合同",
    ]
    existing = {(i.category, i.value) for i in db.query(LookupItem).all()}
    added = 0
    for idx, val in enumerate(_DEPARTMENTS):
        if ("department", val) not in existing:
            db.add(LookupItem(category="department", value=val, sort_order=idx))
            added += 1
    for idx, val in enumerate(_CONTRACT_TYPES):
        if ("contract_type", val) not in existing:
            db.add(LookupItem(category="contract_type", value=val, sort_order=idx))
            added += 1
    db.commit()
    return added


def main() -> None:
    init_db()  # 确保建表 + 补列 + 种子账号
    db = SessionLocal()
    try:
        uploader = _ensure_uploader(db)
        added_c, added_r = seed_contracts_and_risks(db, uploader)
        contract_ids = [
            c.id for c in db.query(Contract).order_by(Contract.id).all()
            if c.filename in {fn for fn, *_ in _CONTRACTS}
        ]
        added_k = seed_knowledge(db)
        added_rt = seed_rectifications(db)
        added_rule, added_tpl = seed_rules_and_templates(db)
        added_role = seed_access_roles(db)
        added_llm = seed_llm_calls(db, contract_ids)
        added_lookup = seed_lookups(db)
        total_c = db.query(Contract).count()
        total_r = db.query(Risk).count()
        total_k = db.query(KnowledgeChunk).count()
        total_rt = db.query(Rectification).count()
        total_rule = db.query(AuditRule).count()
        total_tpl = db.query(ContractTemplate).count()
        total_role = db.query(AccessRole).count()
        total_llm = db.query(LLMCallLog).count()
        total_lookup = db.query(LookupItem).count()
    finally:
        db.close()

    log.info("seed.done", added_contracts=added_c, added_risks=added_r,
             added_knowledge=added_k, added_rectifications=added_rt,
             added_rules=added_rule, added_templates=added_tpl,
             added_roles=added_role, added_llm_calls=added_llm, added_lookups=added_lookup)
    print(f"[seed] 新增：合同 {added_c} / 风险 {added_r} / 知识库 {added_k} / "
          f"整改 {added_rt} / 规则 {added_rule} / 模板 {added_tpl} / 权限角色 {added_role} / "
          f"LLM调用 {added_llm} / 下拉配置 {added_lookup}")
    print(f"[seed] 当前总量：合同 {total_c} / 风险 {total_r} / 知识库 {total_k} / "
          f"整改 {total_rt} / 规则 {total_rule} / 模板 {total_tpl} / 权限角色 {total_role} / "
          f"LLM调用 {total_llm} / 下拉配置 {total_lookup}")


if __name__ == "__main__":
    main()
