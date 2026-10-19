"""Request-local database admission; never changes a shared pool's timeout.

SQLAlchemy 2.x has no per-checkout timeout argument. The small QueuePool facade
below follows its _do_get algorithm with a request-local queue wait, and uses its
normal ConnectionFairy checkin/invalidation machinery. PostgreSQL psycopg waits
use the same deadline (libpq connect_timeout alone rounds to whole seconds).
"""
from contextlib import contextmanager
from contextvars import ContextVar
import ipaddress
import os
import threading
from weakref import WeakSet

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.pool.base import _ConnectionFairy
from sqlalchemy.util import queue

_current = ContextVar('dora_database_budget', default=None)
_installed = WeakSet()
_install_lock = threading.Lock()


def current_budget(): return _current.get()


@contextmanager
def budget_scope(budget):
    token = _current.set(budget)
    try: yield
    finally: _current.reset(token)


def guard_budget(guard):
    """Legacy commit_guard=budget.check still carries its owner budget."""
    owner = getattr(guard, '__self__', None)
    return owner if owner is not None and hasattr(owner, 'remaining') else current_budget()


class _BudgetPool:
    def __init__(self, pool, budget): self.pool, self.budget = pool, budget
    def __getattr__(self, name): return getattr(self.pool, name)
    # A stale connection fails during its bounded first operation. Pool pre-ping
    # happens before a Connection exists, so do not run that unguarded SQL here.
    _pre_ping = False
    def _do_get(self):
        pool, budget = self.pool, self.budget
        if not isinstance(pool, QueuePool):
            budget.check(); result = pool._do_get(); budget.check(); return result
        while True:
            budget.check()
            limited = pool._max_overflow > -1
            wait = limited and pool._overflow >= pool._max_overflow
            try: return pool._pool.get(wait, min(pool.timeout(), budget.remaining()))
            except queue.Empty: pass
            budget.check()
            if limited and pool._overflow >= pool._max_overflow:
                if not wait: continue
                # A shorter configured pool timeout remains a datasource failure.
                from sqlalchemy.exc import TimeoutError
                raise TimeoutError('database pool acquisition timed out')
            if pool._inc_overflow():
                try: return pool._create_connection()
                except BaseException:
                    pool._dec_overflow(); raise


def _checked_generator(gen, budget, on_error=None):
    try:
        budget.check(); state = next(gen)
        while True:
            budget.check()
            ready = yield state
            budget.check(); state = gen.send(ready)
    except StopIteration as done: return done.value
    except BaseException:
        if on_error is not None: on_error()
        raise
    finally: gen.close()


def _pg_wait(connection, gen, budget, interval=.01, invalidate=None):
    from psycopg import waiting
    return waiting.wait(_checked_generator(gen, budget, invalidate or connection.close),
                        connection.pgconn.socket, interval=min(.01, budget.remaining()))


def _install_pg_wait(raw):
    # The dispatcher stays on the DBAPI connection through checkin. Restoring a
    # per-checkout method after checkin could overwrite the next borrower's guard.
    if getattr(raw, '_dora_original_wait', None) is not None: return
    original_wait = raw.wait
    raw._dora_original_wait = original_wait
    def wait(gen, interval=.01):
        active = current_budget()
        if active is None: return original_wait(gen, interval)
        owner = getattr(raw, '_dora_sqlalchemy_connection', None)
        invalidate = owner.invalidate if owner is not None and not owner.closed else raw.close
        return _pg_wait(raw, gen, active, interval, invalidate)
    raw.wait = wait


