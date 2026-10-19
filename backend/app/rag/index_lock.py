"""Session-scoped PG build lock; no long write transaction during model calls."""
from contextlib import contextmanager
import hashlib
import threading
import time
from sqlalchemy import text

_sqlite_lock = threading.Lock()
KEY = int.from_bytes(hashlib.sha256(b'dora-rag:repository-json').digest()[:8], 'big', signed=True)


@contextmanager
def build_lock(engine, budget):
    with engine.connect() as conn:
        acquired = False
        try:
            while not acquired:
                budget.check()
                if engine.dialect.name == 'postgresql':
                    acquired = conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': KEY}).scalar()
                    conn.commit()
                else: acquired = _sqlite_lock.acquire(blocking=False)
                if not acquired: time.sleep(min(.05, budget.remaining()))
            budget.check()
            yield conn
        finally:
            if conn.in_transaction(): conn.rollback()
            if acquired:
                if engine.dialect.name == 'postgresql':
                    try:
                        conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': KEY}); conn.commit()
                    except Exception:
                        # A broken connection must not return a session-held lock to the pool.
                        conn.invalidate()
                else: _sqlite_lock.release()
