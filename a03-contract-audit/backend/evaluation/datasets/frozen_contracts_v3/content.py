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


SECTION_SPECIFIC_CONTROLS = {
    "definitions": "关键术语以首次定义为准，单复数和附件中的同名字段具有相同含义。",
    "scope": "范围排除项须逐项列明，不能仅以“其他”或“另议”概括。",
    "specification": "偏差表未披露的降配、替代料或兼容性限制视为不符合约定。",
    "delivery": "每批交付须标明数量、版本、运输状态和风险异常。",
    "acceptance": "验收结论应由约定角色签署，附条件通过不等于问题关闭。",
    "price": "价款包含完成约定交付所需的包装、运输、人工及税费，明确排除项除外。",
    "payment": "付款节点应与可核验成果对应，不以内部预算流程改变到期日。",
    "warranty": "维修或替换部分的质保期自重新验收之日起计算。",
    "change": "变更单须同时写明基线、增减范围、价款和工期影响。",
    "compliance": "履约所需许可和备案失效时，相关作业应立即停止。",
    "liability": "责任上限的基数、期间和不适用情形须分别计算。",
    "termination": "解除通知应列明违约事实、补救期和终止后的交接事项。",
    "confidentiality": "保密信息可披露给确有必要知悉且受同等义务约束的人员。",
    "dispute": "争议处理期间，双方继续完成不受争议影响的交付和付款。",
    "signature": "签署页主体名称应与登记信息一致，分支机构签署须附授权。",
    "orders": "订单经约定渠道确认后成立，预测和询价本身不构成采购承诺。",
    "risk_transfer": "所有权转移不当然等同于毁损灭失风险转移。",
    "force_majeure": "受影响方未及时通知或未合理减损的，不得就扩大损失免责。",
    "background": "合作背景仅用于解释交易目的，不替代具体权利义务。",
    "business_goal": "目标应转化为可交付成果和可复核指标，宣传性描述不作为验收标准。",
    "milestones": "里程碑延期应区分前置依赖、责任原因和关键路径影响。",
    "roles": "项目负责人权限以授权矩阵为限，重大决定须升级审批。",
    "support": "支持请求按严重等级分派响应、恢复和根因分析时限。",
    "breach": "违约金、扣款和损害赔偿基于同一损失时不得重复主张。",
    "recitals": "鉴于条款与正文不一致时，以正文的可执行约定为准。",
    "interpretation": "专用条件、订单和附件的优先关系仅适用于其明确调整事项。",
    "dependencies": "客户依赖事项须列明提供内容和最迟日期，不能作为概括免责。",
    "fees": "服务费应区分固定费用、可变费用、代垫费用和适用税率。",
    "change_control": "需求基线变更前应完成影响评估、审批和版本归档。",
    "ip": "背景知识产权与新成果分别确认归属、许可和交付范围。",
    "data": "处理目的、数据字段、保存期限和删除方式应与附件数据目录一致。",
    "warranties": "陈述保证在签署日作出，并在持续履约事项上保持真实。",
    "indemnity": "第三方索赔应及时通知责任方并给予合理的抗辩参与权。",
    "survival": "保密、知识产权、审计、结算和责任条款按其性质继续有效。",
    "general": "权利暂不行使不构成放弃，部分无效不影响其余条款。",
    "parties": "主体信息应包括全称、地址和通知联系人，多方交易分别列明角色。",
    "subject": "标的数量、规格和计量口径须能与订单或清单逐项核对。",
    "quality": "质量标准同时明确抽样方法、判定规则和不合格处置。",
    "performance": "履行方式应说明地点、资源、顺序和第三方协作边界。",
    "settlement": "结算单区分本期发生、累计确认、扣减和争议金额。",
    "inspection": "抽检未覆盖的隐蔽缺陷和质保期缺陷仍由责任方承担。",
    "rights": "协助、审查和监督权不转移相对方的专业履约责任。",
    "notice": "解除、索赔和重大违约通知须采用可证明送达的书面方式。",
    "other": "未尽事项须以补充协议处理，项目纪要不得当然修改核心条款。",
    "acceptance_method": "线上接受须保留账号身份、条款版本、时间和操作日志。",
    "account": "管理员账号采用实名、最小权限和定期复核，禁止多人共用。",
    "service": "订阅功能、容量、环境和支持边界以订单列示为准。",
    "subscription": "订阅数量、期限和超量计费应在开通前确认。",
    "billing": "账单逐项列明计费周期、用量、单价、折扣和税额。",
    "availability": "可用率排除窗口须预先定义，计划维护应提前通知。",
    "user_content": "客户内容权利仍归客户，平台仅取得履约必要的有限处理权。",
    "acceptable_use": "禁止利用服务侵权、攻击系统或处理法律明令禁止的数据。",
    "suspension": "暂停服务应与风险程度相当，并保留紧急数据导出渠道。",
    "renewal": "自动续订应提前提醒价格和期限，客户可在截止日前拒绝续订。",
    "electronic_notice": "电子通知应能导出完整内容、发送时间和送达状态。",
    "framework": "框架协议不承诺最低采购量，具体义务由有效订单触发。",
    "order_process": "下单、确认、变更和取消分别设置权限与截止时间。",
    "forecast": "滚动预测用于备货参考，锁定窗口内数量才产生约束。",
    "catalog": "目录更新须保留旧版本，替代品不得降低既定技术标准。",
    "pricing": "调价公式明确基准指数、观察期、触发幅度和取整方式。",
    "order_acceptance": "订单确认应返回唯一编号、承诺数量和交付日期。",
    "invoicing": "发票与对账差异应逐项处理，无争议部分正常开票付款。",
    "service_level": "服务扣减以约定统计口径计算，并设问题整改和复核机制。",
    "order_change": "订单变更不得追溯改变已经验收或结算的事项。",
    "precedence": "文件优先仅解决冲突，不用于扩大未明确约定的义务。",
    "term": "起止日期、续展条件和跨期订单的效力应分别约定。",
    "original_agreement": "原协议以名称、编号和签署日期唯一识别。",
    "purpose": "补充协议只处理列明事项，不整体替代原协议。",
    "changed_terms": "每项变更均应对应原条款、修改后文本和适用范围。",
    "effective_date": "变更原则上不追溯生效，已履行事项另有确认的除外。",
    "transition": "新旧安排切换期间应明确在途事项和临时结算口径。",
    "unchanged_terms": "未明确修改的原协议条款继续有效并与补充协议一并解释。",
    "representations": "各方确认签署授权和资料真实性，不依赖未写入合同的承诺。",
    "release": "既往责任豁免须指向具体事项，不作概括性放弃。",
    "counterparts": "各份副本内容一致时共同构成同一合同。",
    "project_overview": "工程位置、规模、使用状态和施工条件应与现场一致。",
    "site": "承包人进场前完成踏勘并书面列示已发现的现场限制。",
    "scope_boundary": "施工界面按系统、区域和接口划分，交叉作业明确牵头方。",
    "drawings": "施工仅使用受控版本图纸，作废图纸应及时撤回。",
    "schedule": "总进度、关键路径和资源计划应按周更新并说明偏差。",
    "personnel": "关键人员须满足资质和到岗要求，替换需事先批准。",
    "materials": "进场材料先报验，未经批准的替代材料不得用于永久工程。",
    "measurement": "计量以合格完成量和签认记录为依据，不合格工程不计价。",
    "variation": "现场签证记录事实，价款和工期仍须按授权程序确认。",
    "safety": "重大隐患有权停工，整改复查通过后方可恢复作业。",
    "completion": "移交应包含竣工图、检测报告、设备资料和培训记录。",
    "claims": "索赔通知列明事件、责任依据、金额和工期计算资料。",
    "basis": "适用规范应列明名称和版本，冲突时按法定层级和专用约定处理。",
    "regulated_scope": "受监管服务不得超越许可地域、业务类别或人员资格。",
    "qualification": "资质证照到期前完成续期，暂停期间不得安排无证人员替代。",
    "performance_standard": "绩效指标应有数据来源、统计周期和异常剔除规则。",
    "records": "业务记录按监管和合同期限留存，并保持可检索和防篡改。",
    "reporting": "定期报告同时列示完成量、异常、整改和下期计划。",
    "audit": "审计应提前通知并限于合同相关资料，不妨碍正常经营。",
    "customer_policy": "客户制度须在履约前提供，更新不得实质增加未计价义务。",
    "supplier_personnel": "供应商负责人员劳动关系、薪酬保险和现场纪律。",
    "security": "安全事件按等级响应，重大事件立即隔离并保存取证材料。",
    "subcontracting": "分包须事先批准，原承包方仍对分包成果承担责任。",
    "business_continuity": "关键服务应维护恢复预案、备份和替代人员名单。",
    "termination_assistance": "终止协助明确期限、成果格式、人员投入和费用。",
    "order_reference": "确认单应准确引用主协议编号和当前有效版本。",
    "items": "交易明细至少载明编码、名称、数量、单价和要求交期。",
    "contact": "联系人只能处理日常协同，超授权事项对合同不生效。",
}


