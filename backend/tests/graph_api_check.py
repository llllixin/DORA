import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.graph_test_support import graph_fixture,open_case
from app.graph.service import GraphService


class GraphHttp(unittest.TestCase):
    def test_registered_finite_routes_and_legacy_history_compatibility(self):
        from app.main import app
        with graph_fixture() as (repo,engine,source):
            client=TestClient(app)
            response=client.get('/api/graph/status')
            self.assertEqual(response.status_code,200,'A09 HTTP routes missing')
            from app.graph.router import get_graph_service
            service=GraphService(engine,source);app.dependency_overrides[get_graph_service]=lambda:service
            try:
                self.assertFalse(client.get('/api/graph/status').json()['ready'])
                self.assertEqual(client.post('/api/graph/neighborhood',json={'entityId':'unknown'}).status_code,503)
                opened=open_case(repo);service.sync()
                from sqlalchemy import select
                from app.graph.models import GraphEntity
                with repo._session_ctx() as s:root=next(n.data['id'] for n in s.scalars(select(GraphEntity)) if n.data['type']=='ActionCase')
                body={'entityId':root,'includeSimulated':True}
                result=client.post('/api/graph/neighborhood',json=body);self.assertEqual(result.status_code,200)
                value=result.json();edge=value['relations'][0]
                self.assertEqual(client.get('/api/graph/relations/'+edge['id']+'/evidence',params={'batchId':value['batchId'],'includeSimulated':'true'}).status_code,200)
                self.assertEqual(client.post('/api/graph/neighborhood',json={**body,'expectedGraphRevision':'stale'}).status_code,409)
                self.assertEqual(client.post('/api/graph/neighborhood',json={**body,'scopeId':'foreign'}).status_code,422)
                self.assertEqual(client.post('/api/graph/neighborhood',json={'entityId':'foreign'}).status_code,404)
                self.assertEqual(client.post('/api/graph/neighborhood',json={**body,'mode':'historical'}).status_code,422)
                with patch.dict('os.environ',{'DORA_GRAPH_ENABLED':'false'}):
                    self.assertEqual(client.get('/api/graph/status').status_code,503)
                    self.assertEqual(client.get('/api/history/snapshots/'+opened['openingBinding']['snapshotId']).status_code,200)
            finally:app.dependency_overrides.pop(get_graph_service,None)


if __name__=='__main__':unittest.main()