def _pg_connect(cargs, cparams, budget):
    from psycopg import Connection as PsycopgConnection, pq, waiting
    from psycopg.conninfo import make_conninfo
    # libpq's synchronous DNS can block before its poll generator yields. Fail
    # closed for un-resolved remote hosts: configure hostaddr alongside host.
    options = dict(cparams)
    python_options = {key:options.pop(key) for key in ('autocommit','prepare_threshold','context','row_factory','cursor_factory') if key in options}
    params = PsycopgConnection._get_connection_params(cargs[0] if cargs else '', **options)
    if params.get('service') or os.environ.get('PGSERVICE'):
        raise ValueError('deadline database connections require explicit host/hostaddr rather than a libpq service')
    host = params.get('host', os.environ.get('PGHOST',''))
    hostaddr = params.get('hostaddr', os.environ.get('PGHOSTADDR',''))
    if hostaddr:
        for address in hostaddr.split(','):
            try: ipaddress.ip_address(address)
            except ValueError: raise ValueError('deadline database connections require numeric hostaddr') from None
        params['hostaddr'] = hostaddr
    if host and not host.startswith('/') and not hostaddr:
        addresses = []
        for value in host.split(','):
            if value == 'localhost': value = '127.0.0.1'
            try: addresses.append(str(ipaddress.ip_address(value)))
            except ValueError: raise ValueError('deadline database connections require hostaddr for DNS hostnames') from None
        params['hostaddr'] = ','.join(addresses)
    budget.check()
    pgconn = pq.PGconn.connect_start(make_conninfo('', **params).encode())
    def connect_gen():
        try:
            while True:
                budget.check(); state = pgconn.connect_poll()
                if state == pq.PollingStatus.OK:
                    pgconn.nonblocking = 1
                    return pgconn
                if state == pq.PollingStatus.FAILED:
                    from psycopg import OperationalError
                    raise OperationalError('database connection failed')
                yield pgconn.socket, 1 if state == pq.PollingStatus.READING else 2
        except BaseException:
            pgconn.finish(); raise
    gen = _checked_generator(connect_gen(), budget, pgconn.finish)
    raw = waiting.wait_conn(gen, interval=min(.01, budget.remaining()))
    connection = PsycopgConnection(raw)
    connection._autocommit = bool(python_options.get('autocommit',False))
    connection.prepare_threshold = python_options.get('prepare_threshold',5)
    if python_options.get('context') is not None:
        from psycopg.adapt import AdaptersMap
        connection._adapters = AdaptersMap(python_options['context'].adapters)
    if python_options.get('row_factory') is not None: connection.row_factory = python_options['row_factory']
    if python_options.get('cursor_factory') is not None: connection.cursor_factory = python_options['cursor_factory']
    _install_pg_wait(connection)
    budget.check()
    return connection


def install_engine_budget(engine):
    with _install_lock:
        if engine in _installed: return
        def connect(dialect, record, cargs, cparams):
            budget = current_budget()
            if budget is None: return None
            budget.check()
            if dialect.name == 'postgresql':
                if dialect.driver != 'psycopg': raise ValueError('deadline database connections require psycopg')
                return _pg_connect(cargs, cparams, budget)
            if dialect.name == 'sqlite':
                return dialect.loaded_dbapi.connect(*cargs, **{**cparams, 'timeout':budget.remaining()})
            raise ValueError('unsupported deadline database driver')
        event.listen(engine, 'do_connect', connect)
        _installed.add(engine)


@contextmanager
def guard_connection(connection, budget, statement_ms=None):
    """Install guards before BEGIN, readiness inspection or the first query."""
    budget.check()
    raw = connection.connection.dbapi_connection
    if connection.dialect.name == 'postgresql':
        _install_pg_wait(raw)
        raw._dora_sqlalchemy_connection = connection
    def before_sql(conn, cursor, statement, parameters, context, executemany):
        budget.check()
        milliseconds = max(1, int(budget.remaining()*1000))
        if statement_ms is not None: milliseconds = min(milliseconds, statement_ms)
        control = raw.cursor()
        try:
            if conn.dialect.name == 'postgresql':
                control.execute(f'SET LOCAL statement_timeout = {milliseconds}')
                control.execute(f'SET LOCAL lock_timeout = {milliseconds}')
            elif conn.dialect.name == 'sqlite': control.execute(f'PRAGMA busy_timeout = {milliseconds}')
        finally: control.close()
        budget.check()
    event.listen(connection, 'before_cursor_execute', before_sql)
    previous_guard = getattr(connection, '_dora_budget', None)
    connection._dora_budget = budget
    try:
        with budget_scope(budget): yield connection
    finally:
        event.remove(connection, 'before_cursor_execute', before_sql)
        connection._dora_budget = previous_guard
        if connection.dialect.name == 'postgresql' and getattr(raw, '_dora_sqlalchemy_connection', None) is connection:
            raw._dora_sqlalchemy_connection = None