SCOPE_KEYS = {
    "definitions", "scope", "subject", "items", "service", "regulated_scope", "project_overview",
    "business_goal", "framework", "catalog", "order_reference", "parties", "basis", "background",
    "recitals", "purpose", "original_agreement", "account", "subscription",
}
PRICE_KEYS = {"price", "pricing", "fees", "settlement", "payment", "billing", "invoicing"}
DELIVERY_KEYS = {
    "delivery", "performance", "milestones", "schedule", "completion", "order_acceptance", "orders",
    "order_process", "forecast", "risk_transfer", "transition", "site", "scope_boundary", "drawings",
    "materials", "personnel", "supplier_personnel", "roles", "support", "service_level", "availability",
    "business_continuity", "termination_assistance",
}
ACCEPTANCE_KEYS = {"specification", "acceptance", "inspection", "quality", "acceptance_method", "performance_standard", "records", "reporting", "audit"}
CHANGE_KEYS = {"change", "change_control", "order_change", "variation", "changed_terms", "unchanged_terms", "precedence", "interpretation"}
DATA_KEYS = {"confidentiality", "data", "ip", "security", "user_content", "acceptable_use", "subcontracting"}
LIABILITY_KEYS = {"warranty", "warranties", "liability", "breach", "indemnity", "claims", "representations", "release"}
TERM_KEYS = {"termination", "term", "effective_date", "renewal", "suspension", "survival", "counterparts"}
GOVERNANCE_KEYS = {"compliance", "safety", "qualification", "customer_policy", "notice", "electronic_notice", "dispute", "force_majeure", "general", "other", "contact", "signature"}


