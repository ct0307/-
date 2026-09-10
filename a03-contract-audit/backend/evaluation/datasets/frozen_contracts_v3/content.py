"""将逐案事实组装成可排版的真实合同正文。"""
from __future__ import annotations

from dataclasses import dataclass

from .annexes import build_annexes
from .clauses import STYLE_PROFILES
from .models import AnnexSpec, ContractCase


@dataclass(frozen=True)
class ContractSection:
    heading: str
    paragraphs: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...] = ()

    def as_text(self) -> str:
        return "\n".join((self.heading, *self.paragraphs, *("｜".join(row) for row in self.rows)))


@dataclass(frozen=True)
class ContractDocument:
    case_id: str
    title: str
    header_lines: tuple[str, ...]
    sections: tuple[ContractSection, ...]
    annexes: tuple[ContractSection, ...]

    @property
    def plain_text(self) -> str:
        return "\n".join((self.title, *self.header_lines, *(item.as_text() for item in (*self.sections, *self.annexes))))


SECTION_NAMES = {
    "definitions": "定义与解释", "scope": "合同标的与范围", "specification": "规格和技术要求",
    "delivery": "交付与风险转移", "acceptance": "检验与验收", "price": "合同价格与税费",
    "payment": "结算与付款", "warranty": "质量保证与售后", "change": "变更管理",
    "compliance": "合规义务", "liability": "责任承担与限制", "termination": "期限与解除",
    "confidentiality": "保密义务", "dispute": "法律适用与争议解决", "signature": "合同生效与签署",
    "orders": "订单成立", "risk_transfer": "所有权与风险转移", "force_majeure": "不可抗力",
    "background": "合作背景", "business_goal": "项目目标", "milestones": "里程碑计划", "roles": "项目组织与职责",
    "support": "支持与维护", "breach": "违约责任", "recitals": "鉴于条款", "interpretation": "文件解释顺序",
    "dependencies": "客户配合与前置条件", "fees": "服务费与税费", "change_control": "需求及变更控制",
    "ip": "知识产权", "data": "数据处理", "warranties": "陈述与保证", "indemnity": "赔偿责任",
    "survival": "终止后存续义务", "general": "总则", "parties": "合同主体", "subject": "标的与数量",
    "quality": "质量标准", "performance": "履行方式", "settlement": "结算方式", "inspection": "检验程序",
    "rights": "双方权利义务", "notice": "通知与送达", "other": "其他约定", "acceptance_method": "订约与接受方式",
    "account": "账号和管理员", "service": "订阅服务", "subscription": "订阅范围与期限", "billing": "账单与发票",
    "availability": "可用性与服务等级", "user_content": "客户内容", "acceptable_use": "可接受使用规则",
    "suspension": "服务暂停", "renewal": "续订", "electronic_notice": "电子通知", "framework": "框架合作范围",
    "order_process": "订单流程", "forecast": "需求预测", "catalog": "目录和规格", "pricing": "价格机制",
    "order_acceptance": "订单确认", "invoicing": "对账和开票", "service_level": "服务考核", "order_change": "订单变更",
    "precedence": "文件效力和优先级", "term": "有效期", "original_agreement": "原协议", "purpose": "补充目的",
    "changed_terms": "变更事项", "effective_date": "生效时间", "transition": "过渡安排", "unchanged_terms": "未变更事项",
    "representations": "确认与承诺", "release": "既往责任处理", "counterparts": "文本份数", "project_overview": "工程概况",
    "site": "现场条件", "scope_boundary": "承包范围与界面", "drawings": "图纸和技术文件", "schedule": "工期计划",
    "personnel": "项目人员", "materials": "材料设备", "measurement": "计量与计价", "variation": "工程变更和签证",
    "safety": "安全文明施工", "completion": "竣工与移交", "claims": "索赔程序", "basis": "合同依据",
    "regulated_scope": "行业服务范围", "qualification": "资质与人员", "performance_standard": "履行标准",
    "records": "业务记录", "reporting": "报告义务", "audit": "检查与审计", "customer_policy": "客户制度",
    "supplier_personnel": "供应商人员", "security": "信息安全", "subcontracting": "分包与转委托",
    "business_continuity": "业务连续性", "termination_assistance": "终止协助", "order_reference": "订单依据",
    "items": "交易明细", "contact": "业务联系人",
}


