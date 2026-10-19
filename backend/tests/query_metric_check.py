import unittest
from datetime import date
from app.query.metrics import select_metric_rows,observed_period,freshness,read_metric,metric_binding_for_tool
from app.query.contracts import ReadPolicy
from app.query.read_view import QueryReadViewReader
from app.query.routing import classify_query
from app.rag.ontology import Ontology
from app.runtime.executor import RunContext
from tests.query_test_support import query_fixture

class Metrics(unittest.TestCase):
    def test_bound_physical_key_and_no_aggregate(self):
        o=Ontology.load()
        self.assertEqual(metric_binding_for_tool('margin',None,o)['dimension'],'全国')
        self.assertEqual(metric_binding_for_tool('east_orders',None,o)['dimension'],'华东')
        self.assertIsNone(metric_binding_for_tool('unknown',None,o))
        self.assertEqual(metric_binding_for_tool('margin','华东',o)['reasonCode'],'unsupported_dimension')
    def test_tail_after_natural_order_and_conflicting_duplicates(self):
        rows=[{'label':k,'value':i,'dimension':'全国','unit':'%'} for i,k in enumerate(['W10','W1','W2'])]
        self.assertEqual([r['label'] for r in select_metric_rows(rows,dimension='全国',limit=2)],['W2','W10'])
        with self.assertRaisesRegex(ValueError,'ambiguous_source_rows'):select_metric_rows([rows[0],{**rows[0],'value':99}],dimension='全国',limit=2)
        with self.assertRaisesRegex(ValueError,'incomparable_periods'):select_metric_rows([rows[0],{**rows[1],'label':'2026-10-16'}],dimension='全国',limit=2)
    def test_today_at_shanghai_midnight_and_other_subject_same_value(self):
        day=date(2026,10,16)
        self.assertEqual(freshness('today',[observed_period('2026-10-16')],business_date=day)['freshnessStatus'],'verified_today')
        self.assertEqual(freshness('today',[observed_period('2026-10-15')],business_date=day)['freshnessStatus'],'unverified_today')
        rows=[dict(label='当前',value=12,dimension=d,unit='%') for d in ['门店1','门店2']]
        self.assertEqual(select_metric_rows(rows,dimension='门店1',limit=2),[rows[0]])
    def test_relative_or_missing_year_not_today(self):
        for label in ('当前','10/16','W10','2026-02-30'):
            self.assertIsNone(observed_period(label)['isoDate'])
            self.assertEqual(freshness('today',[observed_period(label)],business_date=date(2026,10,16))['freshnessStatus'],'unverified_today')
        self.assertEqual(freshness('unsupported',[],business_date=date(2026,10,16))['reasonCode'],'unsupported_time_range')
    def test_unknown_unit_and_metric_sample_in_mixed_database(self):
        o=Ontology.load()
        for mode,expected in [('sample',0),('uploaded',1)]:
            with query_fixture([],metric_rows=[dict(metric_key='margin',label='当前',value=12,dimension='全国',unit='')],source_mode=mode) as f:
                r=RunContext('unified-answer');p=classify_query('今天全国利润率是多少？',o,on_date=date(2026,10,16))
                v=QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now).capture(p,run_context=r)
                result=read_metric(v,p.binding,limit=200,requested_time='today',policy=ReadPolicy(),include_simulated=False,run_context=r)
                self.assertEqual(len(result['rows']),expected)
                if expected:self.assertIn('unknown_unit',result['warnings']);self.assertEqual(result['freshnessStatus'],'unverified_today')