def _section_group(key: str) -> str:
    for name, keys in (
        ("scope", SCOPE_KEYS), ("price", PRICE_KEYS), ("delivery", DELIVERY_KEYS),
        ("acceptance", ACCEPTANCE_KEYS), ("change", CHANGE_KEYS), ("data", DATA_KEYS),
        ("liability", LIABILITY_KEYS), ("term", TERM_KEYS), ("governance", GOVERNANCE_KEYS),
    ):
        if key in keys:
            return name
    return "governance"


def _primary_clause(case: ContractCase, key: str, ordinal: int) -> str:
    truth = case.truth
    party_a, party_b = case.parties[0], case.parties[1]
    heading = SECTION_NAMES.get(key, key)
    topic = SCENARIO_TERMS[case.scenario][ordinal % len(SCENARIO_TERMS[case.scenario])]
    focus = STYLE_PROFILES[case.drafting_style].obligation_focus[ordinal % 3]
    group = _section_group(key)
    specific = SECTION_SPECIFIC_CONTROLS[key]
    if key == "specification":
        return (
            f"{party_b.role}提供的{truth.subject}应满足附件技术规格、经确认图纸及{truth.acceptance}。型号、材料、接口、容量或性能参数构成报价和验收依据，未经{party_a.role}书面同意不得降配或以近似产品替代。"
            f"发现规格之间存在歧义时，{party_b.role}应在采购、生产或开发前提出澄清并提交偏差表；未披露偏差造成返工、停线或兼容性问题的，由其承担补救费用和相应工期责任。{specific}"
        )
    if key in {"payment", "billing", "invoicing"}:
        payments = "；".join(truth.payment_terms)
        return (
            f"“{heading}”依次按以下节点办理：{payments}。付款申请应列明对应交付批次、已确认价款、税额和本期应付金额，并附验收或对账依据。"
            f"{party_a.role}对申请存在异议的，应在收到后五个工作日内一次性列明；双方先支付无争议金额，争议部分在补充资料或复核完成后单独结算。收款账户变更须经盖章通知确认。{specific}"
        )
    if key in {"warranty", "warranties"}:
        return (
            f"“{heading}”覆盖{truth.subject}的材料、工艺、性能和约定功能。质保或服务期内发生缺陷，{party_b.role}应在收到通知后响应，完成远程诊断、现场修复或替换，并承担其责任范围内的运输和人工费用。"
            f"同一缺陷反复发生或修复后仍不符合{truth.acceptance}的，{party_a.role}可要求重新履行、减价或依{truth.termination}处理；正常损耗及未经授权的改造不在免费责任范围内。{specific}"
        )
    if key == "signature":
        return (
            f"本合同自各方有权代表签字并加盖公章或合同专用章之日起生效；采用可靠电子签名的，签署平台完成时间视为签署时间。签署人应确保已取得内部授权。"
            f"正文、附件、经确认的订单和补充协议共同构成完整合同文件。各方可分别签署同版文本，扫描件或电子副本可用于履行，原件份数及保管方式以签署页记载为准。{specific}"
        )
    if key == "dispute":
        return (
            f"本合同的订立、效力、解释和履行适用中华人民共和国法律。因{truth.subject}产生争议时，双方应先由项目负责人协商；十个工作日内未解决的，提交各自管理层继续协商。"
            f"协商仍未解决的，按合同约定的仲裁机构或有管辖权的人民法院处理。争议期间，除争议事项和确实无法继续的部分外，各方仍应履行其他无争议义务并保存证据。{specific}"
        )
    if key in {"compliance", "qualification", "customer_policy"}:
        return (
            f"履行“{heading}”期间，各方应持续具备从事相关业务所需的许可、备案、人员资质和安全条件，并遵守反商业贿赂、出口管制、劳动用工及现场管理要求。"
            f"发现资质失效、监管调查或可能影响{topic}的重大违规时，相关方应立即书面通知并采取隔离措施；对方有权暂停受影响工作，直至风险消除且证明文件复核通过。{specific}"
        )
    if key == "force_majeure":
        return (
            f"受不可预见、不可避免且不可克服事件影响的一方，应在事件发生后五个工作日内通知对方，说明对{topic}的影响并在合理期限内提交证明。"
            f"双方应优先采取替代运输、远程履行或顺延计划等减损措施；影响持续超过三十日且合同目的无法实现的，任一方可解除受影响部分，已完成工作据实结算。{specific}"
        )
    if key in {"notice", "electronic_notice", "contact"}:
        return (
            f"与“{heading}”有关的通知应发送至合同列明的地址、电子邮箱或约定业务系统。专人递送以签收日、快递以妥投日、电子信息以系统可验证送达记录所示时间为送达日。"
            f"联系人或地址变更应提前三个工作日书面通知；未通知导致文件无法送达的，由变更方承担不利后果。涉及解除、索赔或重大违约的通知不得仅通过即时聊天工具发送。{specific}"
        )
    if group == "scope":
        return (
            f"本合同“{heading}”以{truth.subject}为交易基础，{party_b.role}交付内容应与报价、订单及附件列明的规格和边界一致。"
            f"涉及{topic}的数量、接口或工作成果未列明时，{party_b.role}应在实施前提交书面清单，由{party_a.role}确认后纳入履约范围；确认不免除其对完整性和适用性的责任。{focus}。{specific}"
        )
    if group == "price":
        amount = truth.amount or "按有效订单、实际验收数量及约定单价据实结算，不设固定总额"
        payments = "；".join(truth.payment_terms)
        return (
            f"“{heading}”适用以下商业条件：{truth.pricing}；合同金额或结算口径为{amount}。付款按“{payments}”执行。"
            f"收款方应提交与{topic}相符的对账单、验收文件及合法发票；资料存在可合理说明的缺项时，付款期限自补齐之日起计算，无争议部分不得无故延付。{specific}"
        )
    if group == "delivery":
        return (
            f"关于“{heading}”，双方确认履行安排为：{truth.delivery}。{party_b.role}应提前报告{topic}的准备状态、依赖事项和预计偏差，交付时同步提供清单、版本及签收依据。"
            f"迟延或范围偏差可能影响后续节点的，{party_b.role}应在知悉后两个工作日内提出纠偏计划；{party_a.role}的现场配合不视为对质量、数量或工期的最终认可。{specific}"
        )
    if group == "acceptance":
        return (
            f"“{heading}”按下列标准实施：{truth.acceptance}。检验应覆盖{topic}，并形成样品、测试数据、问题清单或双方签认记录。"
            f"发现不符合项时，{party_b.role}应在约定期限内返工、更换或补交材料，复验不减少原质量责任；{party_a.role}逾期未反馈仅对当时可合理发现的外观和数量问题发生效力。{specific}"
        )
    if group == "change":
        return (
            f"任何涉及“{heading}”的调整均应说明变更原因、具体内容及对价款、工期、验收和既有成果的影响。经双方有权代表以变更单、补充协议或约定业务系统确认前，{party_b.role}不得仅凭口头要求扩大{topic}范围。"
            f"为避免现实损失确需先行处置的，应在三个工作日内补齐授权记录；未补齐的，主张变更的一方承担无法证明部分的不利后果。{specific}"
        )
    if group == "data":
        return (
            f"“{heading}”仅限履行{truth.subject}所必需的范围。接收方应针对{topic}实行最小权限、人员保密、传输保护和访问留痕，不得擅自复制、披露、转委托或用于本合同以外目的。"
            f"发生泄露、误用或权利主张时，应立即隔离影响、保存证据并通知对方；合同终止后按约定返还或删除资料，但法律要求留存及争议举证所必需的副本除外。{specific}"
        )
    if group == "liability":
        return (
            f"违反“{heading}”约定的一方应停止违约、采取补救并赔偿对方因此遭受的可证明损失。对{topic}能够通过返工、替换或重新履行补救的，守约方应给予合理期限，但{truth.termination}。"
            f"责任限制不得适用于故意或重大过失、人身损害、知识产权侵权、保密或数据泄露以及法律禁止限制的责任；主张损失的一方应采取合理减损措施并保存费用凭证。{specific}"
        )
    if group == "term":
        return (
            f"“{heading}”适用期间为{truth.duration}。发生解除、暂停或不续展情形时，提出方应说明依据、生效时间和受影响范围，并为{topic}保留必要的交接期。"
            f"终止不影响终止前已经发生的付款、保密、知识产权、资料返还和违约责任；{truth.termination}。对可补救违约，守约方应先按合同约定发出整改通知。{specific}"
        )
    return (
        f"双方就“{heading}”确认，{topic}应遵守适用法律、行业规范及各自依法制定并事先披露的管理制度。需要许可、审批或资质的，由负有义务的一方在实施前取得并持续有效。"
        f"通知和决定应发送至合同列明的联系人并保留可查询记录；发生重大安全、合规或不可抗力事件时，应先控制损失，再在合理期限内提交原因、影响和恢复安排。{focus}。{specific}"
    )