SCENARIO_TERMS = {
    "procurement": ("包装运输", "到货清点", "抽样复检", "不合格品处置", "备品备件", "质量追溯"),
    "technology": ("需求基线", "系统环境", "源代码交付", "缺陷分级", "上线切换", "运维移交", "安全测试"),
    "operations": ("服务工单", "人员排班", "月度报告", "绩效考核", "连续服务", "改进计划"),
    "leasing": ("租赁物权属", "交接现状", "使用维护", "费用承担", "保险责任", "租赁物返还"),
    "construction": ("施工组织", "材料报验", "隐蔽工程", "工程计量", "现场签证", "安全管理", "竣工资料"),
    "workforce": ("人员资质", "到岗考勤", "人员替换", "劳动合规", "个人信息", "现场管理"),
    "data_ip": ("处理目的", "访问控制", "数据留存", "成果归属", "使用许可", "删除返还", "侵权处置"),
    "framework": ("订单成立", "授权边界", "履约协同", "价格更新", "文件优先", "退出安排"),
}


def _business_paragraph(case: ContractCase, key: str, ordinal: int) -> str:
    truth = case.truth
    party_a, party_b = case.parties[0], case.parties[1]
    topic = SCENARIO_TERMS[case.scenario][ordinal % len(SCENARIO_TERMS[case.scenario])]
    facts = {
        "scope": truth.subject, "subject": truth.subject, "items": truth.subject, "service": truth.subject,
        "regulated_scope": truth.subject, "project_overview": truth.subject, "business_goal": truth.subject,
        "price": f"{truth.pricing}；合同记载金额为{truth.amount or '不设固定总额'}。",
        "pricing": truth.pricing, "fees": truth.pricing, "settlement": truth.pricing,
        "payment": "；".join(truth.payment_terms), "billing": "；".join(truth.payment_terms),
        "delivery": truth.delivery, "performance": truth.delivery, "milestones": truth.delivery,
        "schedule": truth.delivery, "completion": truth.delivery, "order_acceptance": truth.delivery,
        "acceptance": truth.acceptance, "inspection": truth.acceptance, "quality": truth.acceptance,
        "termination": truth.termination, "term": truth.duration, "subscription": truth.duration,
        "effective_date": truth.duration, "renewal": truth.duration,
    }
    fact = facts.get(key, f"双方围绕{truth.subject}就{topic}建立可核验的履行安排。")
    return (
        f"{party_a.role}与{party_b.role}确认，第{ordinal + 1}项“{SECTION_NAMES.get(key, key)}”所涉{topic}应以真实业务记录为依据。{fact}"
        f"承担该项义务的一方应在约定时点提交完整、可追溯且足以复核的资料；接收方应在合理期限内核验并一次性说明可合理发现的问题。"
        f"任何口头沟通只有经双方授权联系人以书面、电子邮件或业务系统确认后才构成合同变更，紧急处置不因此免除事后补办程序。"
    )


def _common_paragraph(case: ContractCase, key: str, ordinal: int) -> str:
    profile = STYLE_PROFILES[case.drafting_style]
    focus = profile.obligation_focus[ordinal % len(profile.obligation_focus)]
    topic = SCENARIO_TERMS[case.scenario][ordinal % len(SCENARIO_TERMS[case.scenario])]
    return (
        f"就本合同第{ordinal + 1}项“{SECTION_NAMES.get(key, key)}”涉及的{topic}而言，双方同意以权责对等、风险可控和证据可追溯为原则履行。{focus}。"
        f"负有通知、审批、交付、审核或付款义务的一方应通过合同列明的渠道完成，并保留送达、版本和处理结果记录。"
        f"一方知道或应当知道履行存在障碍时，应及时说明影响、预计持续时间和补救措施；未及时说明造成损失扩大的，应承担扩大部分的责任。"
    )


