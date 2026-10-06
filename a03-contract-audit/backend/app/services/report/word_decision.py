"""管理速读与专业复核分层的中文Word报告。"""
import io
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .decision_brief import decision_brief, contract_facts, excerpt, value_text


def export_decision_docx(snapshot):
    from .renderers import clean, location, sources, STATUS, AGENT
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.7)
    section.left_margin = section.right_margin = Cm(1.8)
    section.header_distance = section.footer_distance = Cm(.8)
    for name in ["Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3"]:
        style = doc.styles[name]
        style.font.name = "微软雅黑"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "微软雅黑")
        style.font.color.rgb = RGBColor.from_string("202622")
    normal = doc.styles["Normal"]
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.15
    for name, size in [("Title", 23), ("Heading 1", 16), ("Heading 2", 12), ("Heading 3", 11)]:
        doc.styles[name].font.size = Pt(size)
        doc.styles[name].paragraph_format.keep_with_next = True
    doc.styles["Heading 1"].font.color.rgb = RGBColor.from_string("AD321B")
    # 清除本机默认模板的标题线和斜体，确保不同Office环境保持一致。
    for name in ["Title", "Subtitle"]:
        style = doc.styles[name]
        style.font.italic = False
        props = style.element.find(qn("w:pPr"))
        if props is not None:
            for border in list(props.findall(qn("w:pBdr"))):
                props.remove(border)
    section.header.paragraphs[0].text = "契鉴  |  合同审查与审批支持"
    section.header.paragraphs[0].runs[0].font.size = Pt(9)
    footer = section.footer.paragraphs[0]
    footer.add_run("固定快照 · 供授权人员复核与决策    ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" / ")
    total = OxmlElement("w:fldSimple")
    total.set(qn("w:instr"), "NUMPAGES")
    footer._p.append(total)

    def paragraph(label, value):
        p = doc.add_paragraph()
        p.add_run(label + "：").bold = True
        p.add_run(clean(value))
        return p

    def table(headers, rows, widths=None):
        t = doc.add_table(rows=1, cols=len(headers))
        t.autofit = False
        widths = widths or [17.4/len(headers)]*len(headers)
        for col, width in zip(t.columns, widths):
            col.width = Cm(width)
        repeat = OxmlElement("w:tblHeader")
        t.rows[0]._tr.get_or_add_trPr().append(repeat)
        for index, vals in enumerate([headers, *rows]):
            row = t.rows[0] if index == 0 else t.add_row()
            for cell, value, width in zip(row.cells, vals, widths):
                cell.width = Cm(width)
                cell.text = clean(value)
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "202622" if index == 0 else "F7F4EC" if index % 2 else "FFFFFF")
                cell._tc.get_or_add_tcPr().append(shade)
                for p in cell.paragraphs:
                    p.paragraph_format.space_after = Pt(4)
                    p.paragraph_format.space_before = Pt(4)
                    for run in p.runs:
                        run.font.size = Pt(9)
                        if index == 0:
                            run.bold = True
                            run.font.color.rgb = RGBColor(255,255,255)
        doc.add_paragraph().paragraph_format.space_after = Pt(1)
        return t

    s = snapshot["summary"]
    brief = decision_brief(snapshot)
    doc.add_paragraph("合同审查证据报告", "Title")
    doc.add_paragraph("审批摘要与专业核对附件", "Subtitle")
    paragraph("生成", brief["generated"] + "（北京时间）  |  报告 " + snapshot["report_id"][:12])
    doc.add_heading("一、管理速读", 1)
    paragraph("材料状态", brief["status"])
    doc.add_paragraph(brief["note"])
    if len(snapshot["contracts"]) == 1:
        facts = dict(contract_facts(snapshot["contracts"][0]))
        table(["业务信息", "本次合同"], [
            ("合同", excerpt(facts["合同名称"], 100)),
            ("交易双方", excerpt(facts["甲方"], 55) + " / " + excerpt(facts["乙方"], 55)),
            ("金额 / 期限", excerpt(facts["金额（原文）"], 55) + " / " + excerpt(facts["履行期限"], 55)),
            ("标的 / 付款", excerpt(facts["合同标的"], 80) + "\n" + excerpt(facts["付款安排"], 100)),
        ], [3.0,14.4])
    else:
        paragraph("范围", f"{s['total']}份合同。逐份双方、金额、期限与付款安排见第二部分；未经统一币种和基数确认，不汇总为风险敞口。")
    paragraph("风险与核验", f"{s['risks']}条风险记录（高{s['high']} / 中{s['medium']} / 低{s['low']}）；原文与依据同时核验{s['supported']}条；人工确认风险{brief['human_confirmed']}条。")
    doc.add_heading("优先关注事项", 2)
    for item in brief["focus"][:2]:
        r = item["risk"]
        paragraph(f"{item['ref']} · {item['level']} · {excerpt(r['category'],30)}", excerpt(r.get("risk_reason"), 75))
        paragraph("需处理", excerpt(r.get("suggestion"), 75))
    if not brief["focus"]:
        doc.add_paragraph("暂无未忽略的风险记录；请结合审查状态、覆盖信息和缺失要素判断，不能视为合规确认。")
    doc.add_paragraph("本节为节选，全部风险及完整建议见第三部分。系统不代替法务复核，也不自动作出签署决定。")

    if snapshot["contracts"]:
        doc.add_page_break()
    doc.add_heading("二、合同概况与材料完备度", 1)
    if not snapshot["contracts"]:
        doc.add_paragraph("当前范围没有合同，请确认筛选条件与访问权限。")
    for c in snapshot["contracts"]:
        doc.add_heading(f"C{c['id']} · {clean(c['filename'])}", 2)
        # 长付款条款用段落排版，避免表格跨页截断。
        facts = contract_facts(c)
        table(["要素", "记录（原文口径）"], [(k, v) for k,v in facts if k not in {"付款安排", "合同标的"}], [3.2,14.2])
        for k,v in facts:
            if k in {"合同标的", "付款安排"}:
                paragraph(k,v)
        paragraph("处理状态", STATUS.get(c.get("job_status"), "未审查"))
        paragraph("任务与范围", f"任务{c.get('job_id') or '未建立'} / 代次{c.get('audit_generation') or '未记录'}；覆盖信息：{clean(c.get('coverage') or '未提供，需确认')}。")
        paragraph("材料待核对", c.get("review_reason") or "系统未提供额外说明；不代表所有材料已经齐备。")
        analysis = c.get("payment_analysis") or {}
        if analysis.get("events"):
            doc.add_heading("付款节点核对", 3)
            doc.add_paragraph(clean(analysis.get("calculation")))
            for e in analysis["events"]:
                percentage = f"{e['percentage']}%" if e.get("percentage") is not None else "比例待确认"
                paragraph(value_text(e.get("condition")), f"{percentage} / 基数：{value_text(e.get('base'))}\n{value_text(e.get('quote'))}")

    if snapshot["contracts"]:
        doc.add_page_break()
    doc.add_heading("三、逐项风险与处理要求", 1)
    doc.add_paragraph("以下保留审查输出的完整原文、原因和建议。条数按风险记录统计，跨Agent重复项未自动归并；法律适用及建议比例须由专业人员核验。")
    if not brief["issues"]:
        doc.add_paragraph("当前范围暂无风险记录，请先检查任务状态和覆盖信息。")
    source_catalog = {}
    for i in brief["issues"]:
        r = i["risk"]
        doc.add_heading(f"{i['ref']} · {clean(r['category'])} · {i['level']}", 2)
        paragraph("合同 / 发现方", f"{r['filename']} / {AGENT.get(r.get('agent'),r.get('agent') or '未记录')}")
        paragraph("核验 / 人工复核", i["verification"] + " / " + i["review"])
        source_refs = []
        for source in r.get("rag_sources", []):
            if not isinstance(source, dict):
                continue
            content = sources({"rag_sources": [source]})
            if content not in source_catalog:
                source_catalog[content] = f"S{len(source_catalog)+1:03}"
            source_refs.append(source_catalog[content])
        for label, value in [("原文定位", location(r)), ("原文", r.get("original_text")),
                             ("业务影响（审查原文）", r.get("risk_reason")), ("处理建议（待专业复核）", r.get("suggestion")),
                             ("依据（适用性待核验）", r.get("basis")), ("检索来源", "、".join(source_refs) + "（完整来源见文末索引）" if source_refs else "尚无可回读的检索来源"),
                             ("依据支持说明", r.get("support_validation_reason")),
                             ("责任 / 期限 / 整改", i["owner"] + " / " + i["due"] + " / " + i["action_status"])]:
            paragraph(label,value_text(value))

    if snapshot["contracts"]:
        doc.add_page_break()
    doc.add_heading("四、整改与人工签批记录", 1)
    if snapshot["rectifications"]:
        table(["风险 / 任务", "责任人", "截止日", "实际状态"], [
            [f"R{t['risk_id']} / {t['id']}", value_text(t.get("owner"),"待分派"), value_text(t.get("due"),"待约定"), value_text(t.get("status"))] for t in snapshot["rectifications"]
        ],[5.2,4,4,4.2])
    else:
        doc.add_paragraph("尚未建立关联整改任务。请专业人员确认风险后，在系统分派责任人、约定期限并留存复核记录。")
    paragraph("待分派", f"{brief['unassigned']}条未忽略风险尚无完整责任分派。具体风险编号见Excel“审批重点”。")
    doc.add_heading("授权人员填写", 2)
    doc.add_paragraph("以下为空白签批栏，不代表已审批。离线填写内容不会自动回写系统，请按企业审批流程留档。")
    table(["角色", "意见 / 待满足条件", "签名 / 日期"], [
        ["经办", "", ""], ["法务复核", "", ""], ["财务复核", "", ""], ["授权审批人", "", ""]
    ], [3.0,10.0,4.4])
    doc.add_heading("五、范围、口径与追溯", 1)
    for note in snapshot["notes"]:
        doc.add_paragraph(clean(note))
    doc.add_paragraph("‘材料状态’仅提示现有记录中的待补充与核对事项，不代表公司审批制度检查已完成。金额按原文列示，责任人及期限只引用已有关联任务，不自动生成。")
    paragraph("完整校验编号", snapshot["report_id"])
    if source_catalog:
        doc.add_page_break()
        doc.add_heading("附录：检索来源索引", 1)
        doc.add_paragraph("相同来源正文只保留一份，通过来源编号回查。检索到来源不代表其适用性或支持关系已经核验。")
        for content, ref in source_catalog.items():
            doc.add_heading(ref, 2)
            doc.add_paragraph(clean(content))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