def _secondary_clause(case: ContractCase, key: str, ordinal: int) -> str:
    heading = SECTION_NAMES.get(key, key)
    topic = SCENARIO_TERMS[case.scenario][(ordinal + 2) % len(SCENARIO_TERMS[case.scenario])]
    focus = STYLE_PROFILES[case.drafting_style].obligation_focus[(ordinal + 1) % 3]
    controls = {
        "scope": f"范围澄清以经签认的需求基线、图纸、订单和附件为准；未列入报价但属于实现约定功能不可缺少的{topic}，应在开工前书面揭示并协商处理。",
        "price": f"每次付款申请应能对应到已完成的{topic}和验收节点；税率、发票类型或收款账户变化，应在付款日前书面通知并提供有效证明。",
        "delivery": f"交付记录至少载明时间、地点、版本、数量、承运或实施人员及异常情况；对{topic}的临时替代方案不得降低最终交付标准。",
        "acceptance": f"验收结论分为通过、附条件通过和不通过；附条件通过应列明{topic}整改项、责任人和截止日，不得用投入使用替代最终验收。",
        "change": f"变更台账应连续编号并附原始要求、评估意见和批准记录；涉及{topic}的减项、替代或顺序调整，应同步修订相关附件。",
        "data": f"涉及{topic}的载体、账号和备份均纳入安全边界；人员离岗、权限变更或分包终止时，应立即回收访问权限并核对资料去向。",
        "liability": f"损失计算应区分直接损失、第三方索赔和可避免扩大的部分；围绕{topic}的扣款或索赔不得重复计算，已有保险赔付应据实冲抵。",
        "term": f"退出交接至少覆盖未完成事项、在途成果、账号权限、资料清单和费用结算；{topic}需要持续运行的，双方应约定临时支持范围和计费标准。",
        "governance": f"涉及{topic}的审批、通知和会议结论应由有权人员确认；项目人员的签收只证明现场事实，不当然构成对价款、工期或责任的变更。",
    }
    evidence = (
        "归档材料应能对应合同编号、形成日期和经办主体；电子记录导出后应保留原始系统标识，纸质记录的涂改处须由相关人员签认。",
        "一方对记录真实性或完整性有合理异议时，可以在不泄露无关商业秘密的前提下查验原件、抽取底稿或要求第三方出具证明。",
        "现场会议形成的结论应在两个工作日内发送纪要；收到方逾期未反馈不代表放弃实体权利，但不得否认已经确认的现场事实。",
        "任何临时措施均应明确适用期限、责任人员和恢复条件；期限届满仍需继续执行的，必须重新评估风险并取得相应授权。",
        "因一方未及时提供依赖资料导致计划受阻的，受影响方应说明可替代方案和关键路径，不得将本可避免的全部延误转由对方承担。",
        "双方在月度或里程碑复盘时核对未决事项、费用和风险；发现台账与实物或系统记录不一致的，以可验证的原始证据重新确认。",
    )[ordinal % 6]
    return f"作为“{heading}”的履约证据，{controls[_section_group(key)]}{focus}。{SECTION_SPECIFIC_CONTROLS[key]}{evidence}"


