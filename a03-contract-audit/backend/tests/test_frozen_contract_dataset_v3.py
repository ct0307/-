from __future__ import annotations

from pathlib import Path
from collections import Counter
from dataclasses import replace
from difflib import SequenceMatcher
from hashlib import sha256
import re

import pytest

from evaluation.datasets.frozen_contracts_v3.cases import load_cases
from evaluation.datasets.frozen_contracts_v3.models import load_profile


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v3"


def test_v3_module_is_independent_and_profile_is_fixed():
    profile = load_profile(DATASET_ROOT / "corpus-profile.json")

    assert profile.version == "3.0.0"
    assert profile.valid_count == 50
    assert profile.invalid_count == 2
    assert dict(profile.formats) == {
        "docx": 14,
        "text_pdf": 21,
        "scanned_or_mixed_pdf": 15,
    }
    assert sum(profile.drafting_styles.values()) == 50
    assert len(profile.drafting_styles) == 12

    cases = load_cases()
    assert len(cases) == 50
    source = (DATASET_ROOT / "cases.py").read_text(encoding="utf-8")
    assert "frozen_contracts_v1" not in source
    assert "frozen_contracts_v2" not in source


def test_v3_cases_are_explicit_and_business_complete():
    cases = load_cases()

    assert [case.case_id for case in cases] == [f"F3-{index:03d}" for index in range(1, 51)]
    assert Counter(case.scenario for case in cases) == {
        "procurement": 12,
        "technology": 10,
        "operations": 8,
        "leasing": 6,
        "construction": 5,
        "workforce": 4,
        "data_ip": 3,
        "framework": 2,
    }
    assert Counter(case.format for case in cases) == {
        "docx": 14,
        "text_pdf": 21,
        "pdf": 15,
    }
    assert Counter(case.risk_level for case in cases) == {
        "actionable": 28,
        "negotiated": 14,
        "baseline": 8,
    }
    assert sum(len(case.parties) >= 3 for case in cases) >= 5
    assert sum(case.truth.amount is None for case in cases) >= 10

    for case in cases:
        assert case.title and case.contract_type and case.drafting_style
        assert len(case.parties) >= 2
        assert len({party.role for party in case.parties}) == len(case.parties)
        assert all(party.name and party.address for party in case.parties)
        assert case.truth.subject
        assert case.truth.pricing
        assert case.truth.duration
        assert case.truth.payment_terms
        assert case.truth.delivery
        assert case.truth.acceptance
        assert case.truth.termination
        assert case.annex_types

    source = (DATASET_ROOT / "cases.py").read_text(encoding="utf-8")
    assert "for index in range" not in source
    assert "enumerate(" not in source
    assert source.count("ContractCase(") == 50


def test_v3_styles_have_substantive_differences_and_annexes_match_scenarios():
    from evaluation.datasets.frozen_contracts_v3.annexes import (
        ANNEX_SCHEMAS,
        SCENARIO_ALLOWED_ANNEXES,
        build_annexes,
    )
    from evaluation.datasets.frozen_contracts_v3.clauses import STYLE_PROFILES

    assert len(STYLE_PROFILES) == 12
    signatures = {
        (
            profile.section_order,
            profile.obligation_focus,
            profile.opening_pattern,
            profile.signature_pattern,
        )
        for profile in STYLE_PROFILES.values()
    }
    assert len(signatures) == 12
    assert all(len(profile.section_order) >= 8 for profile in STYLE_PROFILES.values())
    assert all(len(profile.obligation_focus) >= 3 for profile in STYLE_PROFILES.values())

    for case in load_cases():
        annexes = build_annexes(case)
        assert tuple(annex.annex_type for annex in annexes) == case.annex_types
        assert set(case.annex_types) <= SCENARIO_ALLOWED_ANNEXES[case.scenario]
        for annex in annexes:
            assert annex.columns == ANNEX_SCHEMAS[annex.annex_type]
            assert annex.rows and all(len(row) == len(annex.columns) for row in annex.rows)
            assert annex.columns != ("记录项目", "责任方", "业务凭证")


