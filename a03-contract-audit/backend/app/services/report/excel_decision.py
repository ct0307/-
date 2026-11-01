"""管理审批首页与可执行核对清单。"""
from openpyxl.styles import Alignment, Font, PatternFill
from .decision_brief import decision_brief, contract_facts, excerpt, value_text, validation_text, human_review_text

INK, RED, PAPER, MUTED = "202622", "AD321B", "F7F4EC", "647067"


def build_overview(wb, snapshot):
    brief = decision_brief(snapshot)
    s = snapshot["summary"]
    ws = wb.create_sheet("摘要", 0)
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 85
    ws.sheet_properties.tabColor = RED
    for col in "ABCDEFGHIJKL":
        ws.column_dimensions[col].width = 12
    for row in range(1, 52):
        ws.row_dimensions[row].height = 23
        for col in range(1, 13):
            cell = ws.cell(row, col)
            cell.fill = PatternFill("solid", fgColor=PAPER)
            cell.font = Font(name="微软雅黑", size=11, color=INK)

    def block(area, value, size=11, color=INK, fill=None, bold=False, link=None):
        ws.merge_cells(area)
        for row in ws[area]:
            for cell in row:
                if fill:
                    cell.fill = PatternFill("solid", fgColor=fill)
        cell = ws[area.split(":")[0]]
        cell.value = value_text(value) if not isinstance(value, (int, float)) else value
        if isinstance(cell.value, str):
            cell.data_type = "s"
        cell.font = Font(name="微软雅黑", size=size, bold=bold, color=color)
        cell.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
        if link:
            cell.hyperlink = link
        return cell

    block("A1:L1", "契鉴  /  审批阅读与专业核对", 11, "FFFFFF", INK, True)
    block("A2:L3", "合同审查 · 审批摘要", 25, bold=True)
    block("A4:L4", f"{brief['generated']}（北京时间）  |  {s['total']}份合同  |  报告 {snapshot['report_id'][:12]}", 10, MUTED)
    block("A6:L6", "材料状态：" + brief["status"], 15, RED, "EDE8DF", True)
    block("A7:L8", excerpt(brief["note"], 175), 11, INK, "EDE8DF")
    block("A10:L10", "01  业务概况  /  合同金额与条款按原文展示，未核验值需确认", 13, bold=True)
    if len(snapshot["contracts"]) == 1:
        facts = dict(contract_facts(snapshot["contracts"][0]))
        for row, left, right in [(11, "甲方", "乙方"), (13, "金额（原文）", "履行期限")]:
            block(f"A{row}:F{row+1}", left + "：" + excerpt(facts[left], 68), 11, fill="FFFFFF")
            block(f"G{row}:L{row+1}", right + "：" + excerpt(facts[right], 68), 11, fill="FFFFFF")
        block("A15:L16", "标的：" + excerpt(facts["合同标的"], 110), 11, fill="FFFFFF")
        block("A17:L18", "付款：" + excerpt(facts["付款安排"], 110), 11, fill="FFFFFF")
        block("A19:L19", excerpt(facts["合同名称"], 70) + "  |  " + excerpt(facts["所属部门 / 类型"], 35), 10, MUTED)
    else:
        block("A11:L13", f"合同组合：{s['total']}份。涉及金额未统一币种与计价基数，不汇总为风险敞口。", 12, fill="FFFFFF")
        names = "；".join(value_text(c.get("filename")) for c in snapshot["contracts"][:3])
        block("A14:L17", excerpt(names or "当前范围没有合同，请检查所选范围及权限。", 180), 11, fill="FFFFFF")
        block("A18:L19", "逐份合同双方、金额、期限及付款安排 → 合同清单", 11, RED, link="#'合同清单'!A1")
    block("A21:L21", "02  优先关注事项  /  按等级排序，已忽略记录不列入首页", 13, bold=True)
    if brief["focus"]:
        for idx, item in enumerate(brief["focus"]):
            row = 22 + idx * 4
            risk = item["risk"]
            block(f"A{row}:L{row}", f"{item['ref']} · {item['level']} · {excerpt(risk.get('category'), 40)} · {item['review']}", 11, RED, "FFFFFF", True)
            block(f"A{row+1}:L{row+3}", "影响：" + excerpt(risk.get("risk_reason"), 88) + "\n处理：" + excerpt(risk.get("suggestion"), 88), 10, fill="FFFFFF")
    else:
        empty = "当前范围暂无风险记录。" if not s["risks"] else "现有风险均已标记忽略；忽略原因与适用性仍须人工核对。"
        block("A22:L29", empty + "\n无记录或已忽略均不代表合规批准。", 12, MUTED, "FFFFFF")
    block("A34:L34", f"共{s['risks']}条风险记录，高{s['high']} / 中{s['medium']} / 低{s['low']}；更多关注事项见“审批重点”。", 10, MUTED)
    block("A36:L36", "03  证据与待办  /  核验完成与人工确认分别统计", 13, bold=True)
    block("A37:F38", f"原文已定位 {brief['original_verified']}/{s['risks']}条\n原文与依据核验完整 {s['supported']}/{s['risks']}条", 11, fill="FFFFFF")
    block("G37:L38", f"人工已确认风险 {brief['human_confirmed']}条\n未分派责任风险 {brief['unassigned']}条（已忽略除外）", 11, fill="FFFFFF")
    block("A40:D41", "审批重点 → 问题、影响与责任", 11, RED, "FFFFFF", True, "#'审批重点'!A1")
    block("E40:H41", "风险详情 → 完整原文与建议", 11, RED, "FFFFFF", True, "#'风险详情'!A1")
    block("I40:L41", "整改跟踪 → 已建任务与期限", 11, RED, "FFFFFF", True, "#'整改跟踪'!A1")
    block("A43:L45", "审批边界：本页整理当前材料，不自动作出签署决定。模型风险、法律依据与修改建议需专业人员核验；跨Agent记录尚未归并，不等于独立问题数。", 10, MUTED)
    block("A47:L49", "完整报告校验编号\n" + snapshot["report_id"] + "\n完整字段、统计范围及待补充信息见各明细页与口径说明。", 9, MUTED)
    ws.freeze_panes = "A5"
    ws.print_area = "A1:L50"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = ws.page_setup.fitToHeight = 1
    ws.print_options.horizontalCentered = True
    ws.oddFooter.center.text = "契鉴 · 审批决定由授权人员填写 | &P / &N"
    return ws