def _section(case: ContractCase, key: str, ordinal: int, repeats: int) -> ContractSection:
    if case.length_class == "short":
        topic = SCENARIO_TERMS[case.scenario][ordinal % len(SCENARIO_TERMS[case.scenario])]
        return ContractSection(
            SECTION_NAMES.get(key, key),
            (
                f"双方确认第{ordinal + 1}项“{SECTION_NAMES.get(key, key)}”涉及的{topic}，以订单和附件记录为准。义务方应按时完成，对方应及时确认或一次性提出异议；未经授权的口头变更不生效。",
            ),
        )
    paragraphs = [_business_paragraph(case, key, ordinal)]
    for repeat in range(1, repeats):
        profile = STYLE_PROFILES[case.drafting_style]
        focus = profile.obligation_focus[(ordinal + repeat) % len(profile.obligation_focus)]
        paragraphs.append(
            _common_paragraph(case, key, ordinal + repeat)
            + f"本款针对“{SECTION_NAMES.get(key, key)}”的第{repeat + 1}项控制要求：{focus}；"
            + f"相关证明应与{case.case_id}的业务台账、附件版本和授权记录相互印证，不得以内部流程尚未完成对抗善意履约方。"
        )
    return ContractSection(SECTION_NAMES.get(key, key), tuple(paragraphs))


def _annex_section(index: int, annex: AnnexSpec) -> ContractSection:
    return ContractSection(
        f"附件{index}：{annex.name}（{annex.version}）",
        (f"本附件用于细化正文所述专门业务事项。{annex.precedence}",),
        (annex.columns, *annex.rows),
    )


def build_contract(case: ContractCase) -> ContractDocument:
    profile = STYLE_PROFILES[case.drafting_style]
    repeats = 1 if case.length_class in {"short", "standard"} else 2
    sections = [ContractSection("订约说明", (profile.opening_pattern,))]
    sections.extend(_section(case, key, ordinal, repeats) for ordinal, key in enumerate(profile.section_order))
    if case.revision_set is not None:
        sections.append(ContractSection("法务修订事项", (case.revision_set.deleted_text,)))
    if case.risk_level == "actionable":
        sections.append(ContractSection("特别责任安排", (
            f"就{case.truth.subject}，不利后果发生时，处于弱势的一方仍可能承担明显超出其控制范围的损失、扣款或持续履行责任。双方确认该条款属于高风险商业安排，应在签署前结合保险、责任上限、过错程度和可得救济另行审阅；本合成样本保留该不平衡表达用于系统识别。",
        )))
    elif case.risk_level == "negotiated":
        sections.append(ContractSection("特别责任安排", (
            f"就{case.truth.subject}产生的直接损失，责任方按其过错和合同约定承担责任；故意、重大过失、知识产权侵权、数据泄露和依法不得限制的责任不适用一般责任上限。双方应先采取合理减损措施，并以可核验记录确定责任范围。",
        )))
    for conflict in case.conflicts:
        sections.append(ContractSection(conflict.source_a, (conflict.text_a,)))
        sections.append(ContractSection(conflict.source_b, (conflict.text_b, conflict.precedence_rule)))
    sections.append(ContractSection(
        "合同主体和通知信息",
        tuple(f"{party.role}：{party.name}；地址：{party.address}；{party.contact}。该等信息仅为合成测试数据。" for party in case.parties),
    ))
    sections.append(ContractSection("签署约定", (profile.signature_pattern,)))
    annexes = tuple(_annex_section(index, annex) for index, annex in enumerate(build_annexes(case), start=1))
    return ContractDocument(
        case_id=case.case_id,
        title=case.title,
        header_lines=("合成测试样本，仅用于系统验收", f"案例编号：{case.case_id}", f"合同类型：{case.contract_type}", f"文本状态：{case.document_state}"),
        sections=tuple(sections),
        annexes=annexes,
    )
