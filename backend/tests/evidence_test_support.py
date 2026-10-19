"""Explicit isolated evidence fixtures; never seed or connect to an implicit DB."""
from copy import deepcopy
from app.business_version import FrozenBusiness, build_version
from app.seed import series_items, rule_items, CLUSTER_STORES
from app.repository import _cast


def raw_inputs(generation=1, margin=None):
    rows = series_items()
    if margin is not None:
        for row in rows:
            if row['metric_key'] == 'margin': row['value'] = margin
    rules = rule_items()
    return dict(scopeId='dora:default', sourceEpoch='a05-test-epoch', generation=generation,
                rows=rows, clusters=[dict(store=s, region=r, aov=v) for s,r,v in CLUSTER_STORES],
                event=dict(eventId=1, updated='fixture:observed', rows_added=len(rows), total_rows=len(rows),
                           metrics=sorted({r['metric_key'] for r in rows})),
                rules={r['key']:_cast(r['value'],r['value_type']) for r in rules}, ruleRows=rules,
                sourceManifest={**{'metric:'+r['metric_key']:'sample' for r in rows},
                                'rules':'sample','cluster':'sample','event':'sample'},
                counts=dict(metric_series=len(rows),store_cluster_store=len(CLUSTER_STORES),rule_config=len(rules),data_update_log=1))


def frozen_inputs(generation=1, margin=None, profile=None):
    raw=raw_inputs(generation,margin)
    return FrozenBusiness(raw,build_version(raw,profile=profile or {'fixture':'template'}))


from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from sqlalchemy import create_engine, event
from app import db
from app.repository import Repository


@contextmanager
def evidence_fixture():
    with TemporaryDirectory(prefix='dora-a05-') as folder:
        engine=create_engine('sqlite:///'+str(Path(folder)/'db.sqlite'),connect_args={'timeout':2})
        @event.listens_for(engine,'connect')
        def foreign_keys(connection,_):connection.execute('PRAGMA foreign_keys=ON')
        try:
            with patch.object(db,'_engine',engine):
                db.init_db();repo=Repository();raw=raw_inputs()
                with repo.business_transaction(source_mode='sample') as tx:
                    tx.upsert_series(raw['rows']);tx.upsert_cluster_stores(raw['clusters']);tx.upsert_rules(raw['ruleRows'])
                    tx.upsert_data_update(dict(updated_at='fixture:observed',rows_added=len(raw['rows']),total_rows=len(raw['rows']),metrics=raw['event']['metrics']))
                yield repo,engine
        finally:engine.dispose()