def test_v3_documents_meet_realistic_length_and_obligation_thresholds():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    for case in load_cases():
        document = build_contract(case)
        chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in document.plain_text)
        if case.length_class == "short":
            assert 1_200 <= chinese_count <= 1_800, case.case_id
        elif case.length_class == "long":
            assert chinese_count >= 6_000, case.case_id
        else:
            assert chinese_count >= 2_500, case.case_id

        substantive_sections = [section for section in document.sections if section.paragraphs]
        assert len(substantive_sections) >= 10, case.case_id
        paragraphs = [paragraph for section in document.sections for paragraph in section.paragraphs]
        assert len(paragraphs) == len(set(paragraphs)), case.case_id
        assert not hasattr(document, "target_pages")


def test_v3_render_modes_and_revision_xml(tmp_path):
    from zipfile import ZipFile

    import fitz

    from evaluation.datasets.frozen_contracts_v3.content import build_contract
    from evaluation.datasets.frozen_contracts_v3.ooxml import extract_revision_text
    from evaluation.datasets.frozen_contracts_v3.renderers import (
        render_docx,
        render_mixed_pdf,
        render_scanned_pdf,
        render_text_pdf,
    )

    cases = load_cases()
    revision_cases = [case for case in cases if case.revision_set]
    assert len(revision_cases) == 4
    assert all(case.format == "docx" for case in revision_cases)

    revision_case = revision_cases[0]
    docx_path = render_docx(build_contract(revision_case), tmp_path / "redline.docx", case=revision_case)
    with ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml")
        settings_xml = archive.read("word/settings.xml")
        assert b"w:trackRevisions" in settings_xml
        assert b"w:ins" in document_xml and b"w:del" in document_xml
        assert b"w:commentRangeStart" in document_xml
        assert "word/comments.xml" in archive.namelist()
    assert revision_case.revision_set.inserted_text in extract_revision_text(docx_path, accept_changes=True)

    native = next(case for case in cases if case.format == "text_pdf")
    scanned = next(case for case in cases if case.render_mode == "scanned")
    mixed = next(case for case in cases if case.render_mode == "mixed")
    native_path = render_text_pdf(build_contract(native), tmp_path / "native.pdf")
    scanned_path = render_scanned_pdf(build_contract(scanned), tmp_path / "scanned.pdf")
    mixed_path = render_mixed_pdf(build_contract(mixed), tmp_path / "mixed.pdf")
    with fitz.open(native_path) as pdf:
        assert pdf.page_count >= 2
        assert sum(len(page.get_text()) for page in pdf) > 1_000
    with fitz.open(scanned_path) as pdf:
        assert sum(len(page.get_text()) for page in pdf) == 0
        assert all(page.get_images() for page in pdf)
    with fitz.open(mixed_path) as pdf:
        text_lengths = [len(page.get_text()) for page in pdf]
        assert any(length > 0 for length in text_lengths)
        assert any(length == 0 for length in text_lengths)


def test_v3_pdf_annex_pagination_avoids_sparse_continuation_pages():
    import fitz

    from evaluation.datasets.frozen_contracts_v3.content import build_contract
    from evaluation.datasets.frozen_contracts_v3.renderers import _text_pdf_bytes

    cases = {case.case_id: case for case in load_cases()}
    for case_id in ("F3-014", "F3-037"):
        data = _text_pdf_bytes(build_contract(cases[case_id]))
        with fitz.open(stream=data, filetype="pdf") as pdf:
            content_blocks = [block for block in pdf[-1].get_text("blocks") if block[1] < 780]
            assert max(block[3] for block in content_blocks) >= 400, case_id


def test_v3_pdf_sections_do_not_leave_headings_at_page_bottom():
    import fitz

    from evaluation.datasets.frozen_contracts_v3.content import build_contract
    from evaluation.datasets.frozen_contracts_v3.renderers import _text_pdf_bytes

    cases = [case for case in load_cases() if case.format != "docx"]
    for case in cases:
        document = build_contract(case)
        headings = {section.heading for section in (*document.sections, *document.annexes)}
        with fitz.open(stream=_text_pdf_bytes(document), filetype="pdf") as pdf:
            for page in pdf:
                content = [block[4].strip() for block in page.get_text("blocks") if block[1] < 780]
                orphan = next((heading for heading in headings if content and content[-1].endswith(heading)), None)
                assert orphan is None, (case.case_id, orphan)


