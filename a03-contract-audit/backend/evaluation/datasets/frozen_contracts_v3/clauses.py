"""现实合同常见的起草风格画像。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StyleProfile:
    section_order: tuple[str, ...]
    obligation_focus: tuple[str, ...]
    opening_pattern: str
    signature_pattern: str


STYLE_PROFILES = {
    "buyer_standard": StyleProfile(
        ("definitions", "scope", "specification", "delivery", "acceptance", "price", "payment", "warranty", "change", "compliance", "liability", "termination", "confidentiality", "dispute", "signature"),
        ("供应方按采购要求完整交付", "采购方保留检验和复验权", "不合格品由供应方承担更换成本"),
        "采购方依据生产经营需要采购本合同项下标的，供应方确认具备完整履约能力。",
        "本合同经双方授权代表签字并加盖各自有效印章后生效。",
    ),
    "supplier_standard": StyleProfile(
        ("definitions", "orders", "scope", "price", "payment", "delivery", "risk_transfer", "acceptance", "change", "warranty", "liability", "force_majeure", "termination", "dispute", "signature"),
        ("客户订单须经供应方书面确认", "需求变更引起的成本和工期应调整", "责任范围与可控制风险相匹配"),
        "客户向供应方采购产品即表示接受经双方确认的订单及本通用条款。",
        "双方可采用纸质盖章或依法可验证的电子签署方式订立本合同。",
    ),
    "business_draft": StyleProfile(
        ("background", "business_goal", "scope", "milestones", "roles", "price", "payment", "acceptance", "change", "support", "confidentiality", "breach", "termination", "dispute", "signature"),
        ("项目成果解决明确业务问题", "双方项目负责人及时协同", "里程碑与付款节点对应"),
        "经前期业务沟通，双方就项目目标、合作范围和实施安排形成如下约定。",
        "本合同一式两份，各方签章后各执一份，具有同等效力。",
    ),
    "legal_redline": StyleProfile(
        ("recitals", "definitions", "interpretation", "scope", "dependencies", "delivery", "acceptance", "fees", "change_control", "ip", "data", "warranties", "indemnity", "liability", "termination", "survival", "dispute", "signature"),
        ("定义、例外和责任边界应可执行", "客户依赖事项不得当然免除服务责任", "终止后数据和知识产权义务继续有效"),
        "鉴于各方已经就交易背景和风险分配进行审阅，现对完整权利义务约定如下。",
        "签署页属于本合同组成部分，授权代表签署即确认已完成内部审批。",
    ),
    "model_contract": StyleProfile(
        ("general", "parties", "subject", "quality", "performance", "price", "settlement", "inspection", "rights", "breach", "force_majeure", "notice", "dispute", "other", "signature"),
        ("双方遵循公平和诚实信用原则", "履行标准与验收程序对应", "违约责任以可证明损失和约定责任衔接"),
        "根据现行法律法规，双方遵循平等、自愿、公平和诚实信用原则订立本合同。",
        "本合同附件、补充协议及经确认的往来文件均为合同组成部分。",
    ),
    "online_terms": StyleProfile(
        ("acceptance_method", "account", "service", "subscription", "fees", "billing", "availability", "user_content", "data", "acceptable_use", "suspension", "renewal", "termination", "electronic_notice", "dispute"),
        ("账号管理员操作对客户具有约束力", "在线订单确定订阅范围和期限", "停用服务须符合通知和数据导出规则"),
        "客户通过签署订单、开通账号或实际使用服务的方式接受本服务条款。",
        "电子订单、平台确认记录和实名认证签署记录共同构成有效订约凭证。",
    ),
    "framework_order": StyleProfile(
        ("framework", "order_process", "forecast", "catalog", "pricing", "order_acceptance", "delivery", "inspection", "invoicing", "service_level", "order_change", "precedence", "term", "termination", "signature"),
        ("框架协议本身不承诺最低采购量", "有效订单形成具体履约义务", "订单偏离框架须明确列示并经授权确认"),
        "本协议建立持续交易的一般规则，具体标的和数量以有效订单为准。",
        "框架协议和订单可分次签署；订单签署不改变未被明确变更的通用条款。",
    ),
    "master_supplement": StyleProfile(
        ("original_agreement", "purpose", "changed_terms", "effective_date", "transition", "unchanged_terms", "precedence", "representations", "release", "notice", "counterparts", "signature"),
        ("仅明确列示事项发生变更", "未变更条款持续有效", "补充协议与原协议冲突时限于变更范围优先"),
        "各方曾签署原协议，现因履行条件变化，就特定事项达成本补充约定。",
        "本补充协议可签署多份副本，各份合并构成同一文件。",
    ),
    "project_conditions": StyleProfile(
        ("project_overview", "site", "scope_boundary", "drawings", "schedule", "personnel", "materials", "inspection", "measurement", "variation", "payment", "safety", "completion", "warranty", "claims", "termination", "signature"),
        ("施工界面和工程量边界清晰", "变更签证须履行授权程序", "安全质量责任落实到现场过程"),
        "本专用条件结合项目现场、施工图纸和工程量清单，对工程实施作出具体约定。",
        "双方在签署页加盖公章或合同专用章，项目人员签字不得替代法人授权。",
    ),
    "industry_template": StyleProfile(
        ("basis", "definitions", "regulated_scope", "qualification", "personnel", "performance_standard", "records", "reporting", "fees", "audit", "safety", "compliance", "breach", "termination", "dispute", "signature"),
        ("服务方持续具备法定和行业资质", "业务记录满足监管留存要求", "重大事件按时报告并配合审计"),
        "双方依据适用的行业监管要求、技术规范和业务管理制度开展本项合作。",
        "签署人确认本合同不存在以项目人员签字替代必要审批的情形。",
    ),
    "customer_template": StyleProfile(
        ("customer_policy", "scope", "supplier_personnel", "delivery", "acceptance", "fees", "security", "data", "ip", "audit", "subcontracting", "business_continuity", "liability", "termination_assistance", "dispute", "signature"),
        ("供应商遵守客户现场及信息安全制度", "分包和人员替换需事先批准", "终止时完成数据返还和业务迁移"),
        "供应商理解客户的业务连续性、合规和安全要求，并同意依本合同提供服务。",
        "供应商签署本合同即确认已经取得履行全部义务所需授权。",
    ),
    "short_order": StyleProfile(
        ("order_reference", "parties", "items", "price", "delivery", "acceptance", "payment", "warranty", "precedence", "contact", "signature"),
        ("订单标的和数量可直接核对", "交期、验收和付款条件相互对应", "订单与主协议的优先关系明确"),
        "本确认单记录本次具体交易，未载事项按所引用的主协议或通用条款执行。",
        "双方授权人员签字或通过约定电子系统确认后，本订单即生效。",
    ),
}
