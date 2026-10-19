"""P033 可重复回归：使用临时 SQLite，不访问用户数据库。"""
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from fastapi.testclient import TestClient
from app import db
from app.models import Base
from app.ingest import IngestValidationError, parse_dataset, items_from_mapping
from app.repository import Repository
from app.engine.engine import compute_snapshot, run_engine, engine_evidence
from app.seed import run_seed
from app.main import app


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = db._engine
        db._engine = create_engine('sqlite:///' + str(Path(self.tmp.name) / 'test.sqlite'))
        Base.metadata.create_all(db._engine)
        self.repo = Repository()
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        db._engine.dispose()
        db._engine = self.old
        self.tmp.cleanup()

    def rows(self, key, vals, dim='全国'):
        return [dict(metric_key=key, label=f'2026-09-{i+1:02}', value=v, dimension=dim, unit='%') for i,v in enumerate(vals)]

    def test_zero_baselines(self):
        run_seed()
        for key, dim in [('margin','全国'), ('orders','全国'), ('revenue','全国'), ('aov','全国'), ('east_orders','华东'), ('new_sku','全区域')]:
            vals = [0,0,0,0,10] if key == 'margin' else [0,0,10]
            self.repo.replace_series([key], self.rows(key, vals, dim))
            self.assertIsNone(compute_snapshot(self.repo)[key]['delta_pct'])
        self.assertEqual(self.client.get('/api/pulse').status_code, 200)
        self.assertEqual(self.client.get('/api/insights').status_code, 200)
        # 增幅无定义时不得产生基于增幅的“新品高速增长”结论。
        self.assertNotIn('c3', [x['id'] for x in run_engine(self.repo)['insights']])

    def test_omitted_dimension(self):
        raw = [dict(date=f'2026-09-0{i+1}', value=str(v)) for i,v in enumerate([17,16,15,14])]
        items=items_from_mapping(raw, dict(metric_key='margin',label_column='date',value_column='value'))
        self.repo.replace_series(['margin'], items)
        self.assertEqual(compute_snapshot(self.repo)['margin']['current'], 14)
        self.assertIn('p1',[x['id'] for x in run_engine(self.repo)['insights']])
        with self.assertRaises(IngestValidationError):
            items_from_mapping(raw, dict(metric_key='returns',label_column='date',value_column='value'))

    def test_order_and_trend(self):
        rows=self.rows('margin',[20,17,16,15])
        self.repo.replace_series(['margin'], rows)
        before=compute_snapshot(self.repo)['margin']
        self.repo.replace_series(['margin'], list(reversed(rows)))
        self.assertEqual(before,compute_snapshot(self.repo)['margin'])
        self.repo.replace_series(['returns'],self.rows('returns',[8,7,6,5], '门店X'))
        self.assertNotIn('p2',[x['id'] for x in run_engine(self.repo)['insights']])
        self.repo.replace_series(['returns'],self.rows('returns',[3,4,5,6,7], '门店X'))
        self.assertIn('p2',[x['id'] for x in run_engine(self.repo)['insights']])
        p2=next(x for x in run_engine(self.repo)['insights'] if x['id']=='p2')
        self.assertIn('门店X',p2['semantics']['causeA']['value'])

    def test_bad_files_do_not_change_data(self):
        self.repo.replace_series(['margin'],self.rows('margin',[20,17,16,15]))
        before=self.repo.get_series('margin')
        for name, data in [('bad.xlsx',b'not zip'),('bad.csv',b'\xff\xfe'),('dupe.csv',b'metric_key,label,value\nmargin,2026-09-01,17\nmargin,2026-09-01,16\n')]:
            response=self.client.post('/api/datasets',files={'file':(name,data)})
            self.assertEqual(response.status_code,400,(name,response.text))
            self.assertEqual(self.repo.get_series('margin'),before)
        response=self.client.post('/api/datasets/mapped',files={'file':('x.csv',b'date,value\n2026-09-01,17\n')},data={'mapping':json.dumps(dict(metric_key=123,label_column='date',value_column='value'))})
        self.assertEqual(response.status_code,400,response.text)

    def test_update_events_append(self):
        for time,metric in [('09:32','margin'),('10:00','orders'),('09:32','revenue')]:
            self.repo.upsert_data_update(dict(updated_at=time,rows_added=1,total_rows=1,metrics=[metric]))
        self.assertEqual(self.repo.count_rows('data_update_log'),3)
        self.assertEqual(self.repo.get_latest_update()['metrics'],['revenue'])

    def test_chart_and_evidence_follow_data(self):
        self.repo.replace_series(['margin'],self.rows('margin',[20,17,16,15]))
        self.repo.upsert_rules([dict(key='margin.target',value='16.5',value_type='float')])
        # 三期低于新的目标
        self.repo.replace_series(['margin'],self.rows('margin',[20,16,15,14]))
        p1=next(x for x in run_engine(self.repo)['insights'] if x['id']=='p1')
        self.assertEqual(p1['chart']['series'][0]['values'],[20,16,15,14])
        self.assertEqual(p1['chart']['threshold']['value'],16.5)
        rows=engine_evidence('p1',self.repo)['rawRows']
        self.assertEqual(rows[0][-1],'正常')
        self.assertEqual(rows[1][-1],'低于目标')


if __name__=='__main__':
    unittest.main()
