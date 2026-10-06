"""把统一证据快照渲染为可核查的 Excel 与中文 Word。"""
import io
import json
import re
import math

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from .excel_decision import build_overview, add_review_sheets
from .word_decision import export_decision_docx

STATUS = {"done": "处理完成", "review_required": "待人工复核", "failed": "审查失败", "audit_failed": "审查失败", "queued": "排队中", "reviewing": "审查中", "parsing": "解析中", "validating": "校验中"}
LEVEL = {"high": "高风险", "medium": "中风险", "low": "低风险"}
REVIEW = {"pending": "待复核", "confirmed": "已确认", "ignored": "已忽略", "to_modify": "待修改"}
EVIDENCE = {"supported": "依据支持", "partially_supported": "部分支持", "unsupported": "缺少支持", "contradicted": "依据矛盾", "unclear": "待核实"}
AGENT = {"legal": "法务专家", "finance": "财务会计", "system": "规则校验"}


def clean(value):
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", str(value))


def location(risk):
    labels = []
    for evidence in risk.get("contract_evidence", []):
        if not isinstance(evidence, dict):
            continue
        label = str(evidence.get("clause_id") or "条款未编号")
        pages = set()
        for anchor in evidence.get("anchors", []):
            if isinstance(anchor, dict):
                page = anchor.get("page") or anchor.get("page_number")
                if page is not None:
                    pages.add(str(page))
        if pages:
            label += " · 第 " + ", ".join(sorted(pages)) + " 页"
        label += "（精确引文）" if evidence.get("match_type") == "exact_quote" else "（近似定位，需核对）"
        labels.append(label)
    return "；".join(labels) or "尚无可靠原文定位"


def sources(risk):
    lines = []
    for item in risk.get("rag_sources", []):
        if isinstance(item, dict):
            lines.append(clean(item.get("source") or item.get("title") or "来源待核实") + "：" + clean(item.get("content") or item.get("quote") or "正文待核实"))
    return "\n".join(lines) or "尚无可回读的检索来源"


def _sheet(wb, title, headers, rows, widths=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for values in rows:
        values = [v if isinstance(v, (int, float)) and not isinstance(v, bool) else clean(v) for v in values]
        parts = [([v[i:i + 30000] for i in range(0, len(v), 30000)] or [""]) if isinstance(v, str) else [v] for v in values]
        for index in range(max(len(p) for p in parts)):
            row = []
            for chunks in parts:
                value = chunks[0] if len(chunks) == 1 else (f"[分段 {index + 1}/{len(chunks)}] {chunks[index]}" if index < len(chunks) else "")
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                row.append(value)
            ws.append(row)
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="202622")
        cell.font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="微软雅黑", size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if cell.row % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F7F4EC")
            if cell.value in ("高风险", "审查失败"):
                cell.font = Font(name="微软雅黑", color="B63B38", bold=True)
    ws.freeze_panes = "C2" if len(headers) > 3 else "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    ws.print_title_rows = "1:1"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3 if len(headers) > 8 else ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.oddFooter.center.text = "第 &P 页 / &N 页"
    for i in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(i)].width = widths[i-1] if widths and i <= len(widths) else 25
    ws.row_dimensions[1].height = 32
    ws.sheet_view.zoomScale = 85
    ws.sheet_properties.tabColor = "AD321B"
    ws.print_area = ws.dimensions
    for cell in ws[1]:
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        lines = max(sum(max(1, math.ceil(len(part) * 1.7 / ws.column_dimensions[cell.column_letter].width)) for part in str(cell.value or "").split("\n")) for cell in row)
        ws.row_dimensions[row[0].row].height = min(240, max(24, lines * 15))
    return ws


def export_report_xlsx(snapshot):
    wb = Workbook()
    wb.remove(wb.active)
    build_overview(wb, snapshot)
    _sheet(wb, "合同清单", ["合同ID", "合同名称", "类型", "部门", "甲方", "标的", "收付款节点", "金额（原文）", "任务ID", "状态", "高风险", "中风险", "低风险", "覆盖", "质量说明", "乙方", "履行期限"], [
        [c["id"], c["filename"], c["contract_type"], c["department"], c["party_a"], c["subject"], c["payment_terms"], c["amount"], c["job_id"], STATUS.get(c["job_status"], "未审查"), c["risk_high"], c["risk_medium"], c["risk_low"], c["coverage"], c["review_reason"], (c.get("elements") or {}).get("party_b") or "待补充", (c.get("elements") or {}).get("duration") or "待补充"] for c in snapshot["contracts"]
    ], [12, 36, 18, 18, 30, 36, 65, 24, 12, 18, 12, 12, 12, 25, 55, 30, 36])
    _sheet(wb, "风险台账", ["合同", "风险ID", "负责智能体", "类别", "等级", "原文", "风险原因", "依据", "修改建议", "复核状态", "证据状态", "原文定位"], [
        [r["filename"], r["id"], AGENT.get(r["agent"], r["agent"]), r["category"], LEVEL.get(r["level"], r["level"]), r["original_text"], r["risk_reason"], r["basis"], r["suggestion"], REVIEW.get(r["review_status"], r["review_status"]), EVIDENCE.get(r["evidence_status"], r["evidence_status"]), location(r)] for r in snapshot["risks"]
    ], [36, 12, 18, 20, 14, 70, 55, 55, 55, 16, 18, 36])
    _sheet(wb, "证据索引", ["风险ID", "合同", "原文定位", "原文核验", "检索来源与正文", "依据支持关系"], [
        [r["id"], r["filename"], location(r), "已核验" if r["original_text_verified"] else "未核验", sources(r), r.get("support_validation_reason")] for r in snapshot["risks"]
    ], [12, 36, 40, 16, 95, 55])
    _sheet(wb, "整改跟踪", ["整改ID", "风险ID", "合同", "问题", "负责人", "状态", "截止日", "备注"], [
        [r["id"], r["risk_id"], r["contract"], r["risk"], r["owner"] or "未分派", r["status"], r["due"], r["note"]] for r in snapshot["rectifications"]
    ])
    matrix = _sheet(wb, "风险矩阵", ["合同ID", "合同", *snapshot["matrix"]["categories"]], [
        [r["contract_id"], r["filename"], *r["counts"]] for r in snapshot["matrix"]["rows"]
    ])
    if snapshot["matrix"]["categories"] and matrix.max_row > 1:
        matrix.conditional_formatting.add(f"C2:{get_column_letter(matrix.max_column)}{matrix.max_row}", ColorScaleRule(start_type="num", start_value=0, start_color="F1F5F6", end_type="max", end_color="E8A6A0"))
    _sheet(wb, "付款节点", ["合同", "节点原文", "条件", "比例", "基数", "说明"], [
        [c["filename"], e["quote"], e["condition"], e["percentage"], e["base"], c["payment_analysis"]["calculation"]]
        for c in snapshot["contracts"] for e in c.get("payment_analysis", {}).get("events", [])
    ], [35, 80, 25, 14, 25, 60])
    _sheet(wb, "口径说明", ["说明"], [[v] for v in ["本文件是生成时的固定审查快照。来源：本地合同、审查任务、风险与整改记录；报告编号用于校验预览一致性。", "无风险不等于合规，模型建议需人工复核。", "长文本按30000字符分段为连续行，其余字段重复便于核对；请按风险ID去重计数，摘要不重复统计。", *snapshot["notes"]]], [110])
    add_review_sheets(wb, snapshot, _sheet, location, sources)
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()



def export_report_docx(snapshot):
    return export_decision_docx(snapshot)
