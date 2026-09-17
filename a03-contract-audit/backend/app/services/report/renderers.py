"""把统一证据快照渲染为可核查的 Excel 与中文 Word。"""
import io
import json
import re
import math

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

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
        cell.fill = PatternFill("solid", fgColor="163B4C")
        cell.font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="微软雅黑", size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if cell.row % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F1F5F6")
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
    ws.row_dimensions[1].height = 26
    for row in ws.iter_rows(min_row=2):
        lines = max(sum(max(1, math.ceil(len(part) * 1.7 / ws.column_dimensions[cell.column_letter].width)) for part in str(cell.value or "").split("\n")) for cell in row)
        ws.row_dimensions[row[0].row].height = min(240, max(24, lines * 15))
    return ws


def export_report_xlsx(snapshot):
    wb = Workbook()
    wb.remove(wb.active)
    s = snapshot["summary"]
    summary = _sheet(wb, "摘要", ["指标", "快照值"], [
        ("报告编号", snapshot["report_id"]), ("生成时间（UTC）", snapshot["generated_at"]),
        ("合同数", s["total"]), ("处理完成", s["completed"]), ("待人工复核", s["review_required"]),
        ("失败", s["failed"]), ("未审查", s["unreviewed"]), ("进行中", s.get("running", 0)),
        ("风险总数", s["risks"]), ("高风险", s["high"]), ("中风险", s["medium"]), ("低风险", s["low"]),
        ("原文与依据已核验", s["supported"]),
    ], [30, 72])
    chart = BarChart()
    chart.title = "所选合同风险分布"
    chart.add_data(Reference(summary, min_col=2, min_row=11, max_row=13))
    chart.set_categories(Reference(summary, min_col=1, min_row=11, max_row=13))
    chart.legend = None
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.y_axis.title = "风险条数"
    chart.x_axis.tickLblPos = "nextTo"
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    chart.dataLabels.showCatName = True
    chart.dataLabels.dLblPos = "outEnd"
    chart.width, chart.height = 17, 9
    for index, color in enumerate(("B63B38", "BE8A32", "438571")):
        point = DataPoint(idx=index)
        point.graphicalProperties.solidFill = color
        chart.series[0].data_points.append(point)
    summary.add_chart(chart, "D3")
    _sheet(wb, "合同清单", ["合同ID", "合同名称", "类型", "部门", "甲方", "标的", "收付款节点", "金额（原文）", "任务ID", "状态", "高风险", "中风险", "低风险", "覆盖", "质量说明"], [
        [c["id"], c["filename"], c["contract_type"], c["department"], c["party_a"], c["subject"], c["payment_terms"], c["amount"], c["job_id"], STATUS.get(c["job_status"], "未审查"), c["risk_high"], c["risk_medium"], c["risk_low"], c["coverage"], c["review_reason"]] for c in snapshot["contracts"]
    ], [12, 36, 18, 18, 30, 36, 65, 24, 12, 18, 12, 12, 12, 25, 55])
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
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _table(doc, headers, rows):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Shading Accent 1"
    table.autofit = False
    widths = [Cm(4), Cm(13)] if len(headers) == 2 else [Cm(17 / len(headers))] * len(headers)
    for column, width in zip(table.columns, widths):
        column.width = width
    for cell, value, width in zip(table.rows[0].cells, headers, widths):
        cell.width = width
        cell.text = clean(value)
    repeat = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for values in rows:
        for cell, value, width in zip(table.add_row().cells, values, widths):
            cell.width = width
            cell.text = clean(value)
    return table


