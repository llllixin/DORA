"""A08 runner guards must fail before resources or database writes."""
import contextlib
import io
import os
import socket
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests import knowledge_ui_gate as gate

VALID={
    'DATABASE_URL':'postgresql+psycopg://dora_a08:dora_a08@127.0.0.1:55458/dora_a08',
    'DORA_API_BASE':'http://127.0.0.1:8088/api','DORA_UI_BASE':'http://127.0.0.1:5188',
    'DORA_MODEL_EXTERNAL_ENABLED':'false','DORA_REASONING_PROVIDER':'template',
    'DORA_RAG_ANSWER_PROVIDER':'template','DORA_RAG_EMBEDDING_PROVIDER':'hash',
    'VITE_API_BASE_URL':'/api','VITE_API_MODE':'http','VITE_PROXY_TARGET':'http://127.0.0.1:8088',
}

def container():
    return {'Id':'a'*64,'Config':{'Image':'postgres:16','Labels':{'dev.dora.knowledge-ui-gate.owner':'test-owner'}},
        'HostConfig':{'AutoRemove':True,'Binds':None,'Tmpfs':{'/var/lib/postgresql/data':'rw'},
            'NetworkMode':'bridge','PortBindings':{'5432/tcp':[{'HostIp':'127.0.0.1','HostPort':'55458'}]}},
        'Mounts':[{'Type':'tmpfs','Destination':'/var/lib/postgresql/data'}]}

