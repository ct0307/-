"""生成本机实验记录与创新表述Word，不把引用率当法律准确率。"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean, median


def technical_summary(rows: list[dict]) -> dict:
    arms = {}
    for arm in ('S1', 'S2', 'D2'):
        selected = [r for r in rows if r['arm'] == arm]
        calls = [c for r in selected for c in r['calls']]
        risks = [risk for r in selected for risk in r['risks']]
        times = sorted(r['elapsed_ms'] for r in selected)
        arms[arm] = {
            'recorded_cells': len(selected),
            'statuses': dict(Counter(r['status'] for r in selected)),
            'calls': len(calls), 'successful_calls': sum(c['status'] == 'success' for c in calls),
            'error_codes': dict(Counter(c['error_code'] for c in calls if 'error_code' in c)),
            'prompt_tokens': sum(c.get('prompt_tokens') or 0 for c in calls),
            'completion_tokens': sum(c.get('completion_tokens') or 0 for c in calls),
            'unreported_usage_calls': sum(c.get('prompt_tokens') is None or
                                          c.get('completion_tokens') is None for c in calls),
            'usage_exceeds_requested_cap_calls': sum(
                (c.get('completion_tokens') or 0) > c.get('max_output_tokens', float('inf'))
                for c in calls),
            'valid_output_findings_before_semantic_dedup': len(risks),
            'exact_quote_matches': sum(r.get('quote_verified') is True for r in risks),
            'exact_quote_rate': sum(r.get('quote_verified') is True for r in risks) / len(risks) if risks else None,
            'mean_cell_ms': mean(times) if times else None,
            'median_cell_ms': median(times) if times else None,
            'p95_cell_ms': times[max(0, (95 * len(times) + 99) // 100 - 1)] if times else None,
            'risk_precision': None, 'risk_recall': None, 'risk_f1': None,
        }
    return {'scope': 'technical_observation_not_legal_quality', 'arms': arms,
            'note': 'Token仅累加已返回用量，未知请求不表示零消耗；未提供价格，不估算费用。风险条数未做语义去重；引用存在不证明风险成立。'}


def build(dataset: Path, run: Path, out: Path) -> Path:
    from docx import Document
    from docx.shared import Inches, Pt
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    manifest = json.loads((dataset / 'manifest.json').read_text(encoding='utf-8'))
    experiment = json.loads((dataset / 'experiment.json').read_text(encoding='utf-8'))
    meta_path = run / 'run.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    path = run / 'results.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []
    summary = technical_summary(rows)
    (run / 'technical-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)
    section.top_margin = section.bottom_margin = Inches(.75)
    style = doc.styles['Normal']
    style.font.name = 'Microsoft YaHei'
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
    doc.add_heading('契鉴：单 Agent 与法财双 Agent 内部对照记录', 0)
    doc.add_paragraph('2026年10月31日｜合成合同、小规模探索实验｜三项创新点定稿')
    doc.add_heading('当前结论', 1)
    status = meta.get('status', 'not_started')
    doc.add_paragraph(f'模型：{meta.get("model", "未取得模型信息")}；运行状态：{status}；已记录实验单元：{len(rows)}/180。')
    doc.add_paragraph('模型运行、格式成功和原文引用指标可以由程序核验；风险召回、精确率和F1必须等待独立人工标注与盲评。当前不能宣称法财双Agent优于单Agent，也不能把请求成功率或引用匹配率称为法律准确率。')
    doc.add_heading('实验设计', 1)
    table = doc.add_table(rows=1, cols=3)
    table.style = 'Light Shading Accent 1'
    for cell, text in zip(table.rows[0].cells, ['组别', '独立审查方式', '每合同每轮请求上限']):
        cell.text = text
    for row in [('S1', '通用法财清单，一次', '1×3200 tokens'),
                ('S2', '通用法财清单，两次取并集', '2×1600 tokens'),
                ('D2', '法务与财务各一次，取并集', '2×1600 tokens')]:
        for cell, text in zip(table.add_row().cells, row):
            cell.text = text
    doc.add_paragraph('20份测试合同，每组3次重复，共180个实验单元、300次计划请求。S2与D2调用数及输出上限一致，实际Token不强制相同。最多3个单元并发，组内顺序调用。这里只比较独立首审专业分工，不测试RAG、完整交叉复核和产品并行性能。')
    doc.add_paragraph('开发集6份与测试集按起草风格隔离，但来自同一合成生成器，仍存在同源模板偏差。测试集包含15份构造actionable与5份negotiated；两者都不是人工风险真值。缺少经确认的无风险对照，限制误报结论。')
    doc.add_heading('输入与安全处理', 1)
    doc.add_paragraph('原合同不变。文本中删除显式答案提示并记录清理痕迹，保留不利责任安排。DOCX按接受插入、排除删除与批注的口径提取；PDF仅使用完整文本层。清理后的敏感字段统一脱敏，因此主体身份核验不在本轮范围内。')
    doc.add_paragraph('服务端提供的模型名称为gpt-6.1-sol。此前旧配置401、错误模型标识503仅作连通诊断，未混入三组实验。新模型开发样本连通检查成功，另存，不计入测试结果。密钥与.env不进入报告或版本控制。')
    doc.add_paragraph('冻结数据清单SHA-256：' + experiment['dataset_sha256'])
    doc.add_heading('程序可核验的观察', 1)
    table = doc.add_table(rows=1, cols=6)
    table.style = 'Light Shading Accent 1'
    for c, text in zip(table.rows[0].cells, ['组', '完整成功/已记录', '请求成功/已请求', '已返回输入Token', '已返回输出Token', '精确引用/输出风险']):
        c.text = text
    for arm, s in summary['arms'].items():
        values = [arm, f'{s["statuses"].get("success", 0)}/{s["recorded_cells"]}',
                  f'{s["successful_calls"]}/{s["calls"]}', str(s['prompt_tokens']), str(s['completion_tokens']),
                  f'{s["exact_quote_matches"]}/{s["valid_output_findings_before_semantic_dedup"]}']
        for c, text in zip(table.add_row().cells, values):
            c.text = text
    doc.add_paragraph('引用指标仅检查输出原文是否为输入中的连续字符串；非连续引用可能无法精确匹配，但不因此自动判为法律误报。风险条数尚未人工做语义去重。服务返回Token为记录依据，未提供价格，费用未测量。')
    deviations = '；'.join(f'{arm}：{s["usage_exceeds_requested_cap_calls"]}次' for arm, s in summary['arms'].items())
    doc.add_paragraph('服务预算偏差：返回completion_tokens超过请求上限的记录为' + deviations +
                      '。客户端发送了max_tokens，但服务端执行或计数口径尚未核实。因此只能比较相同请求配置，不能声称严格等实际算力；不在本轮中途更换参数。')
    unknown = '；'.join(f'{arm}：{s["unreported_usage_calls"]}次' for arm, s in summary['arms'].items())
    doc.add_paragraph('未返回用量的请求为' + unknown + '。上述Token仅为已返回用量之和；超时或失败请求的实际消耗未知，不能当成零，也不能直接据此计算完整费用。')
    doc.add_heading('待人工完成的效果验证', 1)
    doc.add_paragraph('法务与财务人员独立阅读全文和标注，裁决后冻结统一答案。盲评时只提供blind-review.json，不提供private-unblind-map.json。每条预测裁决命中、误报或重复；漏报由冻结标签与已命中标签之差计算。标注需保留真实复核人员和分歧处理记录，AI候选不能冒充专家金标。')
    doc.add_paragraph('本次运行发生在正式人工金标之前，只能作为探索实验。若事后完善标注并评分，须注明事后评估；正式对外效果证据需先冻结标签再独立重跑。3次重复仍只有20份独立合同，不能宣传成60份测试合同。')
    doc.add_heading('三个创新点：最终表述', 1)
    paragraphs = [
        ('法财职责分离与受控交叉复核', '将法务条款审查与财务交易核对分为独立职责，首审阶段相互不可见，随后通过受控结构化事实交接开展交叉复核，保留专业分歧并提交人工处理。当前首审为顺序执行；本轮只验证首审分工。'),
        ('原文、依据与决策关联的风险证据链', '把风险候选与合同原文位置、检索依据标识及决策记录关联，对无法定位、依据未核验或存在冲突的结果保留明确状态，支持人工逐项核验。RAG命中不等于法律判断正确。'),
        ('分级人工介入与整改交付留痕', '将风险分级连接到授权人员的确认、修改或忽略意见，结合整改跟踪和报告导出保留处理记录，使审查结果能够进入后续业务工作。不宣称真实企业效率改善已经测得。'),
    ]
    for title, body in paragraphs:
        doc.add_heading(title, 2)
        doc.add_paragraph(body)
    doc.add_heading('30秒答辩统一口径', 1)
    doc.add_paragraph('契鉴面向企业合同审查中标准不统一、专业意见分散、后续处理难追踪的问题，构建法财分工审查、风险证据关联和分级人工处置三项机制。系统协助发现和定位风险，并把依据、专业分歧和处理记录留给授权人员核验，最终连接到整改与报告交付。')
    doc.add_heading('测试样本清单', 1)
    table = doc.add_table(rows=1, cols=3)
    table.style = 'Light Shading Accent 1'
    for c, text in zip(table.rows[0].cells, ['编号', '原文件', '起草风格']):
        c.text = text
    for row in manifest:
        if row['split'] == 'test':
            for c, text in zip(table.add_row().cells, [row['case_id'], row['source_file'], row['style']]):
                c.text = text
    doc.add_heading('复现与证据位置', 1)
    doc.add_paragraph('backend/evaluation/agent_comparison.py：准备和运行；agent_comparison_score.py：人工复核后评分；agent_comparison_report.py：报告。docs/evaluation/agent-comparison/：协议、操作说明与创新证据表。本地inputs、manifest、原始输出、盲评映射、汇总在outputs中，不提交合同或运行证据到Git。')
    for table in doc.tables:
        for row in table.rows:
            props = row._tr.get_or_add_trPr()
            props.append(OxmlElement('w:cantSplit'))
    doc.save(out)
    # 保存后重读结构，验证中文、表格和关键边界均在。
    checked = Document(out)
    combined = '\n'.join(p.text for p in checked.paragraphs)
    assert '不能宣称法财双Agent优于单Agent' in combined
    assert len(checked.tables) == 3 and len(checked.tables[2].rows) == 21
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.dataset, args.run, args.out))


if __name__ == '__main__':
    main()
