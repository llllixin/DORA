"""F06 integrity regressions over disposable SQLite graph batches only."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select, update

from app.business_version import SCOPE_ID
from app.graph.contracts import Budget, GraphError, GraphLimits, GraphRequest, manifest_revision
from app.graph.models import (GraphBuildBatch, GraphBuildMember, GraphEntity,
                              GraphRelation, GraphRelationEvidence, GraphState)
from app.graph.router import get_graph_service, router
from app.graph.service import GraphService
from tests.graph_test_support import graph_fixture, open_case


class GraphIntegrityRepairs(unittest.TestCase):
    def prepare(self, repo, engine, source):
        open_case(repo)
        service = GraphService(engine, source)
        built = service.sync()
        with repo._session_ctx() as session:
            root = next(row.data['id'] for row in session.scalars(select(GraphEntity))
                        if row.data['type'] == 'ActionCase')
        request = GraphRequest(entityId=root, includeSimulated=True)
        before = service.neighborhood(request)
        edge = next(row for row in before['relations'] if row['type'] == 'opened_from')
        proof = next(row for row in before['evidence'] if row['relationId'] == edge['id'])
        return service, built, request, edge, proof

    def assert_rejected_read_only(self, repo, engine, service, built, request, edge):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_graph_service] = lambda: service
        statements = []

        def track(connection, cursor, statement, *args):
            statements.append(statement.strip().split()[0].upper())

        event.listen(engine, 'before_cursor_execute', track)
        try:
            with TestClient(app) as client:
                responses = [client.get('/api/graph/status'),
                             client.post('/api/graph/neighborhood', json=request.model_dump()),
                             client.get('/api/graph/relations/' + edge['id'] + '/evidence',
                                        params={'batchId': built['batchId'], 'includeSimulated': 'true'})]
            for response in responses:
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()['detail']['reasonCode'], 'graph_integrity_unavailable')
            with repo._session_ctx() as session:
                self.assertEqual(session.get(GraphState, SCOPE_ID).head_batch_id, built['batchId'])
                self.assertEqual(session.get(GraphBuildBatch, (SCOPE_ID, built['batchId'])).graph_revision,
                                 built['graphRevision'])
        finally:
            event.remove(engine, 'before_cursor_execute', track)
        self.assertFalse(set(statements) & {'INSERT', 'UPDATE', 'DELETE'})

    def test_missing_relation_member_fails_every_read_without_moving_head(self):
        self.missing_member('relation')

    def test_missing_proof_member_fails_every_read_without_moving_head(self):
        self.missing_member('evidence')

    def test_missing_entity_member_fails_every_read_without_moving_head(self):
        self.missing_member('entity')

    def missing_member(self, kind):
        with graph_fixture() as (repo, engine, source):
            service, built, request, edge, proof = self.prepare(repo, engine, source)
            item_id = {'entity': edge['to'], 'relation': edge['id'], 'evidence': proof['id']}[kind]
            with repo._session_ctx() as session:
                removed = session.execute(delete(GraphBuildMember).where(
                    GraphBuildMember.batch_id == built['batchId'], GraphBuildMember.item_kind == kind,
                    GraphBuildMember.item_id == item_id)).rowcount
                session.commit()
            self.assertEqual(removed, 1)
            self.assert_rejected_read_only(repo, engine, service, built, request, edge)

    def test_missing_relation_content_fails_every_read_without_moving_head(self):
        self.missing_content('relation')

    def test_missing_proof_content_fails_every_read_without_moving_head(self):
        self.missing_content('evidence')

    def test_missing_entity_content_fails_every_read_without_moving_head(self):
        self.missing_content('entity')

    def missing_content(self, kind):
        with graph_fixture() as (repo, engine, source):
            service, built, request, edge, proof = self.prepare(repo, engine, source)
            model, column, item_id = {'entity': (GraphEntity, GraphEntity.entity_id, edge['to']),
                                     'relation': (GraphRelation, GraphRelation.relation_id, edge['id']),
                                     'evidence': (GraphRelationEvidence, GraphRelationEvidence.evidence_id, proof['id'])}[kind]
            # Model storage damage without cascade repair; this connection is fixture-owned.
            with engine.connect() as connection:
                connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
                connection.commit()
                removed = connection.execute(delete(model).where(column == item_id)).rowcount
                connection.commit()
                connection.exec_driver_sql('PRAGMA foreign_keys=ON')
                connection.commit()
            self.assertEqual(removed, 1)
            self.assert_rejected_read_only(repo, engine, service, built, request, edge)

    def test_unexpected_member_with_existing_content_fails_every_read(self):
        with graph_fixture() as (repo, engine, source):
            service, built, request, edge, _ = self.prepare(repo, engine, source)
            with repo._session_ctx() as session:
                session.add(GraphEntity(scope_id=SCOPE_ID, entity_id='extra-content', data={}))
                session.add(GraphBuildMember(scope_id=SCOPE_ID, batch_id=built['batchId'],
                                             item_kind='entity', item_id='extra-content'))
                session.commit()
            self.assert_rejected_read_only(repo, engine, service, built, request, edge)

    def test_unknown_member_kind_fails_every_read(self):
        with graph_fixture() as (repo, engine, source):
            service, built, request, edge, _ = self.prepare(repo, engine, source)
            with engine.connect() as connection:
                connection.exec_driver_sql('PRAGMA ignore_check_constraints=ON')
                connection.execute(GraphBuildMember.__table__.insert().values(
                    scope_id=SCOPE_ID, batch_id=built['batchId'], item_kind='unknown', item_id=edge['id']))
                connection.commit()
                connection.exec_driver_sql('PRAGMA ignore_check_constraints=OFF')
                connection.commit()
            self.assert_rejected_read_only(repo, engine, service, built, request, edge)
            self.assertFalse(service.reconcile()['ok'])

    def test_unknown_manifest_member_kind_is_rejected_even_with_matching_digest(self):
        with graph_fixture() as (repo, engine, source):
            service, built, request, edge, _ = self.prepare(repo, engine, source)
            with repo._session_ctx() as session:
                row = session.get(GraphBuildBatch, (SCOPE_ID, built['batchId']))
                row.manifest = {**row.manifest, 'members': {**row.manifest['members'], 'unknown': []}}
                row.graph_revision = manifest_revision(row.manifest)
                built['graphRevision'] = row.graph_revision
                session.commit()
            self.assert_rejected_read_only(repo, engine, service, built, request, edge)

    def test_metadata_validation_stays_bounded_and_payloads_stay_lazy(self):
        with graph_fixture() as (repo, engine, source):
            service, built, request, edge, _ = self.prepare(repo, engine, source)
            with repo._session_ctx() as session:
                manifest = session.get(GraphBuildBatch, (SCOPE_ID, built['batchId'])).manifest
                expected_members = sum(len(ids) for ids in manifest['members'].values())
            queries = []

            def track(connection, cursor, statement, params, context, many):
                queries.append((statement, getattr(context, 'compiled_parameters', [])))

            event.listen(engine, 'before_cursor_execute', track)
            try:
                status = service.status()
                service.limits = replace(GraphLimits(), maxScannedRelations=1)
                limited = service.neighborhood(request)
                evidence = service.evidence(edge['id'], built['batchId'], include_simulated=True)
            finally:
                event.remove(engine, 'before_cursor_execute', track)
            self.assertTrue(status['ready'])
            self.assertEqual(status['sourceState'], 'in_sync')
            self.assertEqual(limited['status'], 'limited')
            self.assertEqual(limited['limitReason'], 'scanned_relations')
            self.assertEqual(evidence['status'], 'ok')
            self.assertEqual(evidence['relations'], [edge])
            metadata = [(sql, params) for sql, params in queries if 'FROM graph_build_member' in sql]
            self.assertEqual(len(metadata), 3)
            for sql, params in metadata:
                self.assertNotIn('.data', sql.split('FROM')[0])
                self.assertIn('LIMIT', sql)
                self.assertIn(expected_members + 1, params[0].values())
            adjacency = [(sql, params) for sql, params in queries
                         if 'FROM graph_relation ' in sql and 'graph_relation.from_id' in sql.split('WHERE')[-1]]
            self.assertTrue(adjacency)
            self.assertTrue(all('LIMIT' in sql and 2 in params[0].values() for sql, params in adjacency))

    def test_membership_validation_is_inside_the_query_deadline(self):
        with graph_fixture() as (repo, engine, source):
            service, _, _, _, _ = self.prepare(repo, engine, source)
            tick = [0]
            budget = Budget(100, clock=lambda: tick[0])

            def expire(connection, cursor, statement, *args):
                if 'FROM graph_build_member' in statement:
                    tick[0] = 1

            event.listen(engine, 'before_cursor_execute', expire)
            try:
                with patch('app.graph.service.Budget', return_value=budget), self.assertRaises(GraphError) as error:
                    service.status()
            finally:
                event.remove(engine, 'before_cursor_execute', expire)
            self.assertEqual(error.exception.code, 'graph_deadline')

    def test_relation_with_no_raw_proofs_fails_instead_of_disappearing(self):
        with graph_fixture() as (repo, engine, source):
            service, built, request, edge, _ = self.prepare(repo, engine, source)
            other = next(row for row in service.neighborhood(request)['relations'] if row['id'] != edge['id'])
            with repo._session_ctx() as session:
                session.execute(update(GraphRelationEvidence).where(GraphRelationEvidence.relation_id == edge['id'])
                                .values(relation_id=other['id']))
                session.commit()
            request = request.model_copy(update={'relationTypes': ['opened_from']})
            for read in (lambda: service.neighborhood(request),
                         lambda: service.evidence(edge['id'], built['batchId'], include_simulated=True)):
                with self.assertRaises(GraphError) as error:
                    read()
                self.assertEqual((error.exception.code, error.exception.status_code),
                                 ('graph_integrity_unavailable', 503))


if __name__ == '__main__':
    unittest.main()
