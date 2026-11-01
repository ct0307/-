"""单窗口单角色子图：本地回放、持久预算及受权人工恢复。"""
import time
from threading import Event, Thread
import sqlite3

from contextlib import closing, suppress
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .repository import encoded
from .checkpoints import ObservedSqliteSaver
from .state import AccessDenied, FlowIssue, PilotState, StaleRun, fingerprint


class Pilot:
    def __init__(self, store, checkpoint_path, identity, token, operations, contract, limits,
                 *, clock=time.time, after_call=None, heartbeat_interval=5):
        if fingerprint(contract) != identity.contract_hash:
            raise StaleRun('合同正文与身份哈希不一致')
        self.store, self.identity, self.token = store, identity, token
        self.operations, self.contract, self.limits = operations, contract, limits
        self.clock, self.after_call = clock, after_call
        if heartbeat_interval <= 0:
            raise ValueError('心跳间隔必须为正数')
        self.heartbeat_interval = heartbeat_interval
        self.checkpoint_path = str(checkpoint_path)
        self.config = {'configurable': {'thread_id': identity.thread_id}, 'recursion_limit': 150,
                       'callbacks': []}

    def __enter__(self):
        self._context = closing(sqlite3.connect(self.checkpoint_path, check_same_thread=False))
        connection = self._context.__enter__()
        saver = ObservedSqliteSaver(connection,
            lambda checkpoint: self.store.record_checkpoint(self.identity, self.token, checkpoint))
        builder = StateGraph(PilotState)
        for name in ['guard', 'discover', 'enrich', 'next_page', 'review', 'snapshot', 'human', 'publish']:
            builder.add_node(name, self._observed(name, getattr(self, '_' + name)))
        builder.add_edge(START, 'guard')
        builder.add_edge('guard', 'discover')
        builder.add_conditional_edges('discover', self._after_work)
        builder.add_conditional_edges('enrich', self._after_work)
        builder.add_edge('next_page', 'discover')
        builder.add_edge('review', 'snapshot')
        builder.add_conditional_edges('snapshot', lambda s: 'human' if s['candidates'] or s['issues'] else 'publish')
        builder.add_conditional_edges('human', lambda s: END if s.get('decision') == 'reject' else 'publish')
        builder.add_edge('publish', END)
        self.graph = builder.compile(checkpointer=saver)
        return self

    def __exit__(self, *args):
        return self._context.__exit__(*args)

    def _check(self):
        self.store.check(self.identity, self.token)

    def _observed(self, name, operation):
        def invoke(state):
            self.store.event(self.identity, self.token, name, 'started')
            try:
                result = operation(state)
            except GraphInterrupt:
                self.store.event(self.identity, self.token, name, 'interrupted')
                raise
            except Exception:
                # 事件库也可能不可用，不能用记录失败覆盖原始执行异常。
                with suppress(Exception):
                    self.store.event(self.identity, self.token, name, 'failed')
                raise
            self.store.event(self.identity, self.token, name, 'computed')
            return dict(result, last_node=name)
        return invoke

    def _finish(self, state):
        if state.get('__interrupt__'):
            self.store.set_interrupt(self.identity, self.token, state['__interrupt__'][0].id)
        return state

    def start(self, *, conflict_ids=()):
        self.store.bind_limits(self.identity, self.token, self.limits)
        if self.graph.get_state(self.config).values:
            raise StaleRun('运行已经存在，请使用恢复入口')
        seed = dict(page=1, findings=[], candidates=[], has_more=False, issues=[],
                    conflict_ids=list(conflict_ids), status='running', decision='')
        return self._finish(self.graph.invoke(seed, self.config, durability='sync'))

    def continue_run(self):
        self.store.bind_limits(self.identity, self.token, self.limits)
        if not self.graph.get_state(self.config).values:
            raise StaleRun('没有可恢复的图状态')
        self._reconcile_checkpoint()
        return self._finish(self.graph.invoke(None, self.config, durability='sync'))

    def resume(self, principal, marker, decision):
        self.store.bind_limits(self.identity, self.token, self.limits)
        self.store.decide(self.identity, self.token, principal, marker, decision)
        snapshot = self.graph.get_state(self.config)
        self._reconcile_checkpoint()
        if not snapshot.next:
            return dict(snapshot.values)
        return self._finish(self.graph.invoke(Command(resume={'marker': marker}), self.config, durability='sync'))

    def _reconcile_checkpoint(self):
        stored = self.graph.checkpointer.get_tuple(self.config)
        if stored is not None:
            self.store.record_checkpoint(self.identity, self.token, stored.checkpoint)

    def _guard(self, state):
        self._check()
        return {}

    def _call(self, key, payload, operation):
        # 与生产相同，使用保守字节数加最大输出预留；不是精确 token 计费。
        estimate = len(self.contract.encode()) + len(encoded(payload).encode()) + 3200
        cached = self.store.reserve(self.identity, self.token, key, estimate, self.limits, self.clock())
        if cached is not None:
            return cached
        # 异常保持 pending：无法确定供应商是否执行，恢复不静默再次计费。
        stopped = Event()
        def heartbeat():
            while not stopped.wait(self.heartbeat_interval):
                try:
                    self.store.event(self.identity, self.token, key.split(':')[0], 'heartbeat')
                except (StaleRun, OSError, sqlite3.Error):
                    return
        worker = Thread(target=heartbeat, daemon=True)
        worker.start()
        try:
            self._check()
            result = operation()
        finally:
            stopped.set()
            worker.join(timeout=10)
        if type(result.payload) is not dict or type(result.usage_tokens) is not int or result.usage_tokens < 0:
            raise ValueError('操作结果必须提供结构化对象和非负 token 计数')
        self.store.settle(self.identity, self.token, key, result)
        if self.after_call is not None:
            self.after_call(key)
        return result.payload

    @staticmethod
    def _issue(state, code):
        return {'issues': list(dict.fromkeys([*state['issues'], code]))}

    def _discover(self, state):
        page = state['page']
        try:
            raw = self._call(f'discover:{page}', {'page': page, 'accepted': state['candidates']},
                             lambda: self.operations.discover(page, state['candidates']))
        except FlowIssue as error:
            return self._issue(state, str(error))
        if set(raw) != {'items', 'has_more'} or type(raw['items']) is not list or type(raw['has_more']) is not bool or len(raw['items']) > 5:
            return self._issue(state, 'INVALID_MODEL_OUTPUT')
        known = {item['id'] for item in state['candidates']}
        findings = []
        for item in raw['items']:
            if (type(item) is not dict or set(item) != {'id', 'category', 'quote'}
                    or any(type(item[k]) is not str or not item[k].strip() for k in item)
                    or len(item['id']) > 64 or len(item['quote']) > 1000 or len(item['category']) > 128):
                return self._issue(state, 'INVALID_MODEL_OUTPUT')
            if item['quote'] not in self.contract:
                return self._issue(state, 'ORIGINAL_TEXT_UNRESOLVED')
            if item['id'] not in known:
                findings.append(dict(item))
                known.add(item['id'])
        return dict(findings=findings, has_more=raw['has_more'])

    def _enrich(self, state):
        completed = {item['id'] for item in state['candidates']}
        finding = next(item for item in state['findings'] if item['id'] not in completed)
        try:
            raw = self._call('enrich:' + finding['id'], finding, lambda: self.operations.enrich(finding))
        except FlowIssue as error:
            return self._issue(state, str(error))
        if set(raw) != {'reason', 'suggestion'} or any(type(value) is not str or not value.strip() or len(value) > 1000 for value in raw.values()):
            return self._issue(state, 'INVALID_MODEL_OUTPUT')
        candidate = dict(**finding, **raw, original_verified=True, evidence_supported=False)
        return dict(candidates=[*state['candidates'], candidate])

    def _after_work(self, state):
        if state['issues']:
            return 'snapshot'
        completed = {item['id'] for item in state['candidates']}
        if any(item['id'] not in completed for item in state['findings']):
            return 'enrich'
        if state['has_more']:
            if state['page'] >= self.limits.max_pages:
                return 'review'
            # 路由只决定下一步；页游标由单独节点更新，避免修改未检查点的状态。
            return 'next_page'
        return 'review'

    def _review(self, state):
        if state['has_more'] and state['page'] >= self.limits.max_pages:
            return self._issue(state, 'PAGINATION_EXHAUSTED')
        if not state['conflict_ids']:
            return {}
        bound = [item for item in state['candidates'] if item['id'] in state['conflict_ids']]
        if {item['id'] for item in bound} != set(state['conflict_ids']):
            return self._issue(state, 'UNBOUND_CONFLICT')
        try:
            raw = self._call('review', {'candidates': bound}, lambda: self.operations.review(bound))
        except FlowIssue as error:
            return self._issue(state, str(error))
        if (set(raw) != {'verdict', 'claim_ids'} or type(raw['verdict']) is not str
                or raw['verdict'] not in {'agree', 'disagree', 'unclear'}
                or type(raw['claim_ids']) is not list or any(type(x) is not str for x in raw['claim_ids'])
                or set(raw['claim_ids']) != set(state['conflict_ids'])):
            return self._issue(state, 'INVALID_MODEL_OUTPUT')
        return {} if raw['verdict'] == 'agree' else self._issue(state, 'CONFLICT_UNRESOLVED')

    def _next_page(self, state):
        return {'page': state['page'] + 1, 'findings': []}

    def _snapshot(self, state):
        return {'status': 'review_required' if state['candidates'] or state['issues'] else 'done'}

    def _human(self, state):
        self._check()
        answer = interrupt({'reason_codes': state['issues'], 'candidate_count': len(state['candidates']),
                            'generation': self.identity.generation})
        if type(answer) is not dict or set(answer) != {'marker'}:
            raise AccessDenied('恢复必须使用服务端人工入口')
        decision = self.store.decision(self.identity, self.token, answer['marker'])
        return {'decision': decision, 'status': 'rejected' if decision == 'reject' else state['status']}

    def _publish(self, state):
        snapshot = {key: state[key] for key in ('status', 'candidates', 'issues')}
        self.store.publish(self.identity, self.token, snapshot)
        return {}
