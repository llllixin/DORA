"""A06 pure identity/lifecycle/source-deadline checks; no user DB."""
import importlib.util
import json
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date
from copy import deepcopy
import unittest
from dataclasses import replace
from types import SimpleNamespace


def hold_file(path, ready, stop):
    import fcntl
    with open(path, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX); ready.set(); stop.wait(5)


class IdentityTests(unittest.TestCase):
    def test_repository_annotations_resolve_on_eager_annotation_python(self):
        from typing import get_type_hints
        from app.rag.repository import RagRepository
        self.assertIn('return',get_type_hints(RagRepository._chunk_dict))

    def test_source_identity_formal_fields_and_order(self):
        self.assertIsNotNone(importlib.util.find_spec('app.rag.identity'), 'source/index identities not implemented')
        from app.rag.identity import source_version_hash
        from app.rag.contracts import load_documents
        d=load_documents()[0]; h=source_version_hash(d)
        self.assertEqual(h, source_version_hash(dict(reversed(list(d.items())))))
        for key,value in [('content',d['content']+' '),('status','retired'),('title','new title'),('valid_to','2027-01-01'),('source_ref','changed'),('reviewed_by',['changed'])]:
            changed=deepcopy(d);changed[key]=value;self.assertNotEqual(h,source_version_hash(changed))
        self.assertEqual(h,source_version_hash({**d,'active':False,'is_current':False}))

    def test_embedding_space_not_credential_identity(self):
        self.assertIsNotNone(importlib.util.find_spec('app.rag.identity'))
        from app.rag.identity import embedding_profile
        p=SimpleNamespace(kind='openai',model='test',dimensions=32,base_url='https://example.org/v1/',api_key='one',timeout=3)
        a=embedding_profile(p);p.api_key='two';p.timeout=9;self.assertEqual(a,embedding_profile(p))
        for field,value in [('base_url','https://other.org/v1'),('dimensions',64),('model','other'),('kind','local-semantic'),('adapter_version','next')]:
            q=deepcopy(p);setattr(q,field,value);self.assertNotEqual(a,embedding_profile(q))
        self.assertNotEqual(a,embedding_profile(p,space_revision='v2'))

    def test_lifecycle_draft_future_expired_and_barrier(self):
        self.assertIsNotNone(importlib.util.find_spec('app.rag.lifecycle'))
        from app.rag.lifecycle import select_versions, merge_removal_barriers
        old={'id':'topic','version':1,'status':'reviewed','valid_from':'2026-01-01','valid_to':None}
        newest={**old,'version':2,'valid_to':'2026-10-15'}
        today=date(2026,10,15)
        def selected(docs, barriers=None):return select_versions(docs,on_date=today,barriers=barriers or {})['eligible']
        self.assertEqual(selected([old,newest])[0]['version'],2)
        self.assertEqual(selected([old,{**newest,'status':'draft'}])[0]['version'],1)
        self.assertEqual(selected([old,{**newest,'valid_from':'2026-10-16'}])[0]['version'],1)
        self.assertEqual(selected([old,{**newest,'valid_to':'2026-10-14'}]),[])
        self.assertEqual(selected([old,newest],{'topic':2}),[])
        manifest={'versions':{'topic@1':old,'topic@2':newest},'barriers':{}}
        self.assertEqual(merge_removal_barriers(manifest,[],mode='full'),{'topic':2})
        self.assertEqual(merge_removal_barriers(manifest,[],mode='patch'),{})

    def test_source_file_lock_obeys_budget(self):
        self.assertIsNotNone(importlib.util.find_spec('app.rag.source'), 'bounded file-lock source not implemented')
        from app.rag.source import KnowledgeSource
        from app.runtime.budget import load_profile
        from app.runtime.executor import RunContext
        from app.runtime.contracts import RuntimeFailure
        import time
        with TemporaryDirectory() as folder:
            path=Path(folder)/'docs.json';path.write_text('[]')
            ctx=multiprocessing.get_context('spawn');ready=ctx.Event();stop=ctx.Event()
            proc=ctx.Process(target=hold_file,args=(str(path)+'.lock',ready,stop));proc.start()
            try:
                self.assertTrue(ready.wait(2));run=RunContext('rag-index',profile=replace(load_profile('rag-index',False),maxElapsedMs=80,attemptTimeoutMs=80))
                start=time.monotonic()
                with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
                    KnowledgeSource(path).snapshot(budget=run.budget)
                self.assertLess(time.monotonic()-start,1)
            finally:stop.set();proc.join(2)


if __name__=='__main__':unittest.main(verbosity=2)
