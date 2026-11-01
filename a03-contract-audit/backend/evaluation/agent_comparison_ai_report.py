"""将AI角色标注、待核验项和对照观察整理为Word与逐条CSV。"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from pathlib import Path

from evaluation.agent_comparison import digest
from evaluation.agent_comparison_ai_review import read


CATEGORY = {'legal': '法务', 'finance': '财务'}
STATUS = {'supported': 'AI支持', 'match': '匹配AI参考', 'unsupported': 'AI认为原文不支持',
          'novel_supported': 'AI认为合理、参考未收录', 'uncertain': '不确定', 'pending': '未裁决'}


def percent(value):
    return f'{value:.1%}' if value is not None else '未定义'


def document(title, subtitle):
    from docx import Document
    from docx.shared import Cm, Pt, RGBColor
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(1.8)
    sec.left_margin = sec.right_margin = Cm(2)
    for name in ('Normal', 'Title', 'Heading 1', 'Heading 2'):
        style = doc.styles[name]
        style.font.name = 'Microsoft YaHei'
        style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    normal = doc.styles['Normal']
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.15
    doc.styles['Title'].font.size = Pt(24)
    doc.styles['Heading 1'].font.size = Pt(15)
    doc.styles['Heading 2'].font.size = Pt(12)
    for name in ('Title', 'Heading 1', 'Heading 2'):
        doc.styles[name].font.color.rgb = RGBColor.from_string('163958')
    header = sec.header.paragraphs[0]
    header.text = '契鉴  /  AI模拟复核  /  内部探索记录'
    header.style = doc.styles['Caption']
    footer = sec.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run('AI辅助候选，非人工专家金标  ·  ')
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    doc.add_heading(title, 0)
    doc.add_paragraph(subtitle)
    return doc


def table(doc, headings, values):
    from docx.oxml import OxmlElement
    target = doc.add_table(rows=1, cols=len(headings))
    target.style = 'Light Shading Accent 1'
    for c, value in zip(target.rows[0].cells, headings):
        c.text = str(value)
    repeat = OxmlElement('w:tblHeader')
    target.rows[0]._tr.get_or_add_trPr().append(repeat)
    for values_row in values:
        for c, value in zip(target.add_row().cells, values_row):
            c.text = str(value)
    for row in target.rows:
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
    return target


def csv_file(path, headings, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(headings)
        # 对外部文本保留为数据，避免Excel将其当作公式执行。
        writer.writerows([("'" + str(v)) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v
                         for v in row] for row in rows)


def build_documents(dataset: Path, original: Path, review: Path) -> dict:
    meta = read(review / 'review-run.json')
    if meta['status'] != 'ai_review_complete_pending_human':
        raise ValueError('AI复核未完成，不能生成最终结果报告')
    references = read(review / 'ai-reference-v1.json')
    if digest((review / 'ai-reference-v1.json').read_bytes()) != meta['reference_sha256']:
        raise ValueError('冻结参考已变更')
    summary = read(review / 'ai-summary.json')
    manifest = {r['case_id']: r for r in read(dataset / 'manifest.json') if r['split'] == 'test'}
    if set(manifest) != {r['case_id'] for r in references} or summary['human_review_complete'] is not False:
        raise ValueError('样本或来源状态不一致')
    pool = read(review / meta.get('prediction_pool_file', 'prediction-pool.json'))
    predictions = {p['prediction_id']: {'case_id': c, **p} for c, values in pool.items() for p in values}
    blind = {r['blind_id']: r for r in read(original / 'blind-review.json')}
    identities = read(original / 'private-unblind-map.json')
    expanded = read(review / 'ai-blind-review.json')
    unresolved = read(review / 'unresolved-candidates.json')
    supported = [r for c in references for r in c['risks'] if r['status'] == 'supported']
    uncertain = [r for c in references for r in c['risks'] if r['status'] != 'supported']
    roles = [(case_id, role, read(review / 'role-annotations' / f'{case_id}-{role}.json'))
             for case_id in manifest for role in ('legal', 'finance')]
    directories = tuple(dict.fromkeys(('role-annotations', 'consolidation', 'judgments', meta.get('judgments_folder', 'judgments'))))
    attempts = [a for name in directories
                for p in (review / name).glob('*.json') for a in read(p)['attempts']]
    doc = document('契鉴：AI法务与财务复核', '2026年10月31日  ·  20份合成合同  ·  角色标注、组别隐藏裁决与对照观察')
    doc.add_heading('结论与使用边界', 1)
    doc.add_paragraph('本次已由同一模型分别模拟法务、财务角色完成候选标注，再合并冻结参考并对隐藏组别的预测逐条裁决。它提供可核对的AI复核底稿，不是真人专家金标，不构成独立法律正确性证明。原实验的人工Precision、Recall与F1仍为未测量。')
    doc.add_paragraph(f'合并后有{len(supported)}项AI支持的参考问题、{len(uncertain)}项不确定参考。原实验共180单元、300请求，294请求成功、6次超时，所有失败单元和部分结果均保留。')
    unlocated = sum(r.get('quote_verified') is False for r in uncertain)
    doc.add_paragraph(f'不确定参考中有{unlocated}项未能通过连续原文匹配，其余为模型保留的语义或材料不确定项。匹配失败可能来自PDF换行或转述，不等于问题不存在；这些候选均保留，未计入AI参考覆盖率分母。')
    arms = summary['arms']
    d2, s2 = arms['D2']['ai_reference_coverage'], arms['S2']['ai_reference_coverage']
    if d2 is not None and s2 is not None:
        doc.add_paragraph(f'在本轮冻结AI参考口径下，D2覆盖率为{percent(d2)}，通用两轮S2为{percent(s2)}，差值{(d2-s2)*100:+.1f}个百分点。该差值是同模型事后自评观察，不能解释为真实法律准确率差异或统计显著提升。')
        if d2 <= s2:
            doc.add_paragraph('本轮没有观察到法财分工提高整体AI参考覆盖的优势，应保留职责分工与受控复核的机制特色，删除“已证明双Agent更准确”或“准确率提升”的答辩表述。')
    doc.add_heading('三组对照观察', 1)
    metrics = [
        ('完整成功单元', lambda s: f'{s["complete_success_cells"]}/{s["cells"]}'),
        ('匹配AI参考 / 参考实例', lambda s: f'{s["matched_reference_instances"]}/{s["reference_instances"]}'),
        ('AI参考覆盖率', lambda s: percent(s['ai_reference_coverage'])),
        ('原始输出条数', lambda s: s['raw_findings']),
        ('重复覆盖同一参考的输出', lambda s: s.get('reference_duplicate_findings', 0)),
        ('AI认为原文不支持的输出', lambda s: s.get('unsupported_findings', 0)),
        ('AI认为合理、参考未收录', lambda s: s.get('novel_supported_findings', 0)),
        ('不确定 / 未裁决输出', lambda s: f'{s.get("uncertain_findings", 0)} / {s.get("pending_findings", 0)}'),
    ]
    table(doc, ['观察项', 'S1通用一次', 'S2通用两次', 'D2法财分工'],
          [(label, *(function(arms[a]) for a in ('S1', 'S2', 'D2'))) for label, function in metrics])
    table(doc, ['参考类别', 'S1覆盖', 'S2覆盖', 'D2覆盖'],
          [(CATEGORY[c], *(f'{arms[a][c+"_matched"]}/{arms[a][c+"_references"]}（' +
            percent(arms[a][c+'_matched']/arms[a][c+'_references'] if arms[a][c+'_references'] else None) + '）'
            for a in ('S1', 'S2', 'D2'))) for c in ('legal', 'finance')])
    doc.add_paragraph('覆盖率＝每单元匹配到的不同AI参考数之和 / 每单元可匹配AI参考数之和。每合同每组3次重复，参考实例随重复累加，独立合同始终只有20份。匹配同一参考只计一次；一条输出若明确包含多个不同问题，可覆盖多个参考。类别措辞差异不阻断实质匹配。')
    doc.add_paragraph('“原文不支持”是AI判断，不能直接称为经专家确认的误报。“合理、参考未收录”说明冻结参考可能不全，保留待核验，不算误报，不为某一组事后补标签。不同组原始输出条数不同，不能仅按疑似误报条数比较质量。')
    doc.add_paragraph('样本偏差：复核发现多份合同的附件仍保留与正文业务不符的设备分类、计量或验收表格，例如钢材、食品采购附件出现设备/组件名称。这类生成模板错配会集中产生易识别问题，不能据其覆盖率外推真实企业合同表现。后续宜补充经人工整理的真实业务文本和经确认的无风险对照。')
    doc.add_heading('逐合同参考覆盖', 1)
    case_rows = []
    for c in references:
        risks = [r for r in c['risks'] if r['status'] == 'supported']
        values = []
        for arm in ('S1', 'S2', 'D2'):
            cells = [x for x in summary['cells'] if x['case_id'] == c['case_id'] and x['arm'] == arm]
            numerator = sum(len(x['matched_reference_ids']) for x in cells)
            values.append(f'{numerator}/{len(risks)*3}')
        counts = Counter(r['category'] for r in risks)
        case_rows.append((c['case_id'], f'{counts["legal"]}/{counts["finance"]}', *values))
    table(doc, ['合同', '参考：法/财', 'S1覆盖', 'S2覆盖', 'D2覆盖'], case_rows)
    doc.add_heading('优先核验的问题示例', 1)
    examples = [r for category in ('legal', 'finance')
                for r in sorted((x for x in supported if x['category'] == category),
                                key=lambda r: (r['severity'], r['reference_id']))[:3]]
    for risk in examples:
        doc.add_heading(f'{risk["reference_id"]}  {risk["severity"]}  {risk["issue"]}', 2)
        doc.add_paragraph('原文：' + ' '.join(risk['quote'].split()))
        doc.add_paragraph(f'复核理由：{risk["reason"]}；建议：{risk["suggestion"]}')
    doc.add_heading('待核验新问题与不确定项', 1)
    counts = Counter(r['status'] for r in unresolved)
    doc.add_paragraph(f'按完全相同问题复用裁决后，待核验池包含{counts["novel_supported"]}条参考外合理候选、{counts["uncertain"]}条不确定候选、{counts["pending"]}条未完成裁决。原始预测层面的出现次数见上表，不能将复用后的数量与原始条数混用。')
    for row in unresolved[:5]:
        p = predictions[row['prediction_id']]
        doc.add_paragraph(f'{p["case_id"]}｜{STATUS[row["status"]]}｜{p["issue"]}\n理由：{row["reason"]}')
    doc.add_heading('过程、用量与复现', 1)
    blocked = sum(a.get('error_code') == 'MODEL_OUTBOUND_BLOCKED' for a in attempts)
    unknown_usage = sum((a['prompt_tokens'] is None or a['completion_tokens'] is None)
                        and a.get('error_code') != 'MODEL_OUTBOUND_BLOCKED' for a in attempts)
    doc.add_paragraph(f'模型ID：{meta["model"]}；过程共保存{meta["tasks"]}份任务记录（含初期记录与编号转换复用记录）、{len(attempts)}次请求尝试，{sum(a["status"] == "success" for a in attempts)}次通过结构校验；最多3并发、温度0，每任务最多2次尝试。{blocked}次被本机策略拦截；其余尝试有{unknown_usage}次未返回用量。')
    doc.add_paragraph(f'复核调用已返回输入Token：{sum(a["prompt_tokens"] or 0 for a in attempts)}；输出Token：{sum(a["completion_tokens"] or 0 for a in attempts)}。未返回用量不是零成本；未提供价格，不估算费用。服务返回输出Token超过请求3600上限的记录有{sum((a["completion_tokens"] or 0)>3600 for a in attempts)}次。')
    doc.add_paragraph('先完成40次独立角色标注，再合并20份参考并冻结。之后才读取被测系统预测。裁决输入隐藏组别、来源角色及重复轮次；完全相同“合同+类别+原文+问题”复用裁决，建议质量不在本轮评分范围。全部原始角色标注和调用尝试另存，未覆盖原合同或原实验。')
    if meta.get('remediation'):
        doc.add_paragraph('过程修正：' + meta['remediation'] + '。前期被本机策略拦截的尝试不表示服务端调用或消耗。另有一次进程中断，最多3个在途请求的完成状态和用量未知，可能已有费用，未计入已返回用量。')
    doc.add_paragraph('证据文件：role-annotations/、consolidation/、ai-reference-v1.json、judgments/、ai-blind-review.json、ai-summary.json及unresolved-candidates.json。逐条可读表见同目录两个CSV，合并候选详见标注清单Word。')
    doc.add_heading('创新点与答辩表述', 1)
    doc.add_paragraph('三个创新点继续采用：法财职责分离与受控交叉复核；原文、依据与决策关联的风险证据链；分级人工介入与整改交付留痕。它们是现有应用和工程机制特色，不以本次AI自评结果证明算法首创或准确率提升。')
    doc.add_paragraph('答辩可说：“我们对20份合成合同完成了单轮通用、双轮通用和法财分工三组探索实验，并开展AI角色模拟标注与逐条复核，用于发现漏项、重复和待核验问题。由于尚缺独立人工金标，我们保留效果边界，不将AI自评数字当作法律准确率。”')
    doc.add_heading('基于本轮复核的改进顺序', 1)
    table(doc, ['优先级', '排查方向', '本轮提示'], [
        ('P1', '排查法务覆盖下降与过度推断', 'AI裁决中出现将合成主体标签、未披露内部预算或关联关系、未设一般责任上限直接报为问题的候选。先核对事实和任务范围。'),
        ('P1', '检查PDF数字与换行引用', '例如320万元因断行被报为金额不明；引文换行差异也会使合理候选无法连续定位。应对照原文复核。'),
        ('P2', '审阅参考外新问题及重复覆盖', '参考清单可能不全，统一核验新候选后再考虑新的独立评测，不为某一组临时增补标签。'),
        ('P3', '改善样本代表性', '加入经人工整理的真实业务合同和经确认的无风险对照，减少附件模板错配带来的偏差。'),
    ])
    report_path = review / '契鉴_AI法务财务复核与对照分析.docx'
    doc.save(report_path)
    appendix = document('20份合同AI复核标注清单', '合并候选逐项核验底稿  ·  非真人专家金标  ·  与原始角色标注分开保存')
    appendix.add_paragraph('优先级P1：可能重大责任或资金损失；P2：重要履约或结算歧义；P3：一般改进。AI支持只表示模型认为有原文依据，不表示法规适用已经人工确认。每项保留原文、理由和建议；不确定项不进入覆盖率分母。为便于阅读，Word引文合并换行；逐字引用及定位状态以JSON/CSV为准。')
    for n, case in enumerate(references):
        appendix.add_page_break()
        source = manifest[case['case_id']]
        appendix.add_heading(f'{n+1:02d}  {case["case_id"]}  {source["source_file"]}', 1)
        role_counts = {role: len(record['data']['risks']) for cid, role, record in roles if cid == case['case_id']}
        appendix.add_paragraph(f'独立法务候选{role_counts["legal"]}项、财务候选{role_counts["finance"]}项；合并后{len(case["risks"])}项。角色原始意见见CSV和role-annotations，不代表两名真人独立复核。')
        if not case['risks']:
            appendix.add_paragraph('本轮AI未提出候选问题；不等于经专家确认无风险。')
        for risk in case['risks']:
            appendix.add_heading(f'{risk["reference_id"]}｜{CATEGORY[risk["category"]]}｜{risk["severity"]}｜{STATUS[risk["status"]]}', 2)
            appendix.add_paragraph(risk['issue'])
            appendix.add_paragraph('原文：' + ' '.join(risk['quote'].split()))
            appendix.add_paragraph('理由：' + risk['reason'] + '\n建议：' + risk['suggestion'])
        if case['cleared_points']:
            appendix.add_heading('全文核查后的排除说明', 2)
            for point in case['cleared_points']:
                appendix.add_paragraph(point)
    appendix_path = review / '契鉴_20份合同AI复核标注清单.docx'
    appendix.save(appendix_path)
    role_csv = []
    for case_id, role, record in roles:
        for i, risk in enumerate(record['data']['risks'], 1):
            role_csv.append([case_id, CATEGORY[role], i, risk['severity'], STATUS[risk['status']],
                             risk['quote'], risk['issue'], risk['reason'], risk['suggestion'], risk['quote_verified'], 'AI模拟'])
    csv_file(review / 'AI法务财务分别标注.csv',
             ['合同', '模拟角色', '序号', '优先级', '状态', '原文', '问题', '理由', '建议', '原文精确定位', '来源'], role_csv)
    finding_csv = []
    for row in expanded:
        identity = identities[row['blind_id']]
        for j in row['judgments']:
            prediction = blind[row['blind_id']]['risks'][j['finding_index']]
            finding_csv.append([identity['case_id'], identity['arm'], identity['repeat'], row['blind_id'],
                                j['finding_index'], prediction['category'], prediction['quote'], prediction['issue'],
                                STATUS[j['status']], ';'.join(j['reference_ids']), j['reason'], 'AI模拟裁决'])
    csv_file(review / '全部模型输出AI逐条裁决.csv',
             ['合同', '组别（裁决后揭示）', '轮次', '盲评ID', '输出序号', '原类别', '原文', '原问题', 'AI裁决', '参考ID', '理由', '来源'], finding_csv)
    from docx import Document
    checked = Document(report_path)
    all_text = '\n'.join(p.text for p in checked.paragraphs)
    assert '不是真人专家金标' in all_text and '未测量' in all_text
    appendix_text = '\n'.join(p.text for p in Document(appendix_path).paragraphs)
    assert all(r['reference_id'] in appendix_text for c in references for r in c['risks'])
    return {'report': str(report_path), 'annotation_appendix': str(appendix_path),
            'role_annotation_rows': len(role_csv), 'finding_judgment_rows': len(finding_csv)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--original-run', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    args = parser.parse_args()
    print(build_documents(args.dataset, args.original_run, args.review))


if __name__ == '__main__':
    main()
