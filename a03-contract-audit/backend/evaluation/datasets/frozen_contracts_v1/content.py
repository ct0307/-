"""根据冻结案例事实组装原创合同正文，不读取生产解析器实现。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import ContractCase


@dataclass(frozen=True)
class ContractSection:
    heading: str
    paragraphs: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...] = ()

    def as_text(self) -> str:
        blocks = [self.heading, *self.paragraphs]
        blocks.extend("｜".join(row) for row in self.rows)
        return "\n".join(blocks)


@dataclass(frozen=True)
class ContractDocument:
    case_id: str
    title: str
    header_lines: tuple[str, ...]
    sections: tuple[ContractSection, ...]
    annexes: tuple[ContractSection, ...]

    @property
    def plain_text(self) -> str:
        blocks = [self.title, *self.header_lines]
        blocks.extend(section.as_text() for section in (*self.sections, *self.annexes))
        return "\n".join(blocks)


PRICE_MODEL_DESCRIPTIONS = {
    "unit_price_framework": "按已确认订单的实际数量乘以附件含税单价结算，框架协议不承诺固定采购总额。",
    "consumption_based": "按经双方核对的实际领用量和约定单价逐月结算，未领用库存不计入货款。",
    "market_index_formula": "每批单价依约定公开市场指数、升贴水和交付日参数计算，不预设合同总额。",
    "separate_orders": "货款、仓储及配送费用分别依据采购订单和服务账单结算。",
    "usage_subscription": "基础订阅按订购周期计费，超出套餐的资源或调用量按月度账单据实结算。",
    "public_interest_no_fee": "本协议为限定公共服务场景的数据共享安排，各方互不收取数据交易价款。",
    "work_order_unit_price": "按有效工单记载的项目、工程量和单价表据实结算，不设最低工作量。",
    "rate_card_monthly": "仓储、操作和配送费用按月度实际业务量及服务单价表汇总结算。",
    "headcount_actual": "服务费用按经确认的实际到岗人日和岗位单价核算，人数预测不构成保底承诺。",
    "daily_usage_rate": "租用费按设备实际占用天数和预约单费率核算，校准及运输费用另行确认。",
    "success_fee_salary_ratio": "候选人达到约定入职条件后，按其首年固定薪酬的一定比例计取成功服务费。",
    "meal_count_settlement": "餐费按实际有效刷卡餐次和约定餐标逐月结算，考核扣款单独列示。",
    "non_monetary": "本协议仅约束信息披露和保密行为，不单独产生交易价款。",
    "included_in_master_service": "本协议项下费用已纳入主服务合同，不重复计费。",
    "future_orders": "具体项目的范围和价款由后续订单确定，框架协议本身不设固定总额。",
    "change_order_adjustment": "新增或减少工作量按三方确认的变更单调整，并入对应里程碑结算。",
}


def _pick(case: ContractCase, choices: tuple[str, ...]) -> str:
    return choices[(int(case.case_id[-3:]) - 1) % len(choices)]


def _role(case: ContractCase, index: int) -> str:
    if index < len(case.primary_roles):
        return case.primary_roles[index]
    return f"参与方{index + 1}"


def _party_section(case: ContractCase) -> ContractSection:
    rows = tuple(
        (_role(case, index), party, "统一社会信用代码：合成样本不适用")
        for index, party in enumerate(case.parties)
    )
    return ContractSection(
        heading=_pick(case, ("合同当事人", "签约主体", "协议各方", "交易参与方")),
        paragraphs=(
            "各方确认其具备签署和履行本合同所需的主体资格及内部授权。",
            "本页主体信息仅用于合成数据测试，不对应任何现实登记主体。",
        ),
        rows=rows,
    )


def _commercial_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    truth = case.truth
    amount = truth["amount"]
    if amount is None:
        amount_text = PRICE_MODEL_DESCRIPTIONS.get(
            case.price_model,
            "本合同不预先确定固定总额，实际价款依据有效订单、工单、计费清单或书面约定结算。",
        )
    else:
        amount_text = str(amount)

    payments = truth["payment_terms"]
    payment_rows = tuple(
        (f"第{index}期", term, "满足相应交付、验收或对账条件后执行")
        for index, term in enumerate(payments, start=1)
    )
    if not payment_rows:
        payment_rows = (("非付费安排", "本协议不单独产生付款义务", "如有费用按关联合同执行"),)

    return (
        ContractSection(
            heading=_pick(case, ("合作事项", "项目内容", "交易标的", "委托范围")),
            paragraphs=(
                str(truth["subject"]),
                "具体规格、数量、成果边界或服务口径以正文及经有效确认的附件为准。",
            ),
        ),
        ContractSection(
            heading=case.amount_heading,
            paragraphs=(amount_text, "除另有明确约定外，价格口径应与发票税目和交付范围保持一致。"),
        ),
        ContractSection(
            heading=_pick(case, ("付款安排", "费用结算", "支付与对账", "账款处理")),
            paragraphs=(
                "收款方应按约定提供合法有效的结算资料和发票；付款不视为对质量责任的免除。",
            ),
            rows=payment_rows,
        ),
        ContractSection(
            heading=_pick(case, ("履行期限", "项目周期", "有效期间", "进度约定")),
            paragraphs=(
                str(truth["duration"] or "期限由后续有效订单或双方书面确认文件确定。"),
                "影响进度的事项应及时书面通知，并保留可核验的沟通和交付记录。",
            ),
        ),
    )


def _risk_clause(tag: str, case: ContractCase) -> str:
    if any(word in tag for word in ("单方", "解释权", "默认", "默示")):
        return f"涉及{tag}时，不得仅凭一方内部记录作出决定，应给相对方合理核验和异议期限。"
    if any(word in tag for word in ("免责", "限额", "上限", "赔偿")):
        return f"就{tag}，免责或责任限制不适用于故意、重大过失以及依法不得限制的责任。"
    if any(word in tag for word in ("数据", "个人信息", "网络安全", "跨境", "漏洞")):
        return f"关于{tag}，相关方应遵循最小必要原则，落实访问控制、留痕和安全事件通知。"
    if any(word in tag for word in ("知识产权", "成果", "源代码", "模型")):
        return f"关于{tag}，各方应区分既有权利、履约成果和第三方材料，并保存授权链证明。"
    if any(word in tag for word in ("安全", "食品", "高空", "停产")):
        return f"涉及{tag}的作业应执行现场制度和应急预案，但管理配合不转移法定安全责任。"
    return f"对于{tag}，判断条件、证据形式和责任承担应结合实际履约记录另行核验。"


def _legal_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    role_a = _role(case, 0)
    role_b = _role(case, 1)
    risk_paragraphs = tuple(_risk_clause(tag, case) for tag in case.risk_tags)
    related = "、".join(case.related_documents) or "双方后续有效签署的书面文件"
    priority = (
        f"正文与{related}约定不一致时，应先核对文件形成时间和明确的优先顺序；"
        "后签且明确变更前文的文件优先，无法判断时由各方另行书面确认。"
        if case.clause_conflict
        else f"{related}与正文共同构成交易文件；未明确变更正文的，不视为对正文的替代。"
    )
    return (
        ContractSection(
            heading=_pick(case, ("双方职责", "权利与义务", "履约分工", "各方承诺")),
            paragraphs=(
                f"{role_a}应按约提供必要资料、现场条件或业务确认，不得无故拖延审批。",
                f"{role_b}应配置具备相应能力的人员和资源，并对其交付成果及分包行为负责。",
            ),
        ),
        ContractSection(
            heading=_pick(case, ("验收与异议", "成果确认", "检查和接收", "履约评价")),
            paragraphs=(
                "验收应以约定范围、可重复的标准和完整交付记录为依据。发现不符合项时，接收方应说明事实和依据，履约方应在合理期限内整改。",
                "阶段性签收、付款或投入使用不当然免除隐蔽瑕疵、持续服务或质量保证责任。",
            ),
        ),
        ContractSection(
            heading="特别约定",
            paragraphs=risk_paragraphs,
        ),
        ContractSection(
            heading=_pick(case, ("文件构成与效力", "合同文件顺序", "附件及版本", "文件解释")),
            paragraphs=(priority,),
        ),
        ContractSection(
            heading=_pick(case, ("违约处理", "责任承担", "履约救济", "违约责任")),
            paragraphs=(
                "一方未按约履行的，应在收到通知后采取补救措施，并赔偿其违约行为直接造成的合理损失。",
                "主张违约责任的一方应采取合理措施防止损失扩大，并提供能够证明违约、因果关系和损失范围的材料。",
            ),
        ),
        ContractSection(
            heading=_pick(case, ("保密和资料管理", "信息保护", "资料使用限制", "商业秘密")),
            paragraphs=(
                "履约中获悉的非公开技术、经营和人员信息仅限本项目使用；接收方应按必要范围授权访问并要求相关人员承担同等义务。",
                "法定披露、已公开信息以及能够证明从合法第三方独立取得的信息不受前述限制。",
            ),
        ),
        ContractSection(
            heading=_pick(case, ("不可抗力", "履约障碍", "情势与应急", "特殊事件处理")),
            paragraphs=(
                "受不可预见、不可避免且不可克服事件影响的一方应及时通知，提供合理证明并尽力减轻影响；金钱给付义务不因一般经营困难当然免除。",
            ),
        ),
        ContractSection(
            heading=_pick(case, ("通知和送达", "项目联络", "书面通知", "沟通机制")),
            paragraphs=(
                "业务联系人可以处理日常协调，但范围、价格、期限和责任的实质变更须由有权人员书面确认。联系人或地址变更应及时通知。",
            ),
        ),
        ContractSection(
            heading=_pick(case, ("争议解决", "适用法律及争议", "争议处理", "法律适用")),
            paragraphs=(
                "本合同适用中华人民共和国法律。争议发生后，各方应先由项目负责人和授权代表分级协商；协商不成的，按签署页约定的争议解决方式处理。",
            ),
        ),
        ContractSection(
            heading=_pick(case, ("生效与文本", "其他事项", "合同成立", "附则")),
            paragraphs=(
                "本合同自各方有权代表签署并按各自制度完成生效手续之日起生效。电子签署文本、经确认的扫描件与纸质文本具有同等证明作用。",
                "未尽事项由各方另行协商；任何补充或变更均应形成可追溯的书面记录。",
            ),
        ),
        ContractSection(
            heading="签署页",
            paragraphs=tuple(
                f"{_role(case, index)}：{party}　授权代表：________　日期：____年__月__日"
                for index, party in enumerate(case.parties)
            ),
        ),
    )


def _sale_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("规格、数量和订单", ("货物型号、技术参数、批次数量及含税单价以确认的清单或订单为准；替代型号须事先书面批准。",)),
        ContractSection("交付和风险转移", ("供货方应按指定地点分批交付并提交装箱、合格和追溯资料。毁损灭失风险在清点签收后转移，但质量责任不随之转移。",)),
        ContractSection("包装与运输", ("包装应满足运输、装卸和合理仓储要求；危险或温控物料应附明显标识和必要说明。因包装不当产生的损失由责任方承担。",)),
        ContractSection("检验和质量保证", ("到货检验不替代性能验收。抽样方案、异议期限和复检机构按货物特性确定；发现批次性缺陷时，供货方应配合隔离、退换或召回。",)),
        ContractSection("所有权及备件", ("货物、专用模具、随机软件和备件的权属按订单约定分别处理；未经权利人同意不得复制专用图纸或为第三方生产。",)),
    )


def _technology_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("需求与范围基线", ("双方以经确认的需求、接口目录和非功能指标建立范围基线。会议纪要只有在明确记载变更内容并经授权人员确认后才调整基线。",)),
        ContractSection("项目组织与开发", ("服务方应配置项目经理、架构和测试人员，执行版本管理、代码审查和缺陷跟踪；关键人员更换不得降低履约能力。",)),
        ContractSection("部署、迁移与上线", ("上线前应完成备份、回退和演练。历史数据问题应区分源数据缺陷、转换规则和程序错误，不得概括性免除迁移责任。",)),
        ContractSection("技术验收", ("验收环境、样本、并发量和通过阈值应可复现。未通过项进入缺陷清单，双方确认优先级、修复期限和复测次数。",)),
        ContractSection("数据与网络安全", ("处理业务数据应遵循约定目的和最小权限，生产数据不得擅自用于训练、展示或其他客户项目；发生事件时应及时隔离、调查和通知。",)),
        ContractSection("软件及成果权利", ("双方应区分背景知识产权、定制成果、开源组件和第三方许可。交付清单应列明源代码、文档、部署脚本以及后续维护所需材料。",)),
        ContractSection("运行维护和服务等级", ("服务可用性、响应和恢复时间按统计周期核算。计划维护、客户原因和不可抗力的扣除条件应有客观记录，不得由服务方单方认定。",)),
    )


def _service_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("服务范围和任务下达", ("常规服务按年度计划执行，临时或专项工作通过工单、任务书或排期确认；超出范围的工作应先确认资源和费用。",)),
        ContractSection("人员与现场管理", ("服务人员由服务方依法管理并承担薪酬、社保和劳动关系责任。客户的现场安全和成果要求不构成对服务人员的直接用工管理。",)),
        ContractSection("服务标准", ("响应时间、完成质量、返工率和报告要求应结合业务场景核验。考核记录须向服务方开放，并允许其在约定期限内申诉。",)),
        ContractSection("成果和验收", ("报告、工单、课程材料或运营数据为主要验收凭证。对于持续性服务，按月或按阶段确认，不以单次签收替代整个周期责任。",)),
        ContractSection("费用与第三方支出", ("差旅、媒体、材料或第三方资源费用应事前批准并提供凭证；管理费、税费和加价口径不得重复计算。",)),
        ContractSection("分包与连续性", ("未经书面同意不得将核心服务整体转包。获准分包不减轻服务方责任；关键服务中断时应启动交接和业务连续性安排。",)),
    )


def _lease_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("租赁物及权属", ("出租方应保证对租赁物具有合法出租权，并如实披露抵押、查封、共有或限制使用情况。位置、面积、设备和现状以交付清单为准。",)),
        ContractSection("用途和使用限制", ("承租方仅可按约定用途使用并遵守消防、环保和园区管理要求；管理规则的更新不得实质减损承租方已取得的核心使用权。",)),
        ContractSection("交付与接收", ("双方应共同查验状态、计量表底数、钥匙和设施，形成交接记录。交付缺陷影响使用的，租金起算和整改责任据实调整。",)),
        ContractSection("租金、押金和能耗", ("租金、服务费、能耗和税费分别列示。押金不得当然抵作最后一期租金，扣除时应说明依据并返还剩余部分。",)),
        ContractSection("维修、装修和保险", ("结构及固有设施由出租方负责，因承租方使用造成的损坏由承租方修复。装修方案和消防报审应事先确认，保险不替代责任承担。",)),
        ContractSection("返还与提前终止", ("租期届满或提前终止时，双方按交付清单办理返还。恢复原状、遗留物处理和迁出窗口应兼顾实际施工及业务连续性。",)),
    )


def _construction_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("工程或定作范围", ("承包或承揽范围以图纸、清单、技术协议和界面划分为依据。漏项、暂估项及甲供材料应分别说明，不得以总价概括全部未知工作。",)),
        ContractSection("合同文件和图纸", ("开工或制造前应完成图纸会审和技术交底。发现文件错误、矛盾或不具备实施条件时，实施方应及时提出，不得明知有误继续施工。",)),
        ContractSection("进度和工期", ("进度计划应列明关键路径、材料到货和验收节点。因变更、场地移交或协作方原因影响工期的，应提交同期记录和顺延申请。",)),
        ContractSection("变更、签证和计价", ("变更应说明原因、范围、工期和价款影响。现场联系人无权口头确认重大增项，紧急处置后应在约定期限内补齐书面记录。",)),
        ContractSection("质量检验和隐蔽工程", ("材料设备进场、隐蔽工程、样品和阶段成果按约检查。未经检验擅自覆盖的，责任方应承担重新检验的合理费用和工期影响。",)),
        ContractSection("安全、环保和现场协调", ("实施方应落实人员资质、危险作业审批和应急措施；发包方提供场地规则及必要协调，但不因此承担实施方的法定安全管理责任。",)),
        ContractSection("竣工、结算和保修", ("完工后提交完整成果、检测和竣工资料。结算审核不影响无争议款支付；保修范围、响应期限和缺陷责任起算点以验收记录为准。",)),
    )


def _employee_service_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("服务对象和名单", ("服务对象、资格条件和增减规则以经授权确认的名单为准。名单仅用于履约，不得擅自用于营销、画像或其他商业目的。",)),
        ContractSection("服务资源和人员", ("服务机构应配置具备相应资质和经验的人员，依法承担其劳动用工责任，并对服务场所、设备和流程进行持续管理。",)),
        ContractSection("服务实施和质量", ("预约、到岗、承保、检查、供餐或候选人推荐等记录应可核验。发现遗漏、差错或不符合项时，应按业务时效及时补救。",)),
        ContractSection("敏感信息保护", ("健康、身份、薪酬和候选人资料按敏感个人信息管理，采取加密、权限控制和最短保存期限；对个人的通知应避免扩大知悉范围。",)),
        ContractSection("投诉和异常事件", ("服务机构应建立投诉、食品或健康异常、保险理赔争议和人员替换机制，重大事件及时报告并保存处理证据。",)),
        ContractSection("退出与交接", ("合同终止时应完成服务对象、未结事项和资料的清点交接，依法返还或删除个人信息，不得以费用争议扣留必要证明材料。",)),
    )


def _confidentiality_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("受保护信息", ("受保护信息包括以书面、口头、电子或样品形式披露且依其性质或场景应合理理解为非公开的信息；公开信息和独立开发成果除外。",)),
        ContractSection("允许使用目的", ("接收方仅可为本项目评估和履行使用信息，并限于确有知悉必要的人员。未经同意，不得反向工程、训练模型或用于竞争性开发。",)),
        ContractSection("安全措施", ("接收方采取不低于保护自身同类重要信息的措施，包括访问授权、传输保护、操作留痕和离职权限回收。",)),
        ContractSection("依法披露", ("因法律、监管或司法要求必须披露时，在法律允许范围内提前通知披露方，并将披露范围控制在最低必要限度。",)),
        ContractSection("成果和知识产权", ("信息披露不构成任何明示或默示许可。联合成果、改进成果、申请权及商业化收益应结合人员贡献、背景权利和专项约定确定。",)),
        ContractSection("返还、删除与存档", ("目的完成或收到要求后，接收方应返还或安全删除载体；法定留档和备份系统中的不可即时删除副本继续受本合同约束。",)),
    )


def _related_document_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return (
        ContractSection("合作背景", ("各方此前已形成框架、主合同、订单或补充文件，本协议用于明确后续业务安排，不当然替代未被明确变更的既有条款。",)),
        ContractSection("文件衔接", ("引用文件应能通过名称、编号、版本和签署日期识别。仅在本协议明确列明的事项和范围内，后签文件对先前文件构成变更。",)),
        ContractSection("订单和变更机制", ("具体项目通过有效订单或变更单落实标的、进度、价格和验收。未形成订单时，框架安排不当然产生最低采购或排他义务。",)),
        ContractSection("多方职责边界", ("各方分别对自身承诺、人员、数据和交付负责；一方协调、代付或接收成果的行为，不当然使其对其他方债务承担连带责任。",)),
        ContractSection("结算和发票", ("价款调整应对应明确的工作量和定价依据。付款路径、发票开具方和最终责任方应保持一致，代收代付须留存有效凭证。",)),
        ContractSection("存续和退出", ("未被修改的保密、知识产权、质量保证、争议解决和已发生债权债务继续有效。退出方应完成数据、资料和在途事项交接。",)),
    )


ScenarioBuilder = Callable[[ContractCase], tuple[ContractSection, ...]]

BUILDERS: dict[str, ScenarioBuilder] = {
    "采购、供货与销售": _sale_sections,
    "技术、软件与数据服务": _technology_sections,
    "运维、咨询、培训与业务外包": _service_sections,
    "房屋、设备与场地租赁": _lease_sections,
    "建设、装修、监理与承揽": _construction_sections,
    "人力资源、保险与员工服务": _employee_service_sections,
    "保密、数据处理与知识产权": _confidentiality_sections,
    "框架订单、补充协议与多方合作": _related_document_sections,
}


def _annexes(case: ContractCase) -> tuple[ContractSection, ...]:
    return tuple(
        ContractSection(
            heading=f"附件{index}：{name}",
            paragraphs=(
                f"本附件对应 {case.case_id} 的{name}，用于细化{case.truth['subject']}的履约口径。",
                "附件中的空白栏位应在实际业务确认后填写；本合成样本不包含真实签章、账号或个人身份信息。",
            ),
            rows=(("项目", "约定内容", "确认记录"), (name, "按业务事实和验收记录执行", "________")),
        )
        for index, name in enumerate(case.related_documents, start=1)
    )


def build_contract(case: ContractCase) -> ContractDocument:
    """从一条冻结案例构建确定性的合同文档结构。"""
    try:
        scenario_sections = BUILDERS[case.scenario](case)
    except KeyError as exc:
        raise ValueError(f"不支持的合同场景：{case.scenario}") from exc

    state_labels = {
        "internal_draft": "内部讨论稿",
        "signed_final": "签署归档文本",
        "stamped_scan": "签章回传归档件（无真实印章）",
        "supplier_draft": "供应商提供版本",
        "legal_redline": "法务修订稿",
        "supplier_final": "供应商定稿",
        "online_order_final": "在线订购归档条款",
    }
    header_lines = (
        "合成测试样本，仅用于系统验收",
        f"案例编号：{case.case_id}",
        f"合同编号：SYN-{case.case_id[3:]}-2026",
        f"文本状态：{state_labels.get(case.document_state, case.document_state)}",
    )
    sections = (
        _party_section(case),
        *_commercial_sections(case),
        *scenario_sections,
        *_legal_sections(case),
    )
    return ContractDocument(
        case_id=case.case_id,
        title=case.title,
        header_lines=header_lines,
        sections=sections,
        annexes=_annexes(case),
    )
