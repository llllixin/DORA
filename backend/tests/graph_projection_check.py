import unittest
from dataclasses import replace
from unittest.mock import patch
from tests.graph_test_support import graph_fixture, open_case
from app.graph.source import SourceReader
from app.graph.contracts import Budget, GraphError, GraphLimits
try:
    from app.graph.projector import project
except ImportError:
    project = None


class GraphProjection(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(project, 'A09 graph projector missing')

    def test_real_capture_chain_and_every_edge_has_source(self):
        from app.watch.evaluator import evaluate_one
        with graph_fixture() as (repo, engine, source):
            opened = open_case(repo)
            target = repo.create_watch_target('margin', dict(metric_key='margin', condition=dict(type='below', ref=100)))
            evaluate_one(repo, target)
            view = SourceReader(engine, source).capture(Budget())
            with patch('app.engine.engine.run_engine', side_effect=AssertionError('history must not recompute')):
                graph = project(view, GraphLimits(), Budget())
            kinds = {e['type'] for e in graph['relations']}
            self.assertTrue({'opened_from','opened_with','emitted','monitors','event_matched','supported_by','captured_in','produced_occurrence'} <= kinds)
            self.assertEqual({w['relationId'] for w in graph['evidence']}, {e['id'] for e in graph['relations']})
            self.assertTrue(any(n['attributes'].get('occurrenceId') == opened['openingBinding']['occurrenceId'] for n in graph['nodes']))
            for witness in graph['evidence']:
                value = view['records'][witness['sourceKey']]['data']
                for field in witness['pointer'].split('/')[1:]:
                    value = value[int(field)] if isinstance(value,list) else value[field]
                self.assertEqual(value, witness['data'])
            observations = [n['attributes']['row'] for n in graph['nodes'] if n['type']=='MetricObservation']
            self.assertTrue(any(r['metric_key']=='margin' and r['value']==18.1 and r['unit']=='%' for r in observations))

    def test_same_type_in_new_generation_keeps_distinct_occurrences(self):
        from tests.evidence_test_support import raw_inputs
        with graph_fixture() as (repo,engine,source):
            one=open_case(repo)
            repo.upsert_series(raw_inputs(margin=17)['rows']); two=open_case(repo)
            graph=project(SourceReader(engine,source).capture(Budget()),GraphLimits(),Budget())
            cases=[n for n in graph['nodes'] if n['type']=='ActionCase']
            self.assertEqual(len(cases),2)
            self.assertNotEqual(one['openingBinding']['occurrenceId'],two['openingBinding']['occurrenceId'])
            self.assertEqual(len({n['id'] for n in cases}),2)
            self.assertEqual(len([n for n in graph['nodes'] if n['type']=='Rule']),1,
                             'same rule version must not duplicate for another snapshot')

    def test_repeat_projection_and_profile_change_do_not_multiply_facts(self):
        with graph_fixture() as (repo,engine,source):
            open_case(repo); reader=SourceReader(engine,source)
            first=project(reader.capture(Budget()),GraphLimits(),Budget())
            with patch.dict('os.environ',{'DORA_LLM_MODEL':'different-model'}):
                second=project(reader.capture(Budget()),GraphLimits(),Budget())
            self.assertEqual(first,second)

    def test_legacy_and_build_limit_are_explicit(self):
        with graph_fixture() as (repo,engine,source):
            open_case(repo); view=SourceReader(engine,source).capture(Budget())
            view['bindings'][0]['source_record'].pop('insight',None)
            with self.assertRaises(GraphError): project(view,replace(GraphLimits(),maxBuildNodes=2),Budget())

    def test_observation_keeps_raw_period_dimension_and_changed_row_value(self):
        from tests.evidence_test_support import raw_inputs
        with graph_fixture() as (repo,engine,source):
            raw=raw_inputs(margin=17)['rows']
            margin_rows=[r for r in raw if r['metric_key']=='margin']
            for index,row in enumerate(margin_rows):row.update(label=f'10/{index+1:02}',dimension='全国')
            with repo.business_transaction(source_mode='sample') as tx:tx.delete_all_series();tx.upsert_series(raw)
            open_case(repo)
            first=project(SourceReader(engine,source).capture(Budget()),GraphLimits(),Budget())
            observations=[n for n in first['nodes'] if n['type']=='MetricObservation' and n['attributes']['row']['metric_key']=='margin']
            self.assertTrue(observations)
            for node in observations:
                self.assertRegex(node['attributes']['row']['label'],r'^10/\d{2}$')
                self.assertEqual(node['attributes']['row']['dimension'],'全国');self.assertEqual(node['attributes']['row']['unit'],'%')
            with repo.business_transaction(source_mode='sample') as tx:tx.delete_all_series();tx.upsert_series(raw_inputs(margin=16)['rows'])
            open_case(repo)
            second=project(SourceReader(engine,source).capture(Budget()),GraphLimits(),Budget())
            old={n['id'] for n in observations}
            new={n['id'] for n in second['nodes'] if n['type']=='MetricObservation' and n['attributes']['row']['value']==16}
            self.assertTrue(new);self.assertFalse(old&new)

    def test_missing_legacy_opening_and_watch_intent_never_get_guessed(self):
        from copy import deepcopy
        from sqlalchemy import select
        from app.models import EvidenceBinding
        from app.watch.evaluator import evaluate_one
        with graph_fixture() as (repo,engine,source):
            opened=open_case(repo);legacy={**opened['case'],'id':'legacy-only'}
            repo.create_action_case(legacy,[])
            target=repo.create_watch_target('margin',dict(metric_key='margin',condition=dict(type='below',ref=100)));evaluate_one(repo,target)
            with repo._session_ctx() as s:
                binding=s.scalar(select(EvidenceBinding).where(EvidenceBinding.owner_kind=='watch_event'))
                record=deepcopy(binding.source_record);record['target'].pop('intent');binding.source_record=record;s.commit()
            graph=project(SourceReader(engine,source).capture(Budget()),GraphLimits(),Budget())
            reasons={m['reason'] for m in graph['missingEvidence']}
            self.assertTrue({'opening_not_captured','watch_intent_not_captured'}<=reasons)
            self.assertFalse(any(n['type']=='WatchTarget' or n['attributes'].get('caseId')=='legacy-only' for n in graph['nodes']))

    def test_each_graph_cardinality_limit_rejects_the_whole_projection(self):
        with graph_fixture() as (repo,engine,source):
            open_case(repo);view=SourceReader(engine,source).capture(Budget())
            for field in ('maxBuildNodes','maxBuildRelations','maxBuildWitnesses'):
                with self.subTest(field=field),self.assertRaises(GraphError) as error:
                    project(view,replace(GraphLimits(),**{field:0}),Budget())
                self.assertEqual(error.exception.code,'build_input_limit')

    def test_reused_public_case_id_keeps_old_and_new_instances_separate(self):
        from app.action.builder import create_case_from_insight
        from app.engine.engine import run_engine
        with graph_fixture() as (repo,engine,source):
            insight=next(i for i in run_engine(repo)['insights'] if i['id']=='p1')
            first=create_case_from_insight(repo,insight);repo.delete_action_case('p1')
            second=create_case_from_insight(repo,insight)
            graph=project(SourceReader(engine,source).capture(Budget()),GraphLimits(),Budget())
            cases=[n for n in graph['nodes'] if n['type']=='ActionCase']
            self.assertEqual(len(cases),2);self.assertEqual({n['attributes']['caseId'] for n in cases},{'p1'})
            self.assertEqual({n['attributes']['caseInstanceId'] for n in cases},
                             {first['openingBinding']['sourceInstanceId'],second['openingBinding']['sourceInstanceId']})


if __name__=='__main__': unittest.main()