def test_v3_pdf_signature_tables_keep_all_parties_on_one_page():
    import fitz

    from evaluation.datasets.frozen_contracts_v3.content import build_contract
    from evaluation.datasets.frozen_contracts_v3.renderers import _text_pdf_bytes

    for case in (case for case in load_cases() if case.format != "docx"):
        with fitz.open(stream=_text_pdf_bytes(build_contract(case)), filetype="pdf") as pdf:
            signature_page = next(page.get_text() for page in pdf if "签约方" in page.get_text())
            signature_table = signature_page[signature_page.rfind("签约方"):]
            assert all(party.name in signature_table for party in case.parties), case.case_id


def test_v3_generation_freezes_50_plus_2_without_overwrite(tmp_path):
    from evaluation.datasets.frozen_contracts_v3.generate import generate_dataset

    v1_cases = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v1" / "cases.json"
    v2_cases = BACKEND_ROOT / "evaluation" / "datasets" / "frozen_contracts_v2" / "cases.py"
    before = {path: sha256(path.read_bytes()).hexdigest() for path in (v1_cases, v2_cases)}
    root = tmp_path / "frozen-contracts-v3"

    result = generate_dataset(root)

    assert result.valid_count == 50
    assert result.invalid_count == 2
    assert result.supplemental_count == 1
    assert len(result.manifest["files"]) == 53
    hashes = [row["sha256"] for row in result.manifest["files"]]
    assert len(hashes) == len(set(hashes))
    assert result.manifest["evidence_level"] == "construction_truth_only"
    assert result.manifest["formal_gold"] is False
    with pytest.raises(FileExistsError, match="冻结目录已存在"):
        generate_dataset(root)
    after = {path: sha256(path.read_bytes()).hexdigest() for path in (v1_cases, v2_cases)}
    assert after == before


def test_v3_validator_rejects_sparse_duplicate_or_mismatched_documents():
    from evaluation.datasets.frozen_contracts_v3.content import ContractDocument, build_contract
    from evaluation.datasets.frozen_contracts_v3.validate import validate_contract_documents

    cases = load_cases()
    documents = [build_contract(case) for case in cases]

    sparse = replace(documents[0], sections=documents[0].sections[:1], annexes=())
    reasons = validate_contract_documents(cases, [sparse, *documents[1:]])
    assert any("F3-001" in reason and "正文长度" in reason for reason in reasons)

    duplicate = replace(documents[1], sections=documents[0].sections, annexes=documents[0].annexes)
    reasons = validate_contract_documents(cases, [documents[0], duplicate, *documents[2:]])
    assert any("正文相似度过高" in reason for reason in reasons)

    mismatched_case = replace(cases[0], annex_types=("data_catalog",))
    mismatched_document = build_contract(mismatched_case)
    reasons = validate_contract_documents([mismatched_case], [mismatched_document])
    assert any("F3-001" in reason and "附件与场景不匹配" in reason for reason in reasons)


def test_v3_contract_lengths_stay_within_realistic_ranges():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    for case in load_cases():
        count = sum("\u4e00" <= char <= "\u9fff" for char in build_contract(case).plain_text)
        if case.length_class == "standard":
            assert 2_500 <= count <= 5_500, (case.case_id, count)
        elif case.length_class == "long":
            assert 6_000 <= count <= 10_000, (case.case_id, count)


def test_v3_risk_layers_and_conflicts_have_contract_evidence():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    cases = load_cases()
    assert sum(bool(case.conflicts) for case in cases) == 6
    for case in cases:
        document = build_contract(case)
        if case.risk_level in {"actionable", "negotiated"}:
            assert "特别责任安排" in document.plain_text, case.case_id
        for conflict in case.conflicts:
            assert conflict.text_a != conflict.text_b
            assert conflict.text_a in document.plain_text
            assert conflict.text_b in document.plain_text
            assert conflict.precedence_rule in document.plain_text
            assert conflict.effective_value in (conflict.text_a + conflict.text_b)


def test_v3_annexes_and_signature_blocks_look_like_business_documents():
    from evaluation.datasets.frozen_contracts_v3.annexes import ANNEX_NAMES, build_annexes
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    assert all(any("\u4e00" <= char <= "\u9fff" for char in name) for name in ANNEX_NAMES.values())
    for case in load_cases():
        expected_rows = {"short": 3, "standard": 4, "long": 6}[case.length_class]
        assert all(len(annex.rows) == expected_rows for annex in build_annexes(case))
        document = build_contract(case)
        signature = next(section for section in document.sections if section.heading == "签署页")
        assert signature.rows[0] == ("签约方", "授权代表", "签署日期", "盖章位置")
        assert len(signature.rows) == len(case.parties) + 1


