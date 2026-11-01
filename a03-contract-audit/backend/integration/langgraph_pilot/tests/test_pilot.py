"""只用合成回放验证编排、恢复与围栏，不评估法律准确率。"""
from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from integration.langgraph_pilot.state import Limits, RunIdentity, StaleRun, AccessDenied
from integration.langgraph_pilot.repository import PilotStore
from integration.langgraph_pilot.graph import Pilot
from integration.langgraph_pilot.replay import ReplayOperations


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.contract = '甲方验收后付款，乙方提供发票。'
        self.identity = RunIdentity.create(contract_id=1, job_id=2, generation=1,
            fingerprint='fixture-v1', contract=self.contract, knowledge_revision=3,
            role='legal', window_id='w1')
        self.store = PilotStore(self.root / 'business.db')
        self.store.register(self.identity, 'token-a')
        self.store.grant('reviewer', 1)
        self.limits = Limits(max_calls=10, max_tokens=100000, deadline=2000)

    def tearDown(self):
        self.temp.cleanup()

    def pilot(self, operations, *, identity=None, token='token-a', limits=None, after_call=None, clock=None):
        return Pilot(self.store, self.root / 'graph.db', identity or self.identity, token,
                     operations, self.contract, limits or self.limits,
                     clock=clock or (lambda: 1000), after_call=after_call)

    def approve(self, pilot, state):
        return pilot.resume('reviewer', state['__interrupt__'][0].id, 'approve')

    def test_empty_discovery_publishes_without_review_call(self):
        operations = ReplayOperations([])
        with self.pilot(operations) as pilot:
            state = pilot.start()
        self.assertEqual(state['status'], 'done')
        self.assertEqual(operations.calls, ['discover:1'])
        self.assertEqual(self.store.publication_count(self.identity), 1)

    def test_candidate_requires_human_and_does_not_upgrade_evidence(self):
        operations = ReplayOperations(['验收后付款'])
        with self.pilot(operations) as pilot:
            state = pilot.start()
            self.assertIn('__interrupt__', state)
            self.assertEqual(self.store.publication_count(self.identity), 0)
            state = self.approve(pilot, state)
        self.assertEqual(state['status'], 'review_required')
        self.assertFalse(state['candidates'][0]['evidence_supported'])
        self.assertEqual(operations.calls, ['discover:1', 'enrich:c1'])

    def test_conflict_permits_only_one_review_even_if_unclear(self):
        operations = ReplayOperations(['验收后付款'], verdict='unclear')
        with self.pilot(operations) as pilot:
            state = pilot.start(conflict_ids=['c1'])
            state = self.approve(pilot, state)
        self.assertEqual(operations.calls.count('review'), 1)
        self.assertIn('CONFLICT_UNRESOLVED', state['issues'])
        self.assertEqual(state['status'], 'review_required')

    def test_call_budget_blocks_enrichment_with_accurate_code(self):
        operations = ReplayOperations(['验收后付款'])
        with self.pilot(operations, limits=replace(self.limits, max_calls=1)) as pilot:
            state = pilot.start()
            self.assertIn('AUDIT_BUDGET_EXHAUSTED', state['issues'])
            self.assertEqual(operations.calls, ['discover:1'])
            self.assertEqual(self.store.budget(self.identity)['calls'], 1)

    def test_token_budget_blocks_before_external_operation(self):
        operations = ReplayOperations([])
        with self.pilot(operations, limits=replace(self.limits, max_tokens=1)) as pilot:
            state = pilot.start()
        self.assertIn('AUDIT_BUDGET_EXHAUSTED', state['issues'])
        self.assertEqual(operations.calls, [])

    def test_expired_deadline_blocks_before_external_operation(self):
        operations = ReplayOperations([])
        with self.pilot(operations, clock=lambda: 2001) as pilot:
            state = pilot.start()
        self.assertIn('AUDIT_DEADLINE_EXCEEDED', state['issues'])
        self.assertEqual(operations.calls, [])

    def test_response_saved_before_node_crash_is_reused_on_reopen(self):
        operations = ReplayOperations(['验收后付款'])
        def crash(key):
            if key == 'enrich:c1':
                raise RuntimeError('合成检查点前崩溃')
        with self.pilot(operations, after_call=crash) as pilot:
            with self.assertRaises(RuntimeError):
                pilot.start()
        before = self.store.budget(self.identity)['calls']
        with self.pilot(operations) as pilot:
            state = pilot.continue_run()
            self.approve(pilot, state)
        self.assertEqual(operations.calls, ['discover:1', 'enrich:c1'])
        self.assertEqual(self.store.budget(self.identity)['calls'], before)

    def test_uncertain_external_call_is_not_silently_retried(self):
        operations = ReplayOperations(['验收后付款'], fail_on='enrich:c1')
        with self.pilot(operations) as pilot:
            with self.assertRaises(RuntimeError):
                pilot.start()
        with self.pilot(operations) as pilot:
            state = pilot.continue_run()
        self.assertIn('UNCERTAIN_EXTERNAL_CALL', state['issues'])
        self.assertEqual(operations.calls.count('enrich:c1'), 1)
        self.assertEqual(self.store.budget(self.identity)['pending'], 1)

    def test_human_resume_denies_wrong_user_and_wrong_interrupt(self):
        operations = ReplayOperations(['验收后付款'])
        with self.pilot(operations) as pilot:
            state = pilot.start()
            marker = state['__interrupt__'][0].id
            with self.assertRaises(AccessDenied):
                pilot.resume('intruder', marker, 'approve')
            with self.assertRaises(AccessDenied):
                pilot.resume('reviewer', 'forged-interrupt', 'approve')
            self.assertEqual(self.store.publication_count(self.identity), 0)
            self.approve(pilot, state)

    def test_duplicate_resume_is_idempotent_and_cannot_change_decision(self):
        with self.pilot(ReplayOperations(['验收后付款'])) as pilot:
            state = pilot.start()
            marker = state['__interrupt__'][0].id
            pilot.resume('reviewer', marker, 'approve')
            pilot.resume('reviewer', marker, 'approve')
            with self.assertRaises(AccessDenied):
                pilot.resume('reviewer', marker, 'reject')
        self.assertEqual(self.store.publication_count(self.identity), 1)

    def test_rejection_does_not_publish(self):
        with self.pilot(ReplayOperations(['验收后付款'])) as pilot:
            state = pilot.start()
            state = pilot.resume('reviewer', state['__interrupt__'][0].id, 'reject')
        self.assertEqual(state['status'], 'rejected')
        self.assertEqual(self.store.publication_count(self.identity), 0)

    def test_new_generation_fences_old_resume(self):
        with self.pilot(ReplayOperations(['验收后付款'])) as pilot:
            state = pilot.start()
            self.store.replace_authority(replace(self.identity, generation=2), 'token-b')
            with self.assertRaises(StaleRun):
                self.approve(pilot, state)

    def test_new_execution_token_fences_old_execution(self):
        with self.pilot(ReplayOperations([])) as pilot:
            self.store.replace_authority(self.identity, 'token-b')
            with self.assertRaises(StaleRun):
                pilot.start()

    def test_changed_contract_is_rejected(self):
        with self.assertRaises(StaleRun):
            Pilot(self.store, self.root/'graph.db', self.identity, 'token-a',
                  ReplayOperations([]), '被替换的正文', self.limits)

    def test_changed_fingerprint_cannot_reuse_old_state(self):
        with self.pilot(ReplayOperations([]), identity=replace(self.identity, fingerprint='v2')) as pilot:
            with self.assertRaises(StaleRun):
                pilot.start()

    def test_changed_knowledge_revision_is_fenced(self):
        with self.pilot(ReplayOperations([]), identity=replace(self.identity, knowledge_revision=4)) as pilot:
            with self.assertRaises(StaleRun):
                pilot.start()

    def test_cross_contract_resume_is_denied(self):
        with self.pilot(ReplayOperations(['验收后付款'])) as pilot:
            state = pilot.start()
        other = replace(self.identity, contract_id=99)
        self.store.register(other, 'token-c')
        with self.pilot(ReplayOperations([]), identity=other, token='token-c') as other_pilot:
            with self.assertRaises(AccessDenied):
                other_pilot.resume('reviewer', state['__interrupt__'][0].id, 'approve')

    def test_model_quote_not_in_contract_is_not_accepted(self):
        with self.pilot(ReplayOperations(['伪造原文'])) as pilot:
            state = pilot.start()
        self.assertIn('ORIGINAL_TEXT_UNRESOLVED', state['issues'])
        self.assertEqual(state['candidates'], [])

    def test_unbounded_pagination_stops_at_limit(self):
        with self.pilot(ReplayOperations([], has_more=True), limits=replace(self.limits, max_pages=2)) as pilot:
            state = pilot.start()
        self.assertIn('PAGINATION_EXHAUSTED', state['issues'])
        self.assertEqual(self.store.budget(self.identity)['calls'], 2)

    def test_budget_limits_cannot_be_refreshed_after_reopen(self):
        with self.pilot(ReplayOperations(['验收后付款']), limits=replace(self.limits, max_calls=1)) as pilot:
            pilot.start()
        with self.assertRaises(StaleRun):
            with self.pilot(ReplayOperations([]), limits=replace(self.limits, max_calls=20)) as pilot:
                pilot.continue_run()

    def test_events_are_ordered_and_contain_no_contract_text(self):
        with self.pilot(ReplayOperations(['验收后付款'])) as pilot:
            pilot.start()
        events = self.store.events(self.identity)
        self.assertEqual([x['sequence'] for x in events], list(range(1, len(events)+1)))
        self.assertIn('enrich', [x['node'] for x in events])
        self.assertNotIn(self.contract, str(events))

    def test_events_include_real_timestamp_and_completed_count(self):
        with self.pilot(ReplayOperations(['验收后付款'])) as pilot:
            pilot.start()
        events = self.store.events(self.identity)
        self.assertTrue(all(x['timestamp'] > 0 for x in events))
        self.assertTrue(any(x['completed_count'] == 1 for x in events))

    def test_invalid_enrichment_stops_and_preserves_previous_candidates(self):
        operations = ReplayOperations(['验收后付款', '提供发票'])
        original = operations.enrich
        def enrich(finding):
            result = original(finding)
            if finding['id'] == 'c2':
                return replace(result, payload={'reason': ''})
            return result
        operations.enrich = enrich
        with self.pilot(operations) as pilot:
            state = pilot.start()
        self.assertIn('INVALID_MODEL_OUTPUT', state['issues'])
        self.assertEqual(len(state['candidates']), 1)

    def test_store_failure_keeps_unknown_call_reserved(self):
        operations = ReplayOperations(['验收后付款'])
        with self.pilot(operations) as pilot:
            with patch.object(self.store, 'settle', side_effect=OSError('合成磁盘错误')):
                with self.assertRaises(OSError):
                    pilot.start()
        with self.pilot(operations) as pilot:
            state = pilot.continue_run()
        self.assertIn('UNCERTAIN_EXTERNAL_CALL', state['issues'])
        self.assertEqual(operations.calls, ['discover:1'])
        self.assertEqual(self.store.budget(self.identity)['pending'], 1)
        self.assertEqual(self.store.publication_count(self.identity), 0)

    def test_publish_committed_before_graph_crash_is_idempotent(self):
        operations = ReplayOperations(['验收后付款'])
        original = self.store.publish
        def crash_after_publish(*args):
            original(*args)
            raise RuntimeError('合成发布确认前崩溃')
        with self.pilot(operations) as pilot:
            state = pilot.start()
            with patch.object(self.store, 'publish', side_effect=crash_after_publish):
                with self.assertRaises(RuntimeError):
                    self.approve(pilot, state)
        with self.pilot(operations) as pilot:
            state = pilot.continue_run()
        self.assertEqual(state['status'], 'review_required')
        self.assertEqual(self.store.publication_count(self.identity), 1)
        self.assertEqual(operations.calls, ['discover:1', 'enrich:c1'])

    def test_new_fingerprint_same_business_generation_does_not_duplicate_publish(self):
        snapshot = dict(status='done', candidates=[], issues=[])
        self.store.publish(self.identity, 'token-a', snapshot)
        updated = replace(self.identity, fingerprint='replacement-v2')
        self.store.replace_authority(updated, 'token-b')
        self.store.publish(updated, 'token-b', snapshot)
        self.assertEqual(self.store.publication_count(updated), 1)
        with self.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM publications').fetchone()[0], 1)
        with self.assertRaises(StaleRun):
            self.store.publish(updated, 'token-b', dict(snapshot, status='review_required'))

    def test_expired_human_wait_does_not_refresh_deadline_or_add_calls(self):
        operations = ReplayOperations(['验收后付款'])
        with self.pilot(operations) as pilot:
            state = pilot.start()
            marker = state['__interrupt__'][0].id
        with self.pilot(operations, clock=lambda: 3000) as pilot:
            state = pilot.resume('reviewer', marker, 'approve')
        self.assertEqual(state['status'], 'review_required')
        self.assertEqual(operations.calls, ['discover:1', 'enrich:c1'])

    def test_real_process_exit_and_restart_reuses_saved_response(self):
        folder = self.root / 'process-case'
        environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[3]),
                       'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
        command = [sys.executable, '-m', 'integration.langgraph_pilot.worker', str(folder)]
        crashed = subprocess.run([*command, 'crash'], env=environment, capture_output=True, timeout=45)
        self.assertEqual(crashed.returncode, 73, crashed.stderr.decode('utf-8', errors='replace'))
        resumed = subprocess.run([*command, 'resume'], env=environment, capture_output=True, timeout=45)
        self.assertEqual(resumed.returncode, 0, resumed.stderr.decode('utf-8', errors='replace'))
        summary = json.loads(resumed.stdout)
        self.assertEqual(summary['new_external_calls'], [])
        self.assertEqual(summary['total_reserved_calls'], 2)
        self.assertEqual(summary['publications'], 1)

    def test_cloud_tracing_is_disabled(self):
        self.assertEqual(os.environ.get('LANGSMITH_TRACING'), 'false')
        self.assertEqual(os.environ.get('LANGCHAIN_TRACING_V2'), 'false')

    def test_waiting_operation_emits_heartbeat_without_advancing_completed_count(self):
        operations = ReplayOperations([])
        original = operations.discover
        def wait_for_heartbeat(page, accepted):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(x['kind'] == 'heartbeat' for x in self.store.events(self.identity)):
                    return original(page, accepted)
                time.sleep(0.01)
            self.fail('等待外部响应期间没有产生心跳')
        operations.discover = wait_for_heartbeat
        with Pilot(self.store, self.root/'graph.db', self.identity, 'token-a', operations,
                   self.contract, self.limits, clock=lambda: 1000, heartbeat_interval=0.02) as pilot:
            pilot.start()
        heartbeats = [x for x in self.store.events(self.identity) if x['kind'] == 'heartbeat']
        self.assertTrue(heartbeats)
        self.assertTrue(all(x['completed_count'] == 0 for x in heartbeats))

    def test_non_string_verdict_becomes_invalid_output_instead_of_crashing(self):
        operations = ReplayOperations(['验收后付款'], verdict=[])
        with self.pilot(operations) as pilot:
            state = pilot.start(conflict_ids=['c1'])
        self.assertIn('INVALID_MODEL_OUTPUT', state['issues'])
        self.assertEqual(state['status'], 'review_required')

    def test_failed_graph_checkpoint_does_not_emit_completed_work(self):
        with self.pilot(ReplayOperations(['验收后付款'])) as pilot:
            saver = pilot.graph.checkpointer
            original = saver.put
            original_writes = saver.put_writes
            def fail_candidate_checkpoint(config, checkpoint, metadata, versions):
                if checkpoint.get('channel_values', {}).get('candidates'):
                    raise OSError('合成图检查点写入失败')
                return original(config, checkpoint, metadata, versions)
            def fail_candidate_writes(config, writes, task_id, task_path=''):
                if any(key == 'candidates' and value for key, value in writes):
                    raise OSError('合成图写集保存失败')
                return original_writes(config, writes, task_id, task_path)
            with patch.object(saver, 'put', side_effect=fail_candidate_checkpoint), patch.object(saver, 'put_writes', side_effect=fail_candidate_writes):
                with self.assertRaises(OSError):
                    pilot.start()
            persisted = pilot.graph.get_state(pilot.config).values
        self.assertEqual(persisted.get('candidates'), [])
        self.assertFalse(any(x['completed_count'] > 0 for x in self.store.events(self.identity)))

    def test_failed_empty_discovery_checkpoint_cannot_publish_downstream(self):
        with self.pilot(ReplayOperations([])) as pilot:
            saver = pilot.graph.checkpointer
            original = saver.put
            original_writes = saver.put_writes
            def fail_discovery(config, checkpoint, metadata, versions):
                if metadata.get('step', -1) >= 2:
                    raise OSError('合成发现节点保存失败')
                return original(config, checkpoint, metadata, versions)
            def fail_discovery_writes(config, writes, task_id, task_path=''):
                if any(key == 'has_more' for key, _ in writes):
                    raise OSError('合成发现写集失败')
                return original_writes(config, writes, task_id, task_path)
            with patch.object(saver, 'put', side_effect=fail_discovery), patch.object(saver, 'put_writes', side_effect=fail_discovery_writes):
                with self.assertRaises(OSError):
                    pilot.start()
        self.assertEqual(self.store.publication_count(self.identity), 0)

    def test_failure_and_human_interruption_have_explicit_event_types(self):
        operations = ReplayOperations(['验收后付款'], fail_on='enrich:c1')
        with self.pilot(operations) as pilot:
            with self.assertRaises(RuntimeError):
                pilot.start()
        self.assertIn('failed', [x['kind'] for x in self.store.events(self.identity)])
        with self.pilot(operations) as pilot:
            pilot.continue_run()
        self.assertIn('interrupted', [x['kind'] for x in self.store.events(self.identity)])

    def test_committed_checkpoint_event_failure_is_reconciled_without_extra_calls(self):
        operations = ReplayOperations(['验收后付款'])
        original = self.store.record_checkpoint
        failed = []
        def fail_one_event(identity, token, checkpoint):
            if checkpoint.get('channel_values', {}).get('last_node') == 'enrich' and not failed:
                failed.append(True)
                raise OSError('合成事件库故障')
            return original(identity, token, checkpoint)
        with self.pilot(operations) as pilot:
            with patch.object(self.store, 'record_checkpoint', side_effect=fail_one_event):
                with self.assertRaises(OSError):
                    pilot.start()
        with self.pilot(operations) as pilot:
            state = pilot.continue_run()
            self.approve(pilot, state)
            before = len(self.store.events(self.identity))
            pilot._reconcile_checkpoint()
            pilot._reconcile_checkpoint()
            self.assertEqual(len(self.store.events(self.identity)), before)
        self.assertEqual(operations.calls, ['discover:1', 'enrich:c1'])
        self.assertEqual(self.store.publication_count(self.identity), 1)


if __name__ == '__main__':
    unittest.main()
