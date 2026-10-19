"""Wiki routes and lifecycle through real index/SQL boundaries."""
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from fastapi.testclient import TestClient
from app import db
from app.models import Base
from app.main import app
from app.rag.indexer import RagIndexer
from app.rag.repository import RagRepository
from app.rag.embeddings import HashEmbeddingProvider
from tests.wiki_check import draft,reviewed

class WikiIntegrationChecks(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=__import__('sqlalchemy').pool.StaticPool)
        Base.metadata.create_all(self.engine);self.binding=patch.object(db,'_engine',self.engine);self.binding.start()
    def tearDown(self):self.binding.stop();self.engine.dispose()
    def test_retirement_blocks_older_reviewed_in_real_index(self):
        from tests.knowledge_index_support import temporary_index
        old=draft();old['id']='test-lifecycle';old=reviewed(old);old['version']=1
        with temporary_index([old]) as (repo,index,write):
            index.rebuild();self.assertTrue(repo.get_document('test-lifecycle',1)['active'])
            pending=draft();pending['id']='test-lifecycle';pending['version']=2
            write([old,pending]);index.rebuild();self.assertTrue(repo.get_document('test-lifecycle',1)['active'])
            from app.wiki.contracts import retire
            withdrawn=retire(old,actor='test:operator',reason='withdraw',base_version=2);withdrawn['version']=3
            write([old,pending,withdrawn]);index.rebuild();self.assertEqual(repo.active_chunks(),[])
            self.assertFalse(repo.get_document('test-lifecycle',1)['active'])
    def test_routes_read_source_and_historical_versions_no_write_api(self):
        client=TestClient(app)
        out=client.get('/api/wiki/cards');self.assertEqual(out.status_code,200)
        self.assertEqual(len(out.json()['cards']),44)
        self.assertNotEqual(out.json()['indexStatus'],'not_checked')
        old=client.get('/api/wiki/cards/metric-margin?version=1');self.assertEqual(old.status_code,200)
        self.assertEqual(old.json()['card']['version'],1);self.assertTrue(old.json()['card']['legacy'])
        self.assertEqual(client.get('/api/wiki/cards/missing-topic').status_code,404)
        self.assertEqual(client.post('/api/wiki/cards',json={}).status_code,405)
        self.assertEqual(client.get('/api/wiki/candidates').json()['candidates'],[])
        self.assertEqual(client.get('/api/wiki/candidates/missing').status_code,404)
        self.assertEqual(client.post('/api/wiki/candidates',json={}).status_code,405)

if __name__=='__main__':unittest.main()