class KnowledgeUIGateGuards(unittest.TestCase):
    def test_libpq_target_and_service_overrides_are_rejected(self):
        for key in ('PGHOSTADDR','PGHOST','PGPORT','PGDATABASE','PGUSER','PGSERVICE','PGSERVICEFILE','PGPASSFILE','PGOPTIONS'):
            with self.subTest(key=key),self.assertRaises(ValueError):
                gate.safe_environment({**VALID,key:'redirect'})

    def test_browser_api_base_is_pinned_even_against_vite_file_defaults(self):
        for base in ('http://127.0.0.1:8000/api','https://remote.test/api'):
            with self.subTest(base=base),self.assertRaises(ValueError):gate.safe_environment({**VALID,'VITE_API_BASE_URL':base})
        self.assertEqual(gate.safe_environment(VALID)['VITE_API_BASE_URL'],'/api')

    def test_pinned_local_image_identity_is_checked(self):
        info=container();pinned='sha256:'+'b'*64;info['Config']['Image']=pinned
        self.assertEqual(gate.validate_container(info,'test-owner',image=pinned),'a'*64)
        with self.assertRaises(ValueError):gate.validate_container(info,'test-owner',image='sha256:'+'c'*64)

    def test_exact_environment_is_accepted_without_io(self):
        self.assertEqual(gate.validate_environment(VALID),(VALID['DATABASE_URL'],8088,5188))

    def test_database_identity_cannot_be_redirected(self):
        for value in ('',VALID['DATABASE_URL'].replace('55458','5432'),VALID['DATABASE_URL'].replace('55458','55459'),
                      VALID['DATABASE_URL'].replace('dora_a08:','dora:'),VALID['DATABASE_URL'].replace('/dora_a08','/dora'),
                      VALID['DATABASE_URL'].replace('127.0.0.1','localhost'),VALID['DATABASE_URL']+'?hostaddr=8.8.8.8'):
            with self.subTest(value=value),self.assertRaises(ValueError):gate.validate_environment({**VALID,'DATABASE_URL':value})

    def test_api_and_ui_are_exact_and_same_proxy(self):
        for key,value in [('DORA_API_BASE','http://127.0.0.1:8000/api'),('DORA_API_BASE','http://remote.test:8088/api'),
                          ('DORA_UI_BASE','http://127.0.0.1:5188?next=evil'),('VITE_PROXY_TARGET','http://127.0.0.1:8000'),
                          ('VITE_API_MODE','mock')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):gate.validate_environment({**VALID,key:value})

    def test_external_modes_are_rejected(self):
        for key,value in [('DORA_MODEL_EXTERNAL_ENABLED','true'),('DORA_REASONING_PROVIDER','llm'),
                          ('DORA_RAG_ANSWER_PROVIDER','openai'),('DORA_RAG_EMBEDDING_PROVIDER','openai')]:
            with self.subTest(key=key),self.assertRaises(ValueError):gate.validate_environment({**VALID,key:value})

    def test_inherited_keys_are_cleared_and_environment_not_mutated(self):
        source={**VALID,'OPENAI_API_KEY':'private','DORA_LLM_API_KEY':'private','DORA_RAG_OPENAI_API_KEY':'private'}
        result=gate.safe_environment(source)
        for key in ('OPENAI_API_KEY','DORA_LLM_API_KEY','DORA_RAG_OPENAI_API_KEY'):self.assertEqual(result[key],'')
        self.assertEqual(source['OPENAI_API_KEY'],'private')

    def test_occupied_port_is_rejected_instead_of_reused(self):
        with socket.socket() as held:
            held.bind(('127.0.0.1',0));held.listen(1)
            with self.assertRaisesRegex(RuntimeError,'occupied'):gate.assert_ports_free((held.getsockname()[1],))

    def test_only_owned_tmpfs_container_is_accepted(self):
        self.assertEqual(gate.validate_container(container(),'test-owner'),'a'*64)

    def test_unknown_owner_prevents_acceptance(self):
        with self.assertRaises(ValueError):gate.validate_container(container(),'another-owner')

    def test_user_mount_and_persistent_database_are_rejected(self):
        cases=[]
        value=container();value['HostConfig']['Binds']=['/Users/me/db:/var/lib/postgresql/data'];cases.append(value)
        value=container();value['Mounts']=[{'Type':'volume','Destination':'/var/lib/postgresql/data'}];cases.append(value)
        value=container();value['HostConfig']['Tmpfs']={};cases.append(value)
        value=container();value['HostConfig']['AutoRemove']=False;cases.append(value)
        for value in cases:
            with self.subTest(value=value),self.assertRaises(ValueError):gate.validate_container(value,'test-owner')

    def test_wrong_container_bind_or_host_network_is_rejected(self):
        for key,value in [('PortBindings',{'5432/tcp':[{'HostIp':'0.0.0.0','HostPort':'55458'}]}),('NetworkMode','host')]:
            item=container();item['HostConfig'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):gate.validate_container(item,'test-owner')

    def test_default_help_creates_no_process(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch.object(gate.subprocess,'run',side_effect=AssertionError('no subprocess')),\
             patch.object(gate.subprocess,'Popen',side_effect=AssertionError('no service')):
            self.assertEqual(gate.main([]),0)
        self.assertIn('--local-only',output.getvalue());self.assertIn('--full',output.getvalue())

    def test_unsafe_full_stops_before_any_subprocess(self):
        with patch.dict(os.environ,{**VALID,'DATABASE_URL':'postgresql+psycopg://dora:dora@127.0.0.1:5432/dora'},clear=True),\
             patch.object(gate.subprocess,'run',side_effect=AssertionError('must validate before resources')),\
             patch.object(gate.subprocess,'Popen',side_effect=AssertionError('must validate before services')):
            with self.assertRaises(ValueError):gate.main(['--full'])

    def test_current_legacy_http_modules_honor_isolated_base(self):
        report=gate.audit_http_targets()
        self.assertEqual(set(report),{'agent_check','e2e_api_check','action_check','watch_check','rag_check'})
        self.assertTrue(all(item['guardedURLs']>=1 for item in report.values()))

    def test_missing_browser_material_stops_before_resource_commands(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(gate,'ROOT',Path(temp)),\
             patch.object(gate.shutil,'which',return_value='/usr/bin/docker'),\
             patch.object(gate.subprocess,'Popen',side_effect=AssertionError('no resources before scripts')):
            evidence=type('Evidence',(),{'env':VALID})()
            with self.assertRaisesRegex(RuntimeError,'CDP scripts'):gate.full_checks(evidence,'test-owner')

if __name__=='__main__':unittest.main()