def add_review_sheets(wb, snapshot, sheet, location, sources):
    brief = decision_brief(snapshot)
    issues = brief["issues"]
    focus = sheet(wb, "审批重点", ["风险编号", "合同", "等级", "事项", "业务影响（审查原文）", "处理建议（审查原文）", "人工复核", "证据状态", "责任人", "截止日", "整改状态", "详情入口"], [
        [i["ref"], i["risk"]["filename"], i["level"], i["risk"]["category"], excerpt(i["risk"].get("risk_reason"), 180), excerpt(i["risk"].get("suggestion"), 180), i["review"], i["verification"], i["owner"], i["due"], i["action_status"], "查看完整记录"] for i in issues
    ], [12, 30, 12, 24, 60, 60, 15, 24, 20, 18, 24, 18])
    # 竖排全文避免十余列同时打印导致正文缩小；短段落控制Excel行高上限。
    rows, starts = [], {}
    for i in issues:
        risk = i["risk"]
        starts[i["ref"]] = len(rows) + 2
        for label, value in [
            ("事项", f"{i['level']} / {risk['category']} / {i['review']}"),
            ("合同", risk["filename"]), ("原文定位", location(risk)),
            ("原文", risk.get("original_text")), ("业务影响（审查原文）", risk.get("risk_reason")),
            ("修改建议（待复核）", risk.get("suggestion")), ("依据（待核验）", risk.get("basis")),
            ("检索来源", sources(risk)), ("核验与复核", i["verification"] + " / " + i["review"]),
            ("证据核验记录", validation_text(risk)), ("人工复核记录", human_review_text(risk)),
            ("责任与期限", i["owner"] + " / " + i["due"] + " / " + i["action_status"]),
        ]:
            text = value_text(value)
            parts = [text[j:j+420] for j in range(0, len(text), 420)]
            for index, part in enumerate(parts):
                rows.append([i["ref"], label + (f"（续{index+1}）" if index else ""), part])
    detail = sheet(wb, "风险详情", ["风险编号", "阅读项", "完整内容"], rows, [13, 25, 105])
    detail.page_setup.paperSize = detail.PAPERSIZE_A4
    detail.page_setup.orientation = "portrait"
    for index, i in enumerate(issues, 2):
        focus.cell(index, 12).hyperlink = f"#'风险详情'!A{starts[i['ref']]}"
        focus.cell(index, 12).font = Font(name="微软雅黑", size=10, color=RED, underline="single")
    # 顺序不依赖内部workbook实现。
    wb.move_sheet(focus, offset=1-wb.index(focus))
    wb.move_sheet(detail, offset=wb.index(wb["风险台账"])+1-wb.index(detail))
    for name in ["审批重点", "风险台账", "风险详情", "证据索引", "整改跟踪", "付款节点"]:
        ws = wb[name]
        if ws.max_row == 1:
            ws.cell(2, 1, "当前范围暂无记录；请结合合同状态判断，不能据此认定合规。")
            ws.merge_cells(start_row=2, start_column=1, end_row=3, end_column=ws.max_column)
            ws.cell(2, 1).alignment = Alignment(wrap_text=True, vertical="center")
            ws.cell(2, 1).font = Font(name="微软雅黑", color=MUTED, size=11)
            ws.auto_filter.ref = f"A1:{ws.cell(1,ws.max_column).column_letter}1"
            ws.print_area = ws.dimensions
