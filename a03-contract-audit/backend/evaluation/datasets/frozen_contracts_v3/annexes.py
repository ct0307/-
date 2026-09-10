"""按业务场景生成专属附件，不使用通用测试记录表。"""
from __future__ import annotations

from .models import AnnexSpec, ContractCase


ANNEX_SCHEMAS = {
    "equipment_list": ("设备名称", "型号规格", "数量", "制造商", "交付批次"),
    "technical_spec": ("技术指标", "合同要求", "检验方法", "判定规则"),
    "acceptance_plan": ("验收阶段", "前置条件", "测试内容", "签署文件"),
    "delivery_schedule": ("批次", "计划日期", "交付地点", "数量或范围"),
    "material_price_list": ("物料编码", "名称规格", "计价单位", "含税单价", "价格有效期"),
    "quality_standard": ("检验项目", "技术标准", "抽样比例", "不合格处理"),
    "order_template": ("订单编号", "标的及规格", "数量", "单价", "要求交期"),
    "import_documents": ("单证名称", "提供方", "提供时点", "用途"),
    "goods_list": ("品名", "规格或尺码", "数量", "单价", "交货批次"),
    "sealed_sample_standard": ("样品编号", "材质或颜色", "确认日期", "封存位置"),
    "pricing_formula": ("价格要素", "基准值", "调整公式", "数据来源"),
    "food_price_list": ("品类", "规格等级", "计价单位", "协议价", "产地要求"),
    "cold_chain_standard": ("品类", "装运温度", "交付温度", "超温处置"),
    "store_schedule": ("门店", "送货窗口", "收货联系人", "特殊要求"),
    "catalog_rules": ("目录类别", "上架规则", "调价通知期", "替代品规则"),
    "delivery_service_level": ("区域", "截单时间", "承诺时效", "超时补救"),
    "account_matrix": ("账号角色", "权限范围", "授权人", "复核周期"),
    "mould_spec": ("模具编号", "制件名称", "型腔数", "目标寿命", "验收基准"),
    "milestone_plan": ("里程碑", "计划日期", "交付成果", "确认责任人"),
    "deliverable_list": ("成果编号", "成果名称", "格式", "提交阶段", "验收依据"),
    "acceptance_cases": ("用例编号", "业务场景", "预期结果", "通过条件"),
    "interface_list": ("接口编号", "调用方向", "数据对象", "频率", "鉴权方式"),
    "cloud_resource_list": ("资源类型", "规格", "数量", "计费方式", "部署区域"),
    "sla": ("服务指标", "目标值", "统计口径", "未达标补救"),
    "security_schedule": ("控制域", "安全要求", "责任方", "验证证据"),
    "data_catalog": ("数据集", "字段范围", "敏感级别", "提供频率", "保存期限"),
    "requirements_baseline": ("需求编号", "功能描述", "优先级", "验收用例"),
    "data_processing_schedule": ("处理活动", "处理目的", "数据范围", "保留期限"),
    "model_metrics": ("指标", "最低值", "评测数据", "计算方法"),
    "disaster_recovery_test": ("演练场景", "RPO", "RTO", "通过条件"),
    "service_catalog": ("服务项", "服务窗口", "交付频率", "责任边界"),
    "staffing_plan": ("岗位", "人数", "投入比例", "最低资历", "到岗日期"),
    "monthly_report": ("报告模块", "统计周期", "数据来源", "确认人"),
    "consultant_roster": ("角色", "专业方向", "投入天数", "替换条件"),
    "training_plan": ("期次", "课程", "对象", "课时", "地点"),
    "trainer_roster": ("讲师", "专业资历", "负责课程", "备选讲师"),
    "evaluation_form": ("评价维度", "权重", "评分方式", "合格线"),
    "content_calendar": ("发布日期", "渠道", "内容主题", "审核节点"),
    "media_budget": ("媒体渠道", "预算", "采购方式", "结算凭证"),
    "asset_register": ("资产编号", "资产名称", "型号", "数量", "所在位置"),
    "maintenance_plan": ("设备或系统", "维护周期", "维护内容", "停机窗口"),
    "authorization_matrix": ("事项", "发起人", "审核人", "批准权限"),
    "warehouse_kpi": ("指标", "目标值", "取数系统", "扣减规则"),
    "transport_price_list": ("线路", "车型", "计费单位", "含税单价"),
    "rent_schedule": ("期次", "付款日", "租金", "本金或服务费"),
    "delivery_certificate": ("交付对象", "交付日期", "状态", "接收确认"),
    "premises_plan": ("区域", "面积", "用途", "附属设施"),
    "handover_list": ("交接项目", "数量或读数", "现状", "双方确认"),
    "supplement_change_list": ("原条款", "变更内容", "生效日", "适用范围"),
    "vehicle_register": ("车辆编号", "车型", "车架号后六位", "交付里程"),
    "safety_schedule": ("危险作业", "控制措施", "审批人", "检查频次"),
    "bill_of_quantities": ("清单编码", "项目名称", "计量单位", "工程量", "综合单价"),
    "construction_schedule": ("节点", "计划开始", "计划完成", "前置工作"),
    "variation_order": ("变更编号", "变更原因", "价款影响", "工期影响", "批准人"),
    "inspection_plan": ("检验批", "检查项目", "标准", "见证方"),
    "price_schedule": ("工作类别", "计量规则", "人工单价", "材料计价"),
    "work_order": ("工单编号", "工作范围", "完成时限", "验收人"),
    "supervision_scope": ("阶段", "监理事项", "工作方法", "成果记录"),
    "report_schedule": ("报告名称", "提交频次", "提交日期", "接收人"),
    "role_matrix": ("岗位", "人数", "技能要求", "工作边界"),
    "replacement_rules": ("触发情形", "通知期限", "替换时限", "费用承担"),
    "compliance_schedule": ("合规事项", "责任方", "证明材料", "核查频次"),
    "candidate_process": ("阶段", "提交材料", "反馈时限", "个人信息要求"),
    "insured_roster_schema": ("字段", "用途", "敏感级别", "传输方式"),
    "benefit_schedule": ("保障项目", "保额或限额", "免赔条件", "等待期"),
    "claims_sla": ("理赔环节", "材料齐全标准", "处理时限", "升级渠道"),
    "processing_instruction": ("处理步骤", "允许操作", "禁止操作", "控制措施"),
    "deletion_certificate": ("数据范围", "删除时点", "删除方式", "证明责任人"),
    "research_plan": ("研究任务", "牵头方", "阶段成果", "完成日期"),
    "ip_schedule": ("成果类型", "背景权利", "新成果归属", "许可范围"),
    "license_scope": ("软件版本", "许可数量", "地域", "使用限制", "许可期限"),
    "product_price_list": ("产品编码", "型号", "经销价", "建议零售价", "有效期"),
}