def test_v3_annex_rows_use_specific_business_values():
    from evaluation.datasets.frozen_contracts_v3.annexes import build_annexes

    placeholder = re.compile(
        r"(?:经双方确认的.+\d+|本订单第\d+项|.+按本附件及对应业务记录执行)$"
    )
    for case in load_cases():
        for annex in build_annexes(case):
            for row in annex.rows:
                assert not any(placeholder.fullmatch(value) for value in row), (case.case_id, annex.annex_type, row)


def test_v3_key_annex_columns_use_values_matching_their_business_meaning():
    from evaluation.datasets.frozen_contracts_v3.annexes import build_annexes

    semantic_patterns = {
        "deliverable_list": {
            "格式": r"(?:DOCX|XLSX|PDF|PPTX|源代码|部署包|配置文件|图纸)",
            "提交阶段": r"(?:需求|设计|开发|联调|上线|试运行|初验|终验|移交|结项)",
        },
        "interface_list": {
            "调用方向": r"(?:调用|推送|回传|同步|双向)",
            "数据对象": r"(?:订单|客户|库存|主数据|结算|日志|人员|影像|标注|业务单据)",
            "频率": r"(?:实时|分钟|小时|每日|每周|批量|事件触发)",
            "鉴权方式": r"(?:OAuth|mTLS|签名|令牌|白名单|专线)",
        },
        "cloud_resource_list": {
            "资源类型": r"(?:计算|数据库|存储|负载均衡|缓存|容器|消息|日志)",
            "规格": r"(?:vCPU|核|GB|TB|实例|节点)",
            "计费方式": r"(?:包年|包月|按量|预留实例|阶梯计费)",
            "部署区域": r"(?:华东|可用区|同城机房|灾备机房)",
        },
        "service_catalog": {
            "服务窗口": r"(?:工作日|7[×x]24|每日|节假日|至|小时内|到场前|月末)",
            "交付频率": r"(?:实时|每日|每周|每月|每季度|按需|事件触发|按预约|每批|按订单|按退货)",
            "责任边界": r"(?:负责|不含|除外|由.+承担|限于)",
        },
        "variation_order": {
            "变更原因": r"(?:设计|图纸|现场|业主|材料|规范|工程量)",
            "价款影响": r"(?:增加|减少|暂估|不调整|人民币)",
            "工期影响": r"(?:延长|顺延|不影响|压缩)",
        },
        "food_price_list": {
            "品类": r"(?:蔬菜|水果|肉|禽|蛋|水产|乳品|粮油)",
            "计价单位": r"(?:千克|公斤|箱|件|袋)",
            "协议价": r"元/(?:千克|公斤|箱|件|袋)",
            "产地要求": r"(?:产地|基地|农场|屠宰|养殖|国产)",
        },
        "cold_chain_standard": {
            "超温处置": r"(?:隔离|拒收|复检|销毁|退货)",
        },
        "evaluation_form": {
            "评分方式": r"(?:百分制|五级量表|问卷|实操|考试|加权)",
        },
        "media_budget": {
            "媒体渠道": r"(?:微信|视频号|抖音|官网|信息流|搜索|户外)",
            "采购方式": r"(?:询价|比选|框架|竞价|直采)",
            "结算凭证": r"(?:排期|刊例|投放|发票|监测|验收)",
        },
        "bill_of_quantities": {
            "项目名称": r"(?:拆除|隔墙|风管|电缆|地坪|吊顶|基础|洁净|消防|喷淋|钢|螺栓|联动)",
        },
        "supervision_scope": {
            "工作方法": r"(?:旁站|巡视|平行检验|见证取样|审核|复核)",
        },
        "insured_roster_schema": {
            "传输方式": r"(?:加密|SFTP|专线|TLS|脱敏)",
        },
        "benefit_schedule": {
            "保障项目": r"(?:医疗|住院|门诊|重疾|意外|身故)",
        },
        "claims_sla": {
            "升级渠道": r"(?:热线|工单|邮件|专属|电话)",
        },
        "deletion_certificate": {
            "删除方式": r"(?:逻辑删除|物理擦除|密钥销毁|安全覆盖|介质销毁)",
        },
        "research_plan": {
            "研究任务": r"(?:配方|试验|小试|中试|工艺|稳定性)",
        },
        "product_price_list": {
            "型号": r"(?:系列|型号|[A-Z]{1,3}-?\d)",
        },
        "mould_spec": {
            "目标寿命": r"(?:次|模次|万模)",
        },
        "sla": {
            "服务指标": r"(?:可用性|响应|恢复|修复|接通|解决率|满意度)",
        },
        "security_schedule": {
            "安全要求": r"(?:认证|授权|加密|日志|审计|漏洞|补丁|备份|恢复)",
        },
        "data_catalog": {
            "保存期限": r"(?:合同|终止|届满|年|月|日)",
        },
        "data_processing_schedule": {
            "保留期限": r"(?:合同|终止|完成|年|月|日)",
        },
        "price_schedule": {
            "材料计价": r"(?:发票|市场价|信息价|采购价|核价|元/)",
        },
        "role_matrix": {
            "技能要求": r"(?:经验|证书|资质|熟练|掌握|能力)",
        },
        "candidate_process": {
            "个人信息要求": r"(?:授权|同意|加密|脱敏|删除|最小必要)",
        },
        "license_scope": {
            "许可期限": r"(?:年|月|日|合同|授权码)",
        },
    }

    checked = Counter()
    for case in load_cases():
        for annex in build_annexes(case):
            expected_columns = semantic_patterns.get(annex.annex_type, {})
            for row in annex.rows:
                values = dict(zip(annex.columns, row))
                for column, pattern in expected_columns.items():
                    checked[(annex.annex_type, column)] += 1
                    assert re.search(pattern, values[column]), (
                        case.case_id,
                        annex.annex_type,
                        column,
                        values[column],
                    )

    assert set(checked) == {
        (annex_type, column)
        for annex_type, columns in semantic_patterns.items()
        for column in columns
    }

    cases = {case.case_id: case for case in load_cases()}
    technical_rows = {
        case_id: next(
            annex.rows
            for annex in build_annexes(cases[case_id])
            if annex.annex_type == "technical_spec"
        )
        for case_id in ("F3-001", "F3-002", "F3-010")
    }
    assert any("定位精度" in value for row in technical_rows["F3-001"] for value in row)
    assert any("误检率" in value or "漏检率" in value for row in technical_rows["F3-002"] for value in row)
    assert any("功率" in value or "衰减" in value for row in technical_rows["F3-010"] for value in row)

    quantity_rows = {
        case_id: next(
            annex.rows
            for annex in build_annexes(cases[case_id])
            if annex.annex_type == "bill_of_quantities"
        )
        for case_id in ("F3-037", "F3-038", "F3-040")
    }
    assert any("洁净" in value or "风管" in value for row in quantity_rows["F3-037"] for value in row)
    assert any("消防" in value or "喷淋" in value for row in quantity_rows["F3-038"] for value in row)
    assert any("钢" in value or "螺栓" in value for row in quantity_rows["F3-040"] for value in row)


