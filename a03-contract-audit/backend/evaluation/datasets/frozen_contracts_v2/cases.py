"""v2 案例事实：复用已冻结交易事实，显式增加真实性覆盖。"""
from __future__ import annotations

from types import MappingProxyType

from evaluation.datasets.frozen_contracts_v1 import DATASET_ROOT as V1_DATASET_ROOT
from evaluation.datasets.frozen_contracts_v1.models import load_cases as load_v1_cases

from .models import AnnexSpec, ConflictPair, ContractCase, RevisionSet, RiskClause


STYLE_SEQUENCE = (
    *("buyer_standard",) * 6,
    *("supplier_standard",) * 5,
    *("business_draft",) * 5,
    *("legal_redline",) * 4,
    *("model_contract",) * 5,
    *("online_terms",) * 3,
    *("framework_order",) * 4,
    *("master_supplement",) * 4,
    *("project_conditions",) * 4,
    *("industry_template",) * 3,
    *("customer_template",) * 4,
    *("short_order",) * 3,
)


ACTIONABLE_TEXTS = (
    "甲方有权依据内部验收记录单方认定不合格，并直接扣减该批次全部货款，乙方不得提出异议。",
    "乙方对任何原因造成的间接损失、停产损失及数据损失均不承担责任，累计责任以当月服务费为限。",
    "采购数量以甲方预测为准，乙方必须备货；甲方实际采购不足预测数量时不承担任何补偿责任。",
    "货物签收即视为质量、数量和性能全部验收合格，买方此后不得以隐蔽瑕疵为由要求退换。",
    "供应方可以根据原材料价格变化自行调整含税单价，调整通知送达后立即适用于未交付订单。",
    "逾期付款每日按应付金额千分之三计收违约金，供货方迟延交付不承担对等违约责任。",
    "客户连续五日未反馈即视为全部成果验收合格，服务方无需提交测试记录或缺陷关闭证明。",
    "服务方可以将生产数据用于模型训练、产品改进及其他客户项目，无需再次取得客户授权。",
    "系统可用率由服务方后台记录确定，服务方有权自行排除维护、网络和第三方故障时段。",
    "定制开发形成的全部代码和文档归服务方所有，客户仅在合同期内取得不可转移的使用许可。",
    "任何需求说明均不构成固定范围，服务方可就其认为新增的工作直接按人日单价计费。",
    "客户提前解除合同的，应支付剩余全部服务费；服务方提前解除仅需退还尚未发生的费用。",
    "出租人可根据园区经营需要单方调整管理费和能耗附加费，承租人不得因此解除合同。",
    "承租人逾期一日出租人即可停水停电并进入场地处置物品，由此损失全部由承租人承担。",
    "租赁物存在权属争议、抵押或查封时，出租人不承担承租人停业及搬迁产生的任何损失。",
    "发包人可随时调整工程范围，承包人应先行施工，价款是否调整由发包人最终决定。",
    "工程未经发包人指定人员签字即不得计量，但发包人未在期限内签字不视为默认确认。",
    "承包人承担施工现场发生的一切事故责任，包括发包人指令和场地既有缺陷造成的事故。",
    "隐蔽工程覆盖后二十四小时内未提出异议即视为合格，委托人无权要求开拆复验。",
    "候选人入职即产生全额服务费，无论其是否通过试用期，招聘企业均不得要求免费替换。",
    "保险人可依据其内部医疗审核规则拒绝赔付，该规则无需作为合同附件向投保单位披露。",
    "服务商可以留存员工健康信息用于后续营销，并可向关联公司共享，无需另行告知员工。",
    "接收方违反任何保密义务均应支付五百万元违约金，披露方无需证明实际损失。",
    "数据提供方保证全部数据绝对准确完整，并承担模型研发方使用数据产生的所有第三方索赔。",
    "模型研发方永久独占全部联合成果，数据提供方不得自行使用或委托第三方开发相似模型。",
    "框架有效期内甲方不得与任何第三方开展同类业务，但乙方不承诺最低订单或服务能力。",
    "补充协议与原合同不一致的事项均以乙方系统记录为准，乙方可以随时更新系统记录。",
    "任何争议均由模板提供方住所地法院管辖，另一方承担模板提供方全部律师费和差旅费。",
)


NEGOTIATED_TEXTS = (
    "任一方累计赔偿责任以合同含税总价为限，但故意、重大过失、知识产权侵权和数据泄露责任不受该限额约束。",
    "验收期限为十个工作日；逾期未反馈可视为阶段验收，但服务方仍应对隐蔽缺陷和安全漏洞承担责任。",
    "原材料指数波动超过百分之五时任一方均可提出调价，调整须经双方书面确认后适用于后续订单。",
    "客户可以因业务调整提前终止未启动的服务，并支付已经完成且经确认的工作量及不可退第三方费用。",
    "供应商可使用经书面批准的分包商，但应披露分包范围，并对分包交付和数据安全承担连带责任。",
    "租金每两年按约定比例调整，出租人至少提前六十日通知；调整超过上限时承租人可以无责解除。",
    "施工范围变更应先签署变更单；紧急情形可先实施，但双方须在五个工作日内补充确认工程量。",
    "违约金按逾期金额每日万分之五计算，累计不超过对应价款百分之十，守约方可证明超额实际损失。",
    "数据仅限本项目处理；经匿名化且无法复原的数据用于统计研究前，仍须通过双方安全评审。",
    "背景知识产权归原权利人，定制成果归客户所有，通用工具由服务方保留并授予客户永久使用权。",
    "自动续期前任一方可提前三十日书面拒绝续期，服务方应在终止后完成数据导出和迁移协助。",
    "员工名单由投保单位加密提供，保险人仅为承保理赔处理，并在法定留存期届满后删除。",
    "保密违约金为五十万元；若明显低于或高于实际损失，任一方可依法请求调整。",
    "订单与框架协议冲突时订单仅在明确列明变更条款的范围内优先，其余事项继续适用框架协议。",
)


