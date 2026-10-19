"""Authoritative file snapshots; both source lock acquisitions share run deadline."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import fcntl
from pathlib import Path
import time
from zoneinfo import ZoneInfo
import json
from app.rag.contracts import KNOWLEDGE_ROOT, load_documents, RagContractError, RagIndexUnavailable
from app.rag.identity import canonical, digest
from app.runtime.contracts import RuntimeFailure


class Deadline:
    def __init__(self, seconds=5): self.end = time.monotonic() + seconds
    def remaining(self): return max(0, self.end - time.monotonic())
    def check(self):
        if self.remaining() <= 0: raise RuntimeFailure('deadline_exceeded')


@dataclass(frozen=True)
class SourceSnapshot:
    payload: str
    revision: str
    business_date: object
    as_of: str

    @property
    def documents(self): return json.loads(self.payload)


class KnowledgeSource:
    def __init__(self, path=None): self.path = Path(path or KNOWLEDGE_ROOT / 'documents.json')

    @contextmanager
    def locked_snapshot(self, *, on_date=None, budget=None, max_bytes=None):
        budget = budget or Deadline()
        try:
            with self.path.with_suffix(self.path.suffix + '.lock').open('a') as lock:
                while True:
                    budget.check()
                    try:
                        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(min(.05, budget.remaining()))
                try:
                    budget.check()
                    try:
                        if max_bytes is not None and self.path.stat().st_size > max_bytes: raise RuntimeFailure('read_view_limit')
                        payload = canonical(load_documents(self.path))
                        if max_bytes is not None and len(payload.encode('utf-8')) > max_bytes: raise RuntimeFailure('read_view_limit')
                    except (ValueError, TypeError) as exc:
                        raise RagIndexUnavailable('source_unavailable') from exc
                    budget.check()
                    now = datetime.now(ZoneInfo('Asia/Shanghai'))
                    yield SourceSnapshot(payload, digest(payload), on_date or now.date(), now.isoformat())
                finally: fcntl.flock(lock, fcntl.LOCK_UN)
        except (OSError, RagContractError) as exc:
            raise RagIndexUnavailable('source_unavailable') from exc

    def snapshot(self, *, on_date=None, budget=None, max_bytes=None):
        with self.locked_snapshot(on_date=on_date, budget=budget, max_bytes=max_bytes) as snap: return snap