@contextmanager
def budget_connection(engine, budget=None, statement_ms=None):
    budget = budget or current_budget()
    if budget is None:
        with engine.connect() as connection: yield connection
        return
    budget.check(); install_engine_budget(engine)
    connection = None; fairy = None; primary_error = None
    with budget_scope(budget):
        try:
            fairy = _ConnectionFairy._checkout(_BudgetPool(engine.pool, budget))
            connection = Connection(engine, connection=fairy)
            with guard_connection(connection, budget, statement_ms):
                try:
                    yield connection
                except BaseException as exc:
                    primary_error = exc
                    raise
                finally:
                    try:
                        if budget.remaining() <= 0: connection.invalidate()
                        # Rollback and pool reset/checkin may perform driver I/O.
                        # They must finish before leaving this guard and scope.
                        connection.close()
                        budget.check()
                    except BaseException:
                        if primary_error is None: raise
        except Exception:
            # Dialect first-connect rollback may replace a timed-out I/O error
            # after socket invalidation. Preserve an existing caller exception.
            if primary_error is None: budget.check()
            raise
        finally:
            if connection is not None and not connection.closed:
                # Failure before/during guarded cleanup: close the socket first
                # so the final checkin cannot start another unguarded rollback.
                connection.invalidate()
                connection.close()
            elif connection is None and fairy is not None:
                fairy.invalidate(); fairy.close()


class BudgetSession(Session):
    """Repository sessions eagerly acquire inside their inherited budget scope."""
    def __init__(self, engine, budget):
        self._budget = budget
        self._budget_context = budget_connection(engine, budget)
        connection = self._budget_context.__enter__()
        try: super().__init__(bind=connection, autoflush=False, expire_on_commit=False)
        except BaseException:
            self._budget_context.__exit__(None,None,None); raise
    def close(self):
        if self._budget_context is not None and self._budget.remaining() <= 0: self.bind.invalidate()
        try: super().close()
        finally:
            if self._budget_context is not None:
                context, self._budget_context = self._budget_context, None
                context.__exit__(None,None,None)


def prepare_session(session, budget):
    budget.check()
    if getattr(session.bind, '_dora_budget', None) is budget: return
    from sqlalchemy.engine import Engine
    # Session.begin() creates a logical transaction before it checks out a
    # connection. Only an already enlisted bind may use session.connection()
    # here; otherwise acquire within the deadline without replacing that
    # caller-owned transaction. _connections is part of the SQLAlchemy 2.x
    # bridge already covered by the real QueuePool compatibility regressions.
    transaction = session.get_transaction()
    enlisted = transaction is not None and session.bind in transaction._connections
    if isinstance(session.bind, Engine) and not enlisted:
        context = budget_connection(session.bind, budget)
        connection = context.__enter__()
        previous_bind, previous_close = session.bind, session.close
        session.bind = connection
        def close():
            try: previous_close()
            finally:
                session.bind = previous_bind
                session.close = previous_close
                context.__exit__(None,None,None)
        session.close = close
        return
    connection = session.connection()
    if getattr(connection, '_dora_budget', None) is budget: return
    context = guard_connection(connection, budget)
    context.__enter__()
    def cleanup(session, transaction):
        if transaction.parent is None: context.__exit__(None,None,None)
    event.listen(session, 'after_transaction_end', cleanup, once=True)
    budget.check()


class RecordingBudget:
    """Bounded best-effort terminal persistence after the work deadline."""
    def __init__(self, milliseconds=250):
        import time
        self.clock=time.monotonic; self.end=self.clock()+milliseconds/1000
    def remaining(self):return max(0.,self.end-self.clock())
    def check(self):
        if self.remaining() <= 0:
            from app.runtime.contracts import RuntimeFailure
            raise RuntimeFailure('deadline_exceeded')