SCENARIO_ALLOWED_ANNEXES = {
    "procurement": {"equipment_list", "technical_spec", "acceptance_plan", "delivery_schedule", "material_price_list", "quality_standard", "order_template", "import_documents", "goods_list", "sealed_sample_standard", "pricing_formula", "food_price_list", "cold_chain_standard", "store_schedule", "catalog_rules", "delivery_service_level", "account_matrix", "mould_spec", "milestone_plan"},
    "technology": {"deliverable_list", "milestone_plan", "acceptance_cases", "interface_list", "cloud_resource_list", "sla", "security_schedule", "data_catalog", "requirements_baseline", "data_processing_schedule", "model_metrics", "disaster_recovery_test", "equipment_list", "service_catalog"},
    "operations": {"service_catalog", "sla", "staffing_plan", "monthly_report", "deliverable_list", "milestone_plan", "consultant_roster", "training_plan", "trainer_roster", "evaluation_form", "content_calendar", "media_budget", "asset_register", "maintenance_plan", "authorization_matrix", "warehouse_kpi", "transport_price_list", "order_template", "data_processing_schedule"},
    "leasing": {"asset_register", "rent_schedule", "delivery_certificate", "premises_plan", "handover_list", "supplement_change_list", "maintenance_plan", "vehicle_register", "safety_schedule"},
    "construction": {"bill_of_quantities", "construction_schedule", "variation_order", "safety_schedule", "inspection_plan", "price_schedule", "work_order", "supervision_scope", "staffing_plan", "report_schedule"},
    "workforce": {"role_matrix", "staffing_plan", "replacement_rules", "compliance_schedule", "candidate_process", "insured_roster_schema", "benefit_schedule", "claims_sla"},
    "data_ip": {"data_catalog", "processing_instruction", "security_schedule", "deletion_certificate", "research_plan", "ip_schedule", "milestone_plan", "acceptance_cases", "license_scope", "delivery_certificate"},
    "framework": {"order_template", "product_price_list", "authorization_matrix", "supplement_change_list", "deliverable_list", "acceptance_cases"},
}


ANNEX_NAMES = {key: " ".join(part.capitalize() for part in key.split("_")) for key in ANNEX_SCHEMAS}


def _cell_value(case: ContractCase, column: str, row_index: int) -> str:
    number = row_index + 1
    if any(word in column for word in ("名称", "项目", "标的", "工作范围", "处理活动", "研究任务", "服务项")):
        return f"{case.truth.subject}（第{number}项）"
    if any(word in column for word in ("数量", "人数", "工程量", "许可数量")):
        return str(number * 2)
    if any(word in column for word in ("日期", "时点", "交期", "期限", "窗口")):
        return f"合同生效后{number * 10}日内"
    if any(word in column for word in ("金额", "预算", "单价", "租金", "经销价")):
        return f"人民币{number * 10_000:,}元"
    if any(word in column for word in ("责任方", "提供方", "牵头方", "批准人", "确认人", "接收人")):
        return case.parties[min(row_index, len(case.parties) - 1)].role
    if any(word in column for word in ("标准", "指标", "目标值", "通过条件", "验收依据", "判定规则")):
        return case.truth.acceptance
    if any(word in column for word in ("范围", "用途", "内容", "要求", "描述", "场景")):
        return case.truth.subject
    if any(word in column for word in ("编号", "编码")):
        return f"{case.case_id}-A{number:02d}"
    return f"经双方确认的{column}{number}"


def build_annexes(case: ContractCase) -> tuple[AnnexSpec, ...]:
    annexes = []
    for index, annex_type in enumerate(case.annex_types, start=1):
        columns = ANNEX_SCHEMAS[annex_type]
        rows = tuple(tuple(_cell_value(case, column, row_index) for column in columns) for row_index in range(2))
        annexes.append(AnnexSpec(
            annex_type=annex_type,
            name=ANNEX_NAMES[annex_type],
            version=f"V1.{index}",
            columns=columns,
            rows=rows,
            precedence="本附件就其专门事项与正文不一致时，以双方后签确认的专门约定为准。",
        ))
    return tuple(annexes)