def _short_clause(case: ContractCase, key: str, ordinal: int) -> str:
    truth = case.truth
    heading = SECTION_NAMES.get(key, key)
    group = _section_group(key)
    clauses = {
        "scope": f"本次{heading}为{truth.subject}，具体型号、数量和授权范围以本确认单及附件明细为准；超出部分须另行下单。",
        "price": f"{heading}采用以下计价口径：{truth.pricing}，金额为{truth.amount or '据有效订单和验收数量结算'}；付款节点为{'；'.join(truth.payment_terms)}。",
        "delivery": f"{heading}安排为{truth.delivery}。交付方应同步提供清单和版本记录，签收不等于质量验收。",
        "acceptance": f"{heading}标准为{truth.acceptance}；不符合项应在收到通知后限期更换、补交或重新履行。",
        "change": f"{heading}须由双方授权人员书面确认；订单与主协议不一致的，仅明确列示的本次交易事项优先。",
        "data": f"履行{heading}时仅可使用本订单所需资料，不得转授权或扩大用途，交易结束后按要求返还或删除。",
        "liability": f"违反{heading}的一方应补救并承担可证明损失；达到解除条件时，{truth.termination}。",
        "term": f"{heading}适用期间为{truth.duration}；终止前已发生的付款、保密和违约责任继续有效。",
        "governance": f"{heading}由合同列明联系人处理，涉及金额、工期或责任变化的决定须经有权代表书面确认。",
    }
    if key == "parties":
        return f"合同主体为{'、'.join(party.name for party in case.parties)}，各方身份和角色以签署栏为准；联系人无权单独变更价款、期限或责任。"
    if key == "order_reference":
        return "本确认单依据双方已生效的主协议订立，主协议名称、编号及版本以首页引用为准；本确认单未明确变更的通用条款继续适用。"
    if key == "items":
        return f"本次交易明细为{truth.subject}。附件逐项列明成果、数量、版本和交付日期，任何增项或替代均须重新确认价格及验收影响。"
    if key in {"payment", "billing", "invoicing"}:
        return f"{heading}按{'；'.join(truth.payment_terms)}执行。付款申请应附对应签收或验收记录，争议部分单独核对，无争议金额按期支付。"
    evidence = {
        "scope": "附件缺项应在发货或开工前补齐。",
        "price": "开票信息和收款账户以盖章通知为准。",
        "delivery": "异常情况应在当日书面告知。",
        "acceptance": "复验不免除原有质量责任。",
        "change": "临时处置须在三个工作日内补签。",
        "data": "访问和交付记录至少保存三年。",
        "liability": "守约方应采取合理减损措施。",
        "term": "退出时应结清在途事项并交还资料。",
        "governance": "项目人员签收不当然变更价款或责任。",
    }
    return clauses[group] + evidence[group]


