import unittest
from dataclasses import replace
from unittest.mock import patch
from sqlalchemy import select,func,event
from tests.graph_test_support import graph_fixture,open_case
from app.graph.contracts import GraphError,Budget,GraphLimits
try:
    from app.graph.service import GraphService
except ImportError:
    GraphService=None


class GraphStoreChecks(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(GraphService,'A09 atomic graph service missing')
    def test_repeated_sync_rebuild_is_unchanged_and_no_new_members(self):
        from app.graph.models import GraphBuildBatch,GraphBuildMember
        with graph_fixture() as (repo,engine,source):
            open_case(repo);service=GraphService(engine,source)
            one=service.sync();two=service.sync();three=service.sync(rebuild=True)
            self.assertFalse(one['unchanged']);self.assertTrue(two['unchanged']);self.assertTrue(three['unchanged'])
            self.assertEqual(one['batchId'],two['batchId'])
            with repo._session_ctx() as s:
                self.assertEqual(s.scalar(select(func.count()).select_from(GraphBuildBatch)),1)
            self.assertTrue(service.reconcile()['ok'])

    def test_source_changes_during_projection_cannot_publish(self):
        from app.graph import service as module
        with graph_fixture() as (repo,engine,source):
            open_case(repo);service=GraphService(engine,source);first=service.sync()
            original=module.project
            def changed(*a,**kw):
                value=original(*a,**kw);repo.delete_action_case(repo.list_action_cases()[0]['id']);return value
            with patch.object(module,'project',changed),self.assertRaises(GraphError) as error:service.sync()
            self.assertEqual(error.exception.code,'source_changed')
            self.assertEqual(service.status()['batchId'],first['batchId'])

    def test_flush_failure_and_deadline_leave_no_partial_batch(self):
        from app.graph.models import GraphBuildBatch
        with graph_fixture() as (repo,engine,source):
            open_case(repo);service=GraphService(engine,source)
            def fail(conn,cursor,statement,params,context,many):
                if statement.startswith('INSERT INTO graph_build_member'):raise RuntimeError('injected membership write failure')
            event.listen(engine,'before_cursor_execute',fail)
            try:
                with self.assertRaises(RuntimeError):service.sync()
            finally:event.remove(engine,'before_cursor_execute',fail)
            with repo._session_ctx() as s:self.assertEqual(s.scalar(select(func.count()).select_from(GraphBuildBatch)),0)
            with self.assertRaises(GraphError):service.sync(budget=Budget(0))
            self.assertTrue(service.sync()['batchId'])

    def test_head_cas_corruption_and_reconcile_are_read_only(self):
        from app.graph.models import GraphEntity
        with graph_fixture() as (repo,engine,source):
            open_case(repo);service=GraphService(engine,source);first=service.sync()
            with self.assertRaises(GraphError) as error:service.sync(expected_head='obsolete')
            self.assertEqual(error.exception.code,'head_changed')
            with repo._session_ctx() as s:
                row=s.scalar(select(GraphEntity));row.data={**row.data,'sourceLevel':'forged'};s.commit()
            self.assertFalse(service.reconcile()['ok'])
            with self.assertRaises(GraphError):service.sync()

    def test_missing_schema_and_failed_migration_do_not_create_on_read(self):
        from app.graph.migrations import init_graph,require_graph_ready
        from app.graph.models import GraphRelationEvidence
        with graph_fixture() as (repo,engine,source):
            init_graph(engine);GraphRelationEvidence.__table__.drop(engine)
            with self.assertRaises(GraphError):require_graph_ready(engine)
            init_graph(engine);require_graph_ready(engine)
            with patch.object(GraphRelationEvidence.__table__,'create',side_effect=RuntimeError('migration failed')):
                with self.assertRaises(GraphError):init_graph(engine)
            with self.assertRaises(GraphError):require_graph_ready(engine)
            init_graph(engine);require_graph_ready(engine)
    def test_old_successful_batch_remains_readable_above_build_source_limit(self):
        from app.graph.contracts import GraphRequest
        from app.graph.models import GraphEntity
        from tests.evidence_test_support import raw_inputs
        with graph_fixture() as (repo,engine,source):
            opened=open_case(repo);service=GraphService(engine,source,limits=replace(GraphLimits(),maxSnapshots=1));first=service.sync()
            with repo._session_ctx() as s:root=next(n.data['id'] for n in s.scalars(select(GraphEntity)) if n.data['type']=='ActionCase')
            request=GraphRequest(entityId=root,mode='historical',batchId=first['batchId'],includeSimulated=True)
            before=service.neighborhood(request)
            repo.upsert_series(raw_inputs(margin=17)['rows']);open_case(repo)
            with self.assertRaises(GraphError) as error:service.sync()
            self.assertEqual(error.exception.code,'build_input_limit')
            self.assertTrue(service.status()['ready'])
            after=service.neighborhood(request)
            self.assertEqual(before['nodes'],after['nodes']);self.assertEqual(before['relations'],after['relations'])
            self.assertEqual(after['sourceState'],'pending')
            edge=next(e for e in before['relations'] if e['type']=='opened_from')
            evidence=service.evidence(edge['id'],first['batchId'],include_simulated=True)
            self.assertEqual(evidence['relations'],[edge]);self.assertTrue(evidence['evidence'])

    def test_reconcile_reports_missing_member_without_repairing_it(self):
        from sqlalchemy import delete
        from app.graph.models import GraphBuildMember
        with graph_fixture() as (repo,engine,source):
            open_case(repo);service=GraphService(engine,source);batch=service.sync()
            with repo._session_ctx() as s:
                row=s.scalar(select(GraphBuildMember).where(GraphBuildMember.item_kind=='entity'))
                s.delete(row);s.commit()
            statements=[]
            def track(conn,cursor,statement,*a):statements.append(statement.strip().split()[0].upper())
            event.listen(engine,'before_cursor_execute',track)
            try:result=service.reconcile()
            finally:event.remove(engine,'before_cursor_execute',track)
            self.assertFalse(result['ok']);self.assertIn('graph_integrity_conflict',result['issues'])
            self.assertFalse(set(statements)&{'INSERT','UPDATE','DELETE'})


if __name__=='__main__':unittest.main()
