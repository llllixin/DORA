import unittest,json
from dataclasses import replace
from unittest.mock import patch
from sqlalchemy import event
from tests.graph_test_support import graph_fixture,open_case
from app.graph.service import GraphService
from app.graph.contracts import GraphError,GraphRequest,GraphLimits


class GraphQueries(unittest.TestCase):
    def setUp(self):self.assertTrue(hasattr(GraphService,'neighborhood'),'A09 finite query is missing')
    def prepare(self,repo,engine,source,limits=None):
        opened=open_case(repo);service=GraphService(engine,source,limits=limits);batch=service.sync()
        from app.graph.models import GraphEntity
        from sqlalchemy import select
        with repo._session_ctx() as s:
            root=next(r.data for r in s.scalars(select(GraphEntity)) if r.data['type']=='ActionCase')
        return opened,service,batch,root['id']

    def test_simulation_requires_opt_in_and_all_edges_close(self):
        with graph_fixture() as (repo,engine,source):
            opened,service,batch,root=self.prepare(repo,engine,source)
            with self.assertRaises(GraphError) as error:service.neighborhood(GraphRequest(entityId=root))
            self.assertEqual(error.exception.status_code,404)
            value=service.neighborhood(GraphRequest(entityId=root,includeSimulated=True,maxHops=2))
            self.assertTrue(value['relations']);self.assertIn('simulated_sources',value['warnings'])
            ids={n['id'] for n in value['nodes']};relations={r['id'] for r in value['relations']}
            self.assertTrue(all(r['from'] in ids and r['to'] in ids for r in value['relations']))
            self.assertEqual({w['relationId'] for w in value['evidence']},relations)
            self.assertEqual(value['mode'],'current')

    def test_current_deleted_root_hidden_history_stable(self):
        with graph_fixture() as (repo,engine,source):
            opened,service,batch,root=self.prepare(repo,engine,source)
            request=GraphRequest(entityId=root,mode='historical',batchId=batch['batchId'],includeSimulated=True)
            before=service.neighborhood(request);repo.delete_action_case(opened['case']['id'])
            with self.assertRaises(GraphError):service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
            after=service.neighborhood(request)
            self.assertEqual(before['nodes'],after['nodes']);self.assertEqual(before['relations'],after['relations'])
            self.assertTrue(any(w['sourceCurrentStatus']=='deleted' for w in after['evidence']))
            self.assertEqual(after['sourceState'],'pending')

    def test_expected_revision_checked_and_other_batch_not_found(self):
        with graph_fixture() as (repo,engine,source):
            _,service,batch,root=self.prepare(repo,engine,source)
            with self.assertRaises(GraphError) as error:service.neighborhood(GraphRequest(entityId=root,expectedGraphRevision='old'))
            self.assertEqual(error.exception.status_code,409)
            with self.assertRaises(GraphError) as error:service.neighborhood(GraphRequest(entityId=root,mode='historical',batchId='foreign',includeSimulated=True))
            self.assertEqual(error.exception.status_code,404)

    def test_node_edge_scan_and_byte_limits_are_honest_and_closed(self):
        with graph_fixture() as (repo,engine,source):
            _,service,batch,root=self.prepare(repo,engine,source)
            for limits in [replace(GraphLimits(),maxScannedRelations=1),replace(GraphLimits(),maxResultBytes=2000)]:
                service.limits=limits
                result=service.neighborhood(GraphRequest(entityId=root,includeSimulated=True,maxHops=2))
                self.assertEqual(result['status'],'limited')
                self.assertTrue(result['limitReason']);self.assertLessEqual(len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()),limits.maxResultBytes)
                ids={n['id'] for n in result['nodes']}
                self.assertTrue(all(r['from'] in ids and r['to'] in ids for r in result['relations']))
            service.limits=GraphLimits()
            result=service.neighborhood(GraphRequest(entityId=root,includeSimulated=True,maxNodes=1))
            self.assertEqual(len(result['nodes']),1);self.assertFalse(result['relations']);self.assertEqual(result['status'],'limited')

    def test_incoming_traversal_keeps_business_direction_and_exact_evidence(self):
        with graph_fixture() as (repo,engine,source):
            _,service,batch,root=self.prepare(repo,engine,source)
            out=service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
            edge=next(e for e in out['relations'] if e['type']=='opened_from')
            incoming=service.neighborhood(GraphRequest(entityId=edge['to'],direction='in',includeSimulated=True))
            self.assertIn(edge,incoming['relations'])
            ev=service.evidence(edge['id'],batch['batchId'],include_simulated=True)
            self.assertTrue(ev['evidence']);self.assertEqual(ev['mode'],'historical')
            with self.assertRaises(GraphError):service.evidence(edge['id'],batch['batchId'])

    def test_all_read_paths_do_not_write_or_recompute(self):
        with graph_fixture() as (repo,engine,source):
            _,service,batch,root=self.prepare(repo,engine,source)
            statements=[]
            def track(conn,cursor,statement,*args):statements.append(statement.strip().split()[0].upper())
            event.listen(engine,'before_cursor_execute',track)
            try:
                with patch('app.engine.engine.run_engine',side_effect=AssertionError('no current engine')):
                    service.status();value=service.neighborhood(GraphRequest(entityId=root,includeSimulated=True));service.reconcile()
                    service.evidence(value['relations'][0]['id'],batch['batchId'],include_simulated=True)
            finally:event.remove(engine,'before_cursor_execute',track)
            self.assertFalse(set(statements)&{'INSERT','UPDATE','DELETE'})
    def test_adjacency_sql_does_not_load_unrelated_relation_payloads(self):
        with graph_fixture() as (repo,engine,source):
            _,service,batch,root=self.prepare(repo,engine,source);queries=[]
            def track(conn,cursor,statement,*args):
                if 'FROM graph_relation ' in statement:queries.append(statement)
            event.listen(engine,'before_cursor_execute',track)
            try:result=service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
            finally:event.remove(engine,'before_cursor_execute',track)
            self.assertTrue(result['relations']);self.assertTrue(queries)
            self.assertTrue(any('graph_relation.from_id' in q.split('WHERE')[-1] for q in queries))
            for query in queries:self.assertRegex(query.split('WHERE')[-1],r'graph_relation\.(from_id|to_id|relation_id)\s*=')
    def test_expired_budget_with_no_matching_edges_never_reports_unlimited_success(self):
        from app.graph.query import traversal
        from app.graph.contracts import Budget
        with graph_fixture() as (repo,engine,source):
            _,service,batch,root=self.prepare(repo,engine,source)
            with service.read_view(Budget()) as (stored,view):
                value=traversal(stored,view,GraphRequest(entityId=root,includeSimulated=True,relationTypes=['monitors']),
                                GraphLimits(),Budget(0))
            self.assertEqual(value['status'],'limited');self.assertEqual(value['limitReason'],'deadline')

    def test_manifest_verification_cost_is_inside_status_deadline(self):
        from app.graph.contracts import Budget
        from app.graph import store
        with graph_fixture() as (repo,engine,source):
            _,service,batch,root=self.prepare(repo,engine,source)
            tick=[0];budget=Budget(100,clock=lambda:tick[0]);digest=store.manifest_revision
            def slow_manifest(value):
                result=digest(value);tick[0]=1;return result
            with patch('app.graph.service.Budget',return_value=budget),patch.object(store,'manifest_revision',slow_manifest):
                with self.assertRaises(GraphError) as error:service.status()
            self.assertEqual(error.exception.code,'graph_deadline')


if __name__=='__main__':unittest.main()
