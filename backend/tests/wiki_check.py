"""A02 source/publication behavior; temporary files only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from app.rag.contracts import load_documents, validate_document, RagContractError

FIXTURES = Path(__file__).parent / 'fixtures'

def draft(index=0):
    return deepcopy(json.loads((FIXTURES / 'wiki-cards.json').read_text())[index])

def reviewed(doc=None, base=0):
    from app.wiki.contracts import approve
    return approve(doc or draft(), actor='test:operator', reason='test fixture review', base_version=base)

class WikiChecks(unittest.TestCase):
    def test_new_record_cannot_downgrade_to_legacy(self):
        raw=deepcopy(load_documents()[0]);raw['id']='unreviewed-new-topic'
        with self.assertRaises(RagContractError):validate_document(raw)

    def test_reviewed_requires_actual_content_review(self):
        raw=draft();raw['status']='reviewed';raw['reviewed_by']='test:spoof'
        with self.assertRaises(RagContractError):validate_document(raw)

    def test_all_four_templates_and_drafts(self):
        rows=json.loads((FIXTURES / 'wiki-cards.json').read_text())
        for row in rows:
            with self.subTest(id=row['id']):self.assertEqual(validate_document(row)['status'],'draft')
        self.assertEqual(len(rows),44)

    def test_invalid_structure_sources_concepts_and_evidence(self):
        for change in ['section','concept','missing','escape','verified','type','content','simulated','concept_note']:
            raw=draft()
            if change=='section':raw['wiki_card']['sections'].pop('definition')
            if change=='concept':raw['concept_ids']=['invented.node']
            if change=='missing':raw['governance']['source_refs']=['missing-file.md']
            if change=='escape':raw['governance']['source_refs']=['../outside.md']
            if change=='verified':raw['source_type']='verified_case'
            if change=='type':raw['wiki_card']['card_type']='sop'
            if change=='content':raw['content']+=' unaudited extra'
            if change=='simulated':raw['source_type']='simulated'
            if change=='concept_note':raw['concept_ids']=[];raw['wiki_card']['concept_note']=''
            with self.subTest(change=change),self.assertRaises(RagContractError):validate_document(raw)

    def test_review_hash_is_invalidated_by_content_or_source(self):
        raw=reviewed();self.assertEqual(validate_document(raw)['status'],'reviewed')
        for field in ['title','aliases','governance']:
            altered=deepcopy(raw)
            if field=='title':altered[field]='Changed title'
            if field=='aliases':altered[field].append('changed alias')
            if field=='governance':altered[field]['applicability']='changed scope'
            with self.subTest(field=field),self.assertRaises(RagContractError):validate_document(altered)

    def test_primary_citation_must_be_in_audited_sources(self):
        for primary in ['../missing-evidence.md','backend/app/models.py']:
            raw=draft();raw['source_ref']=primary
            with self.subTest(primary=primary),self.assertRaises(RagContractError):reviewed(raw)

    def test_publish_append_repeat_and_bad_batch_zero_write(self):
        from app.wiki.publication import publish_batch
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'documents.json';source.write_text('[]')
            raw=reviewed();out=publish_batch([raw],source)
            self.assertTrue(out['published']);self.assertFalse(out['indexed']);self.assertEqual(out['added'],1)
            before=source.read_bytes();self.assertEqual(publish_batch([raw],source)['added'],0)
            bad=reviewed(draft(1));bad['title']='mutated'
            with self.assertRaises(RagContractError):publish_batch([reviewed(draft(2)),bad],source)
            self.assertEqual(source.read_bytes(),before)
            old=json.loads(before)[0];new=deepcopy(old);new['title']='new margin definition'
            self.assertEqual(publish_batch([reviewed(new,1)],source)['added'],1)
            self.assertEqual(json.loads(source.read_text())[0],old)

    def test_publication_race_one_wins(self):
        from app.wiki.publication import publish_batch
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'documents.json';source.write_text('[]')
            a=reviewed();b=draft();b['title']='other title';b=reviewed(b)
            def commit(doc):
                try:return publish_batch([doc],source)['added']
                except RagContractError:return 'conflict'
            with ThreadPoolExecutor(2) as pool:out=list(pool.map(commit,[a,b]))
            self.assertCountEqual(out,[1,'conflict']);self.assertEqual(len(json.loads(source.read_text())),1)

    def test_retired_blocks_fallback_draft_does_not(self):
        from app.wiki.reader import effective_documents
        from app.wiki.contracts import retire
        old=reviewed();old['version']=1;new=draft();new['version']=2
        self.assertEqual([d['version'] for d in effective_documents([old,new])],[1])
        retired=retire(old,actor='test:operator',reason='withdraw topic',base_version=1);retired['version']=2
        self.assertEqual(effective_documents([old,new,retired]),[])

    def test_republish_after_retirement_requires_new_version(self):
        from app.wiki.publication import publish_batch
        from app.wiki.contracts import retire
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'documents.json';source.write_text('[]')
            first=reviewed();publish_batch([first],source)
            publish_batch([retire(first,actor='test:operator',reason='withdraw',base_version=1)],source)
            self.assertEqual(publish_batch([reviewed(first,2)],source)['added'],1)
            self.assertEqual(len(json.loads(source.read_text())),3)

    def test_candidate_exports_cannot_bypass_source_guard(self):
        from app.wiki.publication import publish_batch
        raw=draft();raw['governance']['origin']={'candidate_id':'missing','revision':1,'source_hash':'0'*64}
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'documents.json';source.write_text('[]')
            with self.assertRaises(RagContractError):publish_batch([reviewed(raw)],source)
            self.assertEqual(source.read_text(),'[]')

    def test_cli_review_publish_and_invalid_batch(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);raw=folder/'draft.json';approved=folder/'approved.json';source=folder/'documents.json'
            raw.write_text(json.dumps([draft()],ensure_ascii=False));source.write_text('[]')
            def cli(*args):return subprocess.run([sys.executable,'-m','app.wiki.cli',*args],capture_output=True,text=True)
            out=cli('approve','--input',str(raw),'--output',str(approved),'--actor','test:operator','--reason','review CLI','--base-version','0')
            self.assertEqual(out.returncode,0,out.stderr)
            out=cli('publish','--input',str(approved),'--source',str(source))
            self.assertEqual(out.returncode,0,out.stderr);self.assertTrue(json.loads(out.stdout)['published'])
            bad=json.loads(approved.read_text());bad[0]['title']='changed';approved.write_text(json.dumps(bad))
            before=source.read_bytes();self.assertEqual(cli('publish','--input',str(approved),'--source',str(source)).returncode,2)
            self.assertEqual(source.read_bytes(),before)

    def test_render_and_failure_reports_committed_source(self):
        from app.wiki.publication import publish_batch
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'documents.json';source.write_text('[]');wiki=Path(directory)/'wiki'
            out=publish_batch([reviewed()],source,render_dir=wiki)
            self.assertTrue(out['rendered']);self.assertTrue((wiki/'index.md').is_file())
            self.assertIn('test:operator',(wiki/'metric/metric-margin.md').read_text())
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'documents.json';source.write_text('[]')
            with patch('app.wiki.publication.render',side_effect=OSError('disk full')):
                out=publish_batch([reviewed()],source,render_dir=Path(directory)/'wiki')
            self.assertTrue(out['published']);self.assertFalse(out['rendered']);self.assertEqual(len(json.loads(source.read_text())),1)

if __name__=='__main__':unittest.main()
