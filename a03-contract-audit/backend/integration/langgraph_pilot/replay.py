"""合成回放操作，不访问网络、不代表真实审查准确率。"""
from .state import OperationResult


class ReplayOperations:
    def __init__(self, quotes, *, verdict='agree', has_more=False, fail_on=None):
        self.quotes = quotes
        self.verdict = verdict
        self.has_more = has_more
        self.fail_on = fail_on
        self.calls = []

    def _record(self, key):
        self.calls.append(key)
        if key == self.fail_on:
            raise RuntimeError('合成外部调用状态未知')

    def discover(self, page, accepted):
        self._record(f'discover:{page}')
        items = [dict(id=f'c{i+1}', category='付款风险', quote=quote)
                 for i, quote in enumerate(self.quotes)] if page == 1 else []
        return OperationResult(dict(items=items, has_more=self.has_more), usage_tokens=20)

    def enrich(self, finding):
        self._record('enrich:' + finding['id'])
        return OperationResult(dict(reason='合成待核理由', suggestion='合成待核建议'), usage_tokens=10)

    def review(self, candidates):
        self._record('review')
        return OperationResult(dict(verdict=self.verdict, claim_ids=[x['id'] for x in candidates]), usage_tokens=10)