def test_v3_representative_annexes_preserve_case_specific_trade_logic():
    from evaluation.datasets.frozen_contracts_v3.annexes import build_annexes

    cases = {case.case_id: case for case in load_cases()}

    warehouse = {annex.annex_type: annex for annex in build_annexes(cases["F3-029"])}
    warehouse_services = "".join(value for row in warehouse["service_catalog"].rows for value in row)
    assert all(keyword in warehouse_services for keyword in ("入库", "上架", "拣选", "盘点", "退货"))
    assert "平台故障" not in warehouse_services and "第三方软件" not in warehouse_services
    warehouse_kpis = "".join(value for row in warehouse["warehouse_kpi"].rows for value in row)
    assert all(keyword in warehouse_kpis for keyword in ("入库", "库存", "出库", "破损", "盘点"))
    warehouse_orders = "".join(value for row in warehouse["order_template"].rows for value in row)
    assert all(keyword in warehouse_orders for keyword in ("装卸", "仓储", "拣选", "配送"))
    transport_rows = warehouse["transport_price_list"].rows
    assert transport_rows == (
        ("杭州至宁波", "4.2米厢式货车", "元/车次", "人民币1,650元"),
        ("杭州至温州", "6.8米厢式货车", "元/车次", "人民币3,600元"),
        ("杭州至金华", "9.6米高栏车", "元/车次", "人民币2,950元"),
        ("宁波至台州", "冷藏车", "元/车次", "人民币3,200元"),
        ("嘉兴至湖州", "新能源轻型货车", "元/车次", "人民币1,280元"),
        ("浙江省内临时线路", "13米半挂车", "元/车公里", "人民币12.50元"),
    )

    construction = {annex.annex_type: annex for annex in build_annexes(cases["F3-037"])}
    quantity_rows = construction["bill_of_quantities"].rows
    assert quantity_rows[1][2:4] == ("平方米", "2,150")
    assert quantity_rows[3][2:4] == ("米", "3,600")
    assert quantity_rows[4][2:4] == ("平方米", "2,400")
    schedule = "".join(value for row in construction["construction_schedule"].rows for value in row)
    assert all(keyword in schedule for keyword in ("图纸会审", "材料报验", "隐蔽验收", "送电条件"))
    safety = "".join(value for row in construction["safety_schedule"].rows for value in row)
    assert all(keyword in safety for keyword in ("动火", "高处", "临时用电", "吊装", "受限空间"))
    assert "费用由责任方承担" not in safety and "保留完整审计记录" not in safety

    vehicle = {annex.annex_type: annex for annex in build_annexes(cases["F3-036"])}
    mileage_index = vehicle["vehicle_register"].columns.index("交付里程")
    mileages = [row[mileage_index] for row in vehicle["vehicle_register"].rows]
    assert all(re.fullmatch(r"\d{1,3}(?:,\d{3})*公里", mileage) for mileage in mileages)
    changes = "".join(value for row in vehicle["supplement_change_list"].rows for value in row)
    assert all(keyword in changes for keyword in ("车辆清单", "租期", "租金", "维保"))


