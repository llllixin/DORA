"""A06 cross-process PostgreSQL/lock/rollback checks. Disposable DB only."""
from copy import deepcopy
from dataclasses import replace
import json
import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from urllib.parse import urlsplit
from sqlalchemy import delete, event, create_engine, text
from app import db
from app.models import RagDocument,RagChunk,RagIndexProjection,RagIndexBatch,RagIndexState
from app.rag.repository import RagRepository
from app.rag.indexer import RagIndexer
from app.rag.source import KnowledgeSource
from app.rag.embeddings import HashEmbeddingProvider
from app.runtime.budget import load_profile
from app.runtime.executor import RunContext
from app.runtime.contracts import RuntimeFailure
from tests.model_runtime_support import MemoryRuns
from tests.model_runtime_check import Clock
from tests.knowledge_index_check import hold_file
from tests.knowledge_index_integration_check import CountingHash
from tests.wiki_check import draft,reviewed


def delayed_file_lock(path, boot, trigger, ready, stop):
    boot.set()
    if trigger.wait(5):hold_file(path,ready,stop)


def require_disposable():
    u=urlsplit(os.environ.get('DATABASE_URL',''))
    if not (u.scheme=='postgresql+psycopg' and u.hostname=='127.0.0.1' and u.username=='dora_a06' and u.path=='/dora_a06' and u.port):
        raise RuntimeError('explicit disposable loopback dora_a06 database required')


def worker(source, counter, start, output):
    require_disposable();db._engine=create_engine(os.environ['DATABASE_URL'])
    class Count(HashEmbeddingProvider):
        def _one(self,value):
            with open(counter,'a') as f:f.write('input\n')
            time.sleep(.08);return super()._one(value)
    try:
        start.wait(3)
        report=RagIndexer(RagRepository(source=KnowledgeSource(source)),Count(),MemoryRuns()).rebuild()
        output.put({'ok':True,'embeddedInputs':report['embeddedInputs']})
    except Exception as exc:output.put({'ok':False,'error':repr(exc)})
    finally:db._engine.dispose()


def hold_advisory(ready):
    from app.rag.index_lock import KEY
    engine=create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as conn:
        conn.execute(text('SELECT pg_advisory_lock(:key)'),{'key':KEY});conn.commit();ready.set()
        time.sleep(15)


class PostgresIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):require_disposable();db.init_db()

    @classmethod
    def tearDownClass(cls):
        with db.make_session() as s:
            for model in (RagIndexState,RagIndexBatch,RagIndexProjection,RagChunk,RagDocument):s.execute(delete(model))
            s.commit()
        db.get_engine().dispose()

    def setUp(self):
        with db.make_session() as s:
            for model in (RagIndexState,RagIndexBatch,RagIndexProjection,RagChunk,RagDocument):s.execute(delete(model))
            s.commit()
        self.temp=TemporaryDirectory();self.path=Path(self.temp.name)/'documents.json'
        raw=draft();raw['id']='a06-pg-topic';raw['version']=1;raw['valid_from']='2026-01-01'
        self.old=reviewed(raw);self.write([self.old]);self.provider=CountingHash();self.runs=MemoryRuns()
        self.repo=RagRepository(source=KnowledgeSource(self.path));self.index=RagIndexer(self.repo,self.provider,self.runs)
        self.ctx=multiprocessing.get_context('spawn')

    def tearDown(self):self.temp.cleanup()
    def write(self,docs):self.path.write_text(json.dumps(docs,ensure_ascii=False))
    def newer(self):
        raw=deepcopy(self.old);raw['version']=2;raw['title']+=' newer'
        return reviewed(raw,base=1)
    def run_budget(self,ms=120,clock=None):
        return RunContext('rag-index',repository=self.runs,clock=clock,
            profile=replace(load_profile('rag-index',False),maxElapsedMs=ms,attemptTimeoutMs=ms))

    def test_two_processes_recheck_after_build_lock(self):
        start=self.ctx.Event();out=self.ctx.Queue();counter=str(self.path)+'.counter'
        processes=[self.ctx.Process(target=worker,args=(str(self.path),counter,start,out)) for _ in range(2)]
        try:
            for p in processes:p.start()
            start.set();results=[out.get(timeout=12) for _ in processes]
            self.assertTrue(all(r['ok'] for r in results),results)
            self.assertEqual(sorted(r['embeddedInputs'] for r in results),[0,1])
            self.assertEqual(Path(counter).read_text().splitlines(),['input'])
        finally:
            for p in processes:
                p.join(3)
                if p.is_alive():p.terminate();p.join()

    def test_build_lock_deadline_and_crashed_process_release(self):
        self.index.rebuild();head=self.repo.index_store.read_snapshot()['head'];self.provider.inputs=0
        ready=self.ctx.Event();proc=self.ctx.Process(target=hold_advisory,args=(ready,));proc.start()
        try:
            self.assertTrue(ready.wait(3));start=time.monotonic()
            with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):self.index.rebuild(run_context=self.run_budget())
            self.assertLess(time.monotonic()-start,1);self.assertEqual(self.provider.inputs,0)
            self.assertEqual(self.repo.index_store.read_snapshot()['head'],head)
        finally:proc.terminate();proc.join(3)
        result=self.index.rebuild(run_context=self.run_budget(2000))
        self.assertEqual(result['embeddedInputs'],0)

    def test_file_lock_initial_and_commit_recheck_share_deadline(self):
        for phase in ('initial','commit'):
            with self.subTest(phase=phase):
                self.write([self.old]);self.provider.after=None;self.index.rebuild()
                head=self.repo.index_store.read_snapshot()['head'];self.provider.inputs=0
                ready=self.ctx.Event();stop=self.ctx.Event();boot=self.ctx.Event();trigger=self.ctx.Event()
                proc=self.ctx.Process(target=delayed_file_lock,args=(str(self.path)+'.lock',boot,trigger,ready,stop))
                proc.start();self.assertTrue(boot.wait(3))
                def hold():
                    trigger.set();self.assertTrue(ready.wait(2))
                if phase=='initial':hold()
                else:
                    self.write([self.old,self.newer()]);self.provider.after=hold
                try:
                    start=time.monotonic()
                    with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
                        self.index.rebuild(run_context=self.run_budget())
                    self.assertLess(time.monotonic()-start,1)
                    if phase=='initial':self.assertEqual(self.provider.inputs,0)
                    self.assertEqual(self.repo.index_store.read_snapshot()['head'],head)
                    self.assertIsNone(self.repo.get_document(self.old['id'],2))
                finally:
                    stop.set()
                    if proc.pid:proc.join(2)
                    self.provider.after=None

    def test_real_document_and_head_flush_deadline_rollback(self):
        self.index.rebuild()
        for sql in ('INSERT INTO RAG_DOCUMENT','UPDATE RAG_INDEX_STATE'):
            with self.subTest(sql=sql):
                head=self.repo.index_store.read_snapshot()['head'];self.write([self.old,self.newer()])
                clock=Clock();observed=[]
                def slow(conn,cursor,statement,parameters,context,many):
                    if sql in statement.upper():observed.append(sql);clock.sleep(.02)
                event.listen(db.get_engine(),'before_cursor_execute',slow)
                try:
                    with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
                        self.index.rebuild(run_context=self.run_budget(10,clock))
                finally:event.remove(db.get_engine(),'before_cursor_execute',slow)
                self.assertTrue(observed,'actual PostgreSQL phase was not exercised')
                self.assertEqual(self.repo.index_store.read_snapshot()['head'],head)
                self.assertIsNone(self.repo.get_document(self.old['id'],2))

    def test_readers_see_whole_successful_batches(self):
        self.index.rebuild();old_head=self.repo.index_store.read_snapshot()['head']
        self.write([self.old,self.newer()]);errors=[];result=[]
        def writer():
            try:result.append(self.index.rebuild())
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=writer);thread.start();seen=[]
        while thread.is_alive():
            state=self.repo.index_store.read_snapshot()
            for key,pid in state['manifest']['projections'].items():
                self.assertEqual(state['projections'][pid]['document_pk'],key)
                self.assertIn(key,state['versions'])
            seen.append(state['head'])
        thread.join(3);self.assertFalse(errors,errors);self.assertTrue(result)
        seen.append(self.repo.index_store.read_snapshot()['head'])
        self.assertTrue(set(seen)<={old_head,result[0]['indexBatchId']})


if __name__=='__main__':unittest.main(verbosity=2)