def _long_form_controls(case: ContractCase) -> ContractSection:
    party_a, party_b = case.parties[0], case.parties[1]
    terms = SCENARIO_TERMS[case.scenario]
    return ContractSection(
        "项目治理与履约记录",
        (
            f"各方分别指定一名项目负责人，负责统筹{terms[0]}、{terms[1]}和{terms[2]}。项目负责人可以确认日常计划和现场事实，但无权单独变更合同价款、责任限制、知识产权归属或解除条件。需要管理层决定的事项，应附影响分析后升级至有权代表；紧急事件先由现场负责人控制人员、数据或财产损失，并在二十四小时内补交书面报告。",
            f"{party_b.role}建立连续编号的履约台账，至少记录交付批次、版本、签收、问题、整改、费用和审批状态；{party_a.role}按照里程碑或每月核对一次。电子邮件、业务系统和纸质记录相互矛盾时，优先核验形成时间、发送主体、原始附件和后续履行情况，不以单一截图作为最终结论。依法需要保存的质量、安全、财务或个人信息资料，应按其法定期限留存并限制访问。",
            f"影响关键路径的依赖事项应进入未决清单，列明责任人、最迟完成日和可替代方案。对方未按期配合时，受影响方先采取合理减损措施，再就实际增加的工期和费用提出证据；未及时预警或可自行避免的损失不得全部转移。围绕{terms[3]}和{terms[4]}形成的会议纪要在两个工作日内发送，异议方应具体指出错误事实，不能仅以内部审批尚未结束否认已经发生的交付或现场记录。",
            f"项目结束前，各方共同完成未结事项、在途成果、账号权限、借用资产、保密资料和费用结算的交接。涉及持续服务的，{party_b.role}应提供不少于十个工作日的知识转移和问题答疑；涉及关键系统、施工现场或人员服务的，还应提交应急联系人及恢复顺序。上述交接不替代最终验收，也不影响任何一方依据{case.truth.termination}行使解除或索赔权利。",
        ),
    )


def _section(case: ContractCase, key: str, ordinal: int, repeats: int) -> ContractSection:
    if case.length_class == "short":
        return ContractSection(SECTION_NAMES.get(key, key), (_short_clause(case, key, ordinal),))
    paragraphs = [_primary_clause(case, key, ordinal)]
    if repeats > 1:
        paragraphs.append(_secondary_clause(case, key, ordinal))
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
    if case.length_class == "long":
        sections.append(_long_form_controls(case))
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
    sections.append(ContractSection(
        "签署页",
        (profile.signature_pattern, "以下签署栏为合同签署组成部分，正文至此结束。"),
        (
            ("签约方", "授权代表", "签署日期", "盖章位置"),
            *((party.name, "________________", "____年__月__日", "（盖章）") for party in case.parties),
        ),
    ))
    annexes = tuple(_annex_section(index, annex) for index, annex in enumerate(build_annexes(case), start=1))
    return ContractDocument(
        case_id=case.case_id,
        title=case.title,
        header_lines=("合成测试样本，仅用于系统验收", f"案例编号：{case.case_id}", f"合同类型：{case.contract_type}", f"文本状态：{case.document_state}"),
        sections=tuple(sections),
        annexes=annexes,
    )
