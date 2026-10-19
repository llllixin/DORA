"""独立 PostgreSQL 上的真实行锁竞争、回滚与旧事件表迁移回归。"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text, select
from app import db
from app.action import flow
from app.models import KnowledgeArchive
from app.repository import Repository


def main():
    assert db.get_engine().dialect.name == 'postgresql', '此测试必须用 PostgreSQL'
    repo = Repository()
    case_id = 'atomic-' + uuid4().hex[:10]
    repo.create_action_case({'id':case_id,'code':case_id,'case_title':'并发回归'}, [{'seq':1,'title':'核对'}])
    try:
        flow.start_step(repo,case_id,1)
        # 写入步骤后模拟后续操作失败，步骤必须回滚。
        with patch.object(flow,'_recompute_case_status',side_effect=RuntimeError('injected')):
            try: flow.done_step(repo,case_id,1)
            except RuntimeError: pass
            else: raise AssertionError('应失败')
        assert repo.get_action_case(case_id)['steps'][0]['status']=='in_progress'
        wrote, release, verifying = Event(), Event(), Event()
        original = Repository.set_action_step_status
        def pause_after_write(self,*args,**kwargs):
            result=original(self,*args,**kwargs)
            wrote.set()
            assert release.wait(8)
            return result
        def verify():
            verifying.set()
            return flow.verify(Repository(),case_id,'resolved','并发回归通过')
        with patch.object(Repository,'set_action_step_status',pause_after_write), ThreadPoolExecutor(2) as pool:
            finishing=pool.submit(flow.done_step,Repository(),case_id,1)
            assert wrote.wait(5)
            verifying_future=pool.submit(verify)
            assert verifying.wait(5)
            try:
                verifying_future.result(timeout=.2)
                raise AssertionError('verify 不应绕过未提交的案件行锁')
            except TimeoutError:
                pass
            finally:
                release.set()
            assert finishing.result(timeout=5)['status']=='waiting_verify'
            assert verifying_future.result(timeout=5)['status']=='resolved'
        try: flow.block_step(repo,case_id,1,'迟到请求')
        except flow.ActionFlowError: pass
        else: raise AssertionError('resolved 应冻结')
        assert repo.get_action_case(case_id)['status']=='resolved'
        with db.make_session() as session:
            assert len(session.execute(select(KnowledgeArchive).where(KnowledgeArchive.source_id==case_id)).scalars().all())==1
        print('Action: 实际并发阻塞、事务回滚、resolved 冻结和知识一致性通过')
    finally:
        repo.delete_action_case(case_id)
    # 独立 schema 模拟旧版唯一时间字段；两次迁移不丢行。
    original_engine=db._engine
    schema='migration_'+uuid4().hex[:10]
    with original_engine.begin() as conn: conn.execute(text(f'CREATE SCHEMA {schema}'))
    migration_engine=create_engine(db.DATABASE_URL,connect_args={'options':f'-csearch_path={schema}'})
    try:
        db._engine=migration_engine
        with migration_engine.begin() as conn:
            conn.execute(text('CREATE TABLE data_update_log (id SERIAL PRIMARY KEY, updated_at VARCHAR(16) NOT NULL, rows_added INTEGER NOT NULL, total_rows INTEGER NOT NULL, metrics JSON NOT NULL, CONSTRAINT uq_data_update UNIQUE(updated_at))'))
            conn.execute(text("INSERT INTO data_update_log(updated_at,rows_added,total_rows,metrics) VALUES ('09:32',1,1,'[]')"))
        db.init_db(); db.init_db()
        Repository().upsert_data_update(dict(updated_at='09:32',rows_added=2,total_rows=3,metrics=['margin']))
        Repository().upsert_data_update(dict(updated_at='2026-09-21T09:32:00.123456+08:00',rows_added=3,total_rows=6,metrics=['orders']))
        assert Repository().count_rows('data_update_log')==3
        assert Repository().get_latest_update()['metrics']==['orders']
        print('事件旧库迁移: 保留原行、同分钟追加、完整日期和重复迁移通过')
    finally:
        db._engine=original_engine
        migration_engine.dispose()
        with original_engine.begin() as conn: conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))


if __name__=='__main__': main()
