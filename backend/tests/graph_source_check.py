import unittest
from dataclasses import replace
from unittest.mock import patch
from sqlalchemy import select
from app.models import EvidenceSnapshot,EvidenceBinding
from tests.graph_test_support import graph_fixture, open_case
try:
    from app.graph.source import SourceReader
except ImportError:
    SourceReader = None
from app.graph.contracts import Budget, GraphError, GraphLimits


class GraphSources(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(SourceReader, 'A09 persistent source adapter missing')

    def test_capture_reads_persisted_values_not_current_engine(self):
        with graph_fixture() as (repo, engine, source):
            opened = open_case(repo)
            with patch('app.engine.engine.run_engine', side_effect=AssertionError('must not recompute history')):
                view = SourceReader(engine, source).capture(Budget())
            self.assertEqual(len(view['snapshots']), 1)
            self.assertEqual(view['bindings'][0]['owner_kind'], 'action_open')
            snap = view['snapshots'][0]
            self.assertEqual(snap['snapshotId'], opened['openingBinding']['snapshotId'])
            self.assertEqual(snap['payload']['factInsights'][0]['metric'], '18.1%')

    def test_corrupt_persistent_snapshot_blocks_source(self):
        with graph_fixture() as (repo, engine, source):
            open_case(repo)
            with repo._session_ctx() as s:
                row = s.scalar(select(EvidenceSnapshot)); row.payload_hash = 'broken'; s.commit()
            with self.assertRaises(GraphError) as caught: SourceReader(engine, source).capture(Budget())
            self.assertEqual(caught.exception.code, 'source_integrity_error')

    def test_source_limits_and_deadline_before_reads(self):
        with graph_fixture() as (repo, engine, source):
            open_case(repo)
            with self.assertRaises(GraphError) as caught:
                SourceReader(engine, source, limits=replace(GraphLimits(), maxSnapshots=0)).capture(Budget())
            self.assertEqual(caught.exception.code, 'build_input_limit')
            with self.assertRaises(GraphError): SourceReader(engine, source).capture(Budget(0))

    def test_deleted_instance_has_durable_status(self):
        with graph_fixture() as (repo, engine, source):
            opened = open_case(repo); reader = SourceReader(engine, source)
            first = reader.capture(Budget()); repo.delete_action_case(opened['case']['id'])
            second = reader.capture(Budget())
            key = 'binding:' + opened['openingBinding']['bindingId']
            self.assertEqual(first['records'][key]['hash'], second['records'][key]['hash'])
            self.assertEqual(second['records'][key]['status'], 'deleted')
            self.assertNotEqual(first['vector'], second['vector'])
    def test_binding_cannot_claim_a_different_fact_version(self):
        with graph_fixture() as (repo,engine,source):
            open_case(repo)
            with repo._session_ctx() as s:
                row=s.scalar(select(EvidenceBinding));context=dict(row.capture_context)
                context['factVersion']={**context['factVersion'],'generation':9999}
                row.capture_context=context;s.commit()
            with self.assertRaises(GraphError) as error:SourceReader(engine,source).capture(Budget())
            self.assertEqual(error.exception.code,'source_integrity_error')
    def test_opening_binding_cannot_point_to_another_valid_occurrence(self):
        with graph_fixture() as (repo,engine,source):
            opened=open_case(repo)
            with repo._session_ctx() as s:
                snapshot=s.scalar(select(EvidenceSnapshot))
                other=next(i for i in snapshot.payload['factInsights'] if i['id']=='p2')
                binding=s.scalar(select(EvidenceBinding));binding.occurrence_id=other['occurrenceId'];s.commit()
            with self.assertRaises(GraphError) as error:SourceReader(engine,source).capture(Budget())
            self.assertEqual(error.exception.code,'source_integrity_error')

    def test_binding_public_owner_and_watch_match_must_agree_with_capture(self):
        from app.watch.evaluator import evaluate_one
        for corrupt in ('owner','watch'):
            with self.subTest(corrupt=corrupt),graph_fixture() as (repo,engine,source):
                open_case(repo)
                if corrupt=='watch':
                    target=repo.create_watch_target('margin',dict(metric_key='margin',condition=dict(type='below',ref=100)))
                    evaluate_one(repo,target)
                with repo._session_ctx() as s:
                    kind='action_open' if corrupt=='owner' else 'watch_event'
                    row=s.scalar(select(EvidenceBinding).where(EvidenceBinding.owner_kind==kind))
                    if corrupt=='owner':row.owner_public_id='other-case'
                    else:
                        snapshot=s.get(EvidenceSnapshot,row.snapshot_id)
                        row.occurrence_id=next(i['occurrenceId'] for i in snapshot.payload['factInsights'] if i['id']=='p2')
                    s.commit()
                with self.assertRaises(GraphError) as error:SourceReader(engine,source).capture(Budget())
                self.assertEqual(error.exception.code,'source_integrity_error')


if __name__ == '__main__': unittest.main()