def test_v3_sections_avoid_repeated_boilerplate_and_near_duplicates():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    repeated_boilerplate = (
        "承担该项义务的一方应在约定时点提交完整、可追溯且足以复核的资料",
        "负有通知、审批、交付、审核或付款义务的一方应通过合同列明的渠道完成",
    )
    for case in load_cases():
        document = build_contract(case)
        assert not any(phrase in document.plain_text for phrase in repeated_boilerplate), case.case_id
        paragraphs = [
            paragraph
            for section in document.sections
            for paragraph in section.paragraphs
            if len(paragraph) >= 80
        ]
        similarities = (
            SequenceMatcher(None, left, right).ratio()
            for index, left in enumerate(paragraphs)
            for right in paragraphs[index + 1:]
        )
        assert max(similarities, default=0.0) < 0.88, case.case_id


def test_v3_validator_accepts_chinese_annex_titles():
    from evaluation.datasets.frozen_contracts_v3.content import build_contract
    from evaluation.datasets.frozen_contracts_v3.validate import validate_contract_documents

    cases = load_cases()
    reasons = validate_contract_documents(cases, [build_contract(case) for case in cases])
    assert not [reason for reason in reasons if "正文附件引用不完整" in reason]


def test_structured_extractor_meets_construction_truth_baseline():
    """构造真值仅用于工程回归，不代表正式法律金标准。"""
    from app.services.parser.elements import extract_element_result
    from app.services.parser.extractor import DocumentParseResult
    from evaluation.datasets.frozen_contracts_v1.precheck import (
        evaluate_construction_truth,
    )
    from evaluation.datasets.frozen_contracts_v3.content import build_contract

    truth_rows = []
    predictions = {}
    for case in load_cases():
        text = build_contract(case).plain_text
        result = extract_element_result(DocumentParseResult(text=text, source="native"))
        truth_rows.append({
            "case_id": case.case_id,
            "gold": dict(case.truth.evaluation_projection(case.parties)),
        })
        predictions[case.case_id] = result.values

    report = evaluate_construction_truth(truth_rows, predictions)

    assert report["overall"]["f1"] >= 0.80
    assert all(item["f1"] > 0 for item in report["by_field"].values())
