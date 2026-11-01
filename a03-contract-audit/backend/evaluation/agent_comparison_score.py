"""对完整运行及人工盲评做描述性统计；拒绝用未复核候选生成准确率。"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def _reviewed(row: dict) -> bool:
    reviewers = row.get('reviewers')
    return (isinstance(reviewers, list) and len(set(reviewers)) >= 2
            and all(isinstance(v, str) and v.strip() for v in reviewers)
            and row.get('review_status') in ('agreed', 'adjudicated')
            and (row.get('review_status') != 'adjudicated'
                 or (row.get('adjudicator') and row['adjudicator'] not in reviewers)))


def score_review(results: list[dict], blind: list[dict], mapping: dict,
                 gold: list[dict]) -> dict:
    if not gold or any(not _reviewed(g) or not isinstance(g.get('risks'), list) for g in gold):
        raise ValueError('必须先完成两人独立复核和分歧裁决；候选不是金标')
    by_case = {g['case_id']: g for g in gold}
    if len(by_case) != len(gold):
        raise ValueError('金标合同重复')
    expected = {(c, repeat, arm) for c in by_case for repeat in (1, 2, 3)
                for arm in ('S1', 'S2', 'D2')}
    lookup = {(r['case_id'], r['repeat'], r['arm']): r for r in results}
    if len(lookup) != len(results) or set(lookup) != expected:
        raise ValueError('必须提供完整三组、三次、全部合同结果，失败样本也须保留')
    if len(blind) != len(expected) or len(mapping) != len(expected):
        raise ValueError('盲评数据不完整')
    stats = {arm: Counter() for arm in ('S1', 'S2', 'D2')}
    seen = set()
    for row in blind:
        if not _reviewed(row):
            raise ValueError('盲评尚未完成独立复核')
        identity = mapping[row['blind_id']]
        key = (identity['case_id'], identity['repeat'], identity['arm'])
        if key not in lookup or key in seen:
            raise ValueError('盲评身份未知或重复')
        seen.add(key)
        result = lookup[key]
        truth = by_case[key[0]]['risks']
        truth_map = {r['risk_id']: r for r in truth}
        if len(truth_map) != len(truth) or any(r.get('category') not in ('legal', 'finance') for r in truth):
            raise ValueError('金标风险ID重复或类别无效')
        predictions = result['risks']
        judgments = row.get('judgments', [])
        judged = {j['finding_index']: j for j in judgments}
        if len(judged) != len(judgments) or set(judged) != set(range(len(predictions))):
            raise ValueError('每条预测都必须盲评，禁止遗漏误报或新增预测')
        s, matched = stats[key[2]], set()
        s['samples'] += 1
        s['successes'] += result['status'] == 'success'
        s['elapsed_ms'] += result.get('elapsed_ms', 0)
        for call in result.get('calls', []):
            s['calls'] += 1
            s['successful_calls'] += call['status'] == 'success'
            s['prompt_tokens'] += call.get('prompt_tokens') or 0
            s['completion_tokens'] += call.get('completion_tokens') or 0
        for index, prediction in enumerate(predictions):
            judgment = judged[index]
            gold_id = judgment.get('gold_risk_id')
            duplicate = judgment.get('duplicate_of')
            if duplicate is not None:
                if not isinstance(duplicate, int) or not 0 <= duplicate < index:
                    raise ValueError('重复项必须引用前面的预测')
                if judgment.get('gold_risk_id') != judged[duplicate].get('gold_risk_id'):
                    raise ValueError('重复项与被引用项匹配不一致')
                s['semantic_duplicates'] += 1
                continue
            s['predictions'] += 1
            s['verified_quotes'] += prediction.get('quote_verified') is True
            if gold_id is None:
                s['fp'] += 1
                continue
            if gold_id not in truth_map or gold_id in matched:
                raise ValueError('未知或重复匹配金标风险')
            matched.add(gold_id)
            s['tp'] += 1
            s[truth_map[gold_id]['category'] + '_tp'] += 1
        s['fn'] += len(truth_map) - len(matched)
        for risk_id, risk in truth_map.items():
            s[risk['category'] + '_positive'] += 1
    if seen != expected:
        raise ValueError('盲评未覆盖全部实验单元')
    arms = {}
    for arm, s in stats.items():
        precision = s['tp'] / (s['tp'] + s['fp']) if s['tp'] + s['fp'] else None
        recall = s['tp'] / (s['tp'] + s['fn']) if s['tp'] + s['fn'] else None
        denominator = 2 * s['tp'] + s['fp'] + s['fn']
        arms[arm] = {**dict(s), 'precision': precision, 'recall': recall,
                     'f1': 2 * s['tp'] / denominator if denominator else None,
                     'success_rate': s['successes'] / s['samples'],
                     'quote_location_rate': s['verified_quotes'] / s['predictions'] if s['predictions'] else None,
                     'legal_recall': s['legal_tp'] / s['legal_positive'] if s['legal_positive'] else None,
                     'finance_recall': s['finance_tp'] / s['finance_positive'] if s['finance_positive'] else None}
    return {'status': 'descriptive_posthoc_human_review', 'independent_contracts': len(gold),
            'repeats_not_independent_contracts': 3, 'arms': arms,
            'limitation': '合成、小样本、探索运行后人工裁决；不是专家效力认证，不输出显著提升结论。'}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--gold', type=Path, required=True)
    p.add_argument('--review', type=Path, required=True)
    args = p.parse_args()
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    meta = load(args.run / 'run.json')
    if meta.get('status') != 'model_run_complete_pending_human_review':
        raise ValueError('模型运行未完成')
    results = [json.loads(line) for line in (args.run / 'results.jsonl').read_text(encoding='utf-8').splitlines()]
    gold = [g for g in load(args.gold) if g.get('split') == 'test']
    report = score_review(results, load(args.review), load(args.run / 'private-unblind-map.json'), gold)
    from evaluation.agent_comparison import digest
    report['input_hashes'] = {k: digest(path.read_bytes()) for k, path in
                             [('gold', args.gold), ('review', args.review),
                              ('results', args.run / 'results.jsonl')]}
    output = args.run / 'human-scored-summary.json'
    with output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(str(output))


if __name__ == '__main__':
    main()
