"""用真实进程退出演示检查点恢复，数据全部为合成回放。"""
import argparse
import json
import os
from pathlib import Path

from .graph import Pilot
from .repository import PilotStore
from .replay import ReplayOperations
from .state import Limits, RunIdentity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('mode', choices=['crash', 'resume', 'demo'])
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    contract = '甲方验收后付款，乙方提供发票。'
    identity = RunIdentity.create(contract_id=1, job_id=2, generation=1,
        fingerprint='fixture-v1', contract=contract, knowledge_revision=3, role='legal', window_id='w1')
    store = PilotStore(args.directory / 'business.db')
    store.register(identity, 'fixture-execution-token')
    store.grant('reviewer', 1)
    # 固定的合成时间基准保证跨进程预算/时限完全一致，不代表真实服务器时间。
    limits = Limits(max_calls=10, max_tokens=100000, deadline=2000)
    operations = ReplayOperations(['验收后付款'])
    def crash(key):
        if args.mode == 'crash' and key == 'enrich:c1':
            os._exit(73)
    with Pilot(store, args.directory/'graph.db', identity, 'fixture-execution-token',
               operations, contract, limits, clock=lambda: 1000, after_call=crash) as pilot:
        result = pilot.continue_run() if args.mode == 'resume' else pilot.start()
        if result.get('__interrupt__'):
            result = pilot.resume('reviewer', result['__interrupt__'][0].id, 'approve')
    summary = dict(status=result['status'], candidate_count=len(result['candidates']),
                   new_external_calls=operations.calls, total_reserved_calls=store.budget(identity)['calls'],
                   publications=store.publication_count(identity), events=store.events(identity),
                   evidence='合成回放仅验证流程和恢复，不证明法律质量或性能提升')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