def export_report_docx(snapshot):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2)
    for style_name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[style_name]
        style.font.name = "微软雅黑"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "微软雅黑")
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.styles["Normal"].paragraph_format.space_after = Pt(7)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.2
    doc.styles["Title"].font.color.rgb = RGBColor.from_string("163B4C")
    section.header.paragraphs[0].text = "契鉴  /  合同审查与证据追溯"
    footer = section.footer.paragraphs[0]
    footer.add_run("审查建议供人工决策参考  ·  第 ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" 页")
    doc.add_paragraph("合同审查证据报告", "Title")
    doc.add_paragraph("单合同诊断" if len(snapshot["contracts"]) == 1 else "合同组合分析", "Subtitle")
    doc.add_paragraph(f"报告编号：{snapshot['report_id'][:20]}\n生成时间（UTC）：{snapshot['generated_at']}")
    s = snapshot["summary"]
    doc.add_heading("一、决策摘要", 1)
    _table(doc, ["所选合同", "高风险条款", "待人工复核合同", "审查失败"], [[s["total"], s["high"], s["review_required"], s["failed"]]])
    doc.add_paragraph(f"本次范围共 {s['total']} 份合同、{s['risks']} 条风险；其中 {s['supported']} 条已同时完成原文定位与依据支持核验。请优先复核高风险、覆盖不足及证据不明确的结果。")
    doc.add_heading("二、合同要素与审查质量", 1)
    for c in snapshot["contracts"]:
        doc.add_heading(clean(c["filename"]), 2)
        _table(doc, ["项目", "记录"], [("甲方", c["party_a"]), ("合同标的", c["subject"]), ("收付款节点", c["payment_terms"]), ("金额（原文）", c["amount"]), ("部门／类型", f"{c['department']} / {c['contract_type']}"), ("审查任务／代次", f"{c['job_id']} / {c['audit_generation']}"), ("状态", STATUS.get(c["job_status"], "未审查")), ("覆盖信息", c["coverage"] or "暂无覆盖信息"), ("质量说明", c["review_reason"] or "未提供额外说明")])
        analysis = c.get("payment_analysis")
        if analysis:
            doc.add_heading("收付款节点与逻辑校验", 3)
            doc.add_paragraph(clean(analysis["calculation"]))
            for event in analysis["events"]:
                percentage = f"{event['percentage']}%" if event['percentage'] is not None else "比例未明确"
                doc.add_paragraph(f"{event['condition']} → {percentage}\n{event['quote']}")
            for issue in analysis.get("issues", []):
                doc.add_paragraph(clean(issue["message"]))
                for quote in issue.get("quotes", []):
                    doc.add_paragraph("对照原文：" + clean(quote))
    doc.add_heading("三、多维风险对照", 1)
    _table(doc, ["等级", "条数"], [("高风险", s["high"]), ("中风险", s["medium"]), ("低风险", s["low"])])
    # 每组最多三个类别，避免横向挤压中文原文。
    for start in range(0, len(snapshot["matrix"]["categories"]), 3):
        categories = snapshot["matrix"]["categories"][start:start + 3]
        _table(doc, ["合同", *categories], [[row["filename"], *row["counts"][start:start + 3]] for row in snapshot["matrix"]["rows"]])
    for row in snapshot["matrix"]["rows"]:
        parts = [f"{cat} {count} 条" for cat, count in zip(snapshot["matrix"]["categories"], row["counts"]) if count]
        doc.add_paragraph(clean(row["filename"]) + "：" + ("；".join(parts) or "当前任务无可展示风险，不代表合规确认"))
    doc.add_heading("四、逐项风险与证据", 1)
    if not snapshot["risks"]:
        doc.add_paragraph("当前范围暂无风险记录，请结合任务状态与覆盖信息判断。")
    for r in sorted(snapshot["risks"], key=lambda row: ({"high": 0, "medium": 1, "low": 2}.get(row["level"], 3), row["id"])):
        doc.add_heading(f"R{r['id']} · {clean(r['category'])} · {LEVEL.get(r['level'], r['level'])}", 2)
        doc.add_paragraph(f"合同：{clean(r['filename'])}  |  发现方：{AGENT.get(r['agent'], r['agent'])}")
        for label, value in [("原文定位", location(r)), ("原文", r["original_text"]), ("风险原因", r["risk_reason"]), ("依据", r["basis"]), ("核验状态", EVIDENCE.get(r["evidence_status"], r["evidence_status"])), ("检索来源", sources(r)), ("修改建议", r["suggestion"]), ("复核状态", REVIEW.get(r["review_status"], r["review_status"]))]:
            paragraph = doc.add_paragraph()
            paragraph.add_run(label + "：").bold = True
            paragraph.add_run(clean(value))
    doc.add_heading("五、整改行动清单", 1)
    if snapshot["rectifications"]:
        _table(doc, ["风险", "责任人", "截止日", "状态"], [[f"R{r['risk_id']} {r['risk']}", r["owner"] or "未分派", r["due"], r["status"]] for r in snapshot["rectifications"]])
    else:
        doc.add_paragraph("当前范围暂无已关联的整改任务。请复核风险后分派负责人和截止日期。")
    doc.add_heading("六、范围与口径", 1)
    for note in snapshot["notes"]:
        doc.add_paragraph(clean(note))
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()