CONFLICTS = {
    4: ConflictPair("正文第六条", "全部设备应于2026年11月20日前交付。", "附件二进度表", "最终批次应于2026年12月15日前交付。", "附件二经双方后签确认，在交付日期事项上优先。", "最终批次应于2026年12月15日前交付。"),
    14: ConflictPair("正文验收条款", "模型准确率达到92%即通过终验。", "附件模型评测规范", "模型准确率达到95%且召回率不低于90%方可通过终验。", "专用技术附件优先于正文概括约定。", "模型准确率达到95%且召回率不低于90%方可通过终验。"),
    25: ConflictPair("正文费用条款", "媒体投放第三方费用按实际发生额结算，不另加管理费。", "附件媒体报价政策", "媒体投放费用按实际发生额另加百分之八采购管理费。", "双方后签的正文补充条款优先于报价政策。", "媒体投放第三方费用按实际发生额结算，不另加管理费。"),
    33: ConflictPair("正文服务等级", "月度可用率低于99.9%时按当月机柜费百分之十抵扣。", "附件SLA", "月度可用率低于99.5%时按当月机柜费百分之五抵扣。", "专用SLA与正文冲突时以正文为准。", "月度可用率低于99.9%时按当月机柜费百分之十抵扣。"),
    40: ConflictPair("正文施工范围", "屋面全部节点及天沟均包含在合同总价内。", "附件报价清单", "天沟修缮不在本次报价范围，发生时另行计价。", "图纸范围与报价清单冲突时须签证确认，未确认前正文范围优先。", "屋面全部节点及天沟均包含在合同总价内。"),
    50: ConflictPair("原合同付款条款", "上线验收后支付合同价款的百分之九十。", "补充协议（二）", "试运行满三个月且完成安全测评后支付至合同价款的百分之九十。", "本补充协议明确变更的付款条件优先。", "试运行满三个月且完成安全测评后支付至合同价款的百分之九十。"),
}


REVISIONS = {
    13: RevisionSet("客户逾期五日未反馈即视为验收合格。", "客户逾期十个工作日未反馈可视为阶段验收，但不免除服务方缺陷修复责任。", "请业务确认默示验收期限及隐蔽缺陷责任。", "Codex（合成法务修订）", "2026-09-10T09:00:00Z"),
    31: RevisionSet("出租人可以随时调整物业管理费。", "物业管理费调整须提前六十日书面通知，年度涨幅不超过百分之五。", "增加调价上限和通知期限。", "Codex（合成法务修订）", "2026-09-10T09:10:00Z"),
    37: RevisionSet("承包人承担施工现场的一切责任。", "承包人对其施工组织和人员行为负责，发包人原因及既有场地缺陷按过错分担。", "责任范围应与控制能力相匹配。", "Codex（合成法务修订）", "2026-09-10T09:20:00Z"),
    46: RevisionSet("保密义务永久有效。", "商业秘密保密义务持续至信息依法公开，其他保密信息自披露之日起五年。", "区分商业秘密与一般保密信息。", "Codex（合成法务修订）", "2026-09-10T09:30:00Z"),
}


def _annexes(base) -> tuple[AnnexSpec, ...]:
    names = base.related_documents or ("履约数据表",)
    return tuple(
        AnnexSpec(
            name=name,
            version=f"V{index}.0",
            rows=(("业务项目", "约定值"), (str(base.truth["subject"]), str(base.truth["amount"] or "据实结算"))),
        )
        for index, name in enumerate(names, start=1)
    )


def load_cases() -> tuple[ContractCase, ...]:
    result = []
    for index, base in enumerate(load_v1_cases(V1_DATASET_ROOT / "cases.json"), start=1):
        risk_level = "actionable" if index <= 28 else "negotiated" if index <= 42 else "baseline"
        risk_text = ACTIONABLE_TEXTS[index - 1] if risk_level == "actionable" else NEGOTIATED_TEXTS[index - 29] if risk_level == "negotiated" else None
        risk_clauses = () if risk_text is None else (
            RiskClause(
                clause_id=f"R2-{index:03d}-01",
                text=risk_text,
                risk_type=(base.risk_tags[0] if base.risk_tags else "权利义务失衡"),
                favored_party=(base.primary_roles[0] if risk_level == "actionable" else None),
                severity=("high" if risk_level == "actionable" else "medium"),
                review_reason=("条款可能造成权利义务明显失衡" if risk_level == "actionable" else "条款已通过例外和边界进行平衡"),
                evidence_location="特别约定",
            ),
        )
        result.append(ContractCase(
            case_id=f"F2-{index:03d}",
            title=base.title,
            scenario=base.scenario,
            contract_type=base.contract_type,
            format=base.format,
            render_mode=base.render_mode,
            document_state=("legal_redline" if index in REVISIONS else base.document_state),
            drafting_style=STYLE_SEQUENCE[index - 1],
            risk_level=risk_level,
            primary_roles=base.primary_roles,
            parties=base.parties,
            truth=MappingProxyType(dict(base.truth)),
            target_pages=base.target_pages,
            risk_clauses=risk_clauses,
            conflicts=((CONFLICTS[index],) if index in CONFLICTS else ()),
            annexes=_annexes(base),
            revision_set=REVISIONS.get(index),
        ))
    return tuple(result)
