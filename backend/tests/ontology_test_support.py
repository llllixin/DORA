"""Test-only file index and in-memory run store; use production chunk preparation."""
from types import SimpleNamespace

from app.rag.contracts import is_current_reviewed, load_documents
from app.rag.indexer import RagIndexer
from app.rag.repository import RagRepository
from app.runtime.executor import RunContext


class FileChunks:
    def __init__(self, embedding):
        documents = load_documents()
        latest = {}
        for doc in documents:
            if is_current_reviewed(doc):
                latest[doc["id"]] = max(latest.get(doc["id"], 0), doc["version"])
        self.chunks = []
        run = RunContext('rag-index', external=False)
        for doc in documents:
            if doc["version"] == latest.get(doc["id"]):
                prepared = RagIndexer(self, embedding)._prepare(doc, run_context=run)
                self.chunks.extend(RagRepository._chunk_dict(SimpleNamespace(**row), SimpleNamespace(knowledge_type=doc["knowledge_type"])) for row in prepared["chunks"])
        run.finish({})

    def active_chunks(self, knowledge_types=None):
        return [dict(row) for row in self.chunks if not knowledge_types or row["knowledge_type"] in knowledge_types]


class RunStore:
    def __init__(self):
        self.runs = {}

    def create_agent_run(self, **kwargs):
        run_id = f"test-{len(self.runs) + 1}"
        self.runs[run_id] = {"id": run_id, **kwargs}
        return self.runs[run_id]

    def append_agent_run_event(self, run_id, event):
        self.runs[run_id]["events"].append(event)
        return self.runs[run_id]

    def finish_agent_run(self, run_id, status, output):
        self.runs[run_id].update(status=status, output=output)
        return self.runs[run_id]
        return self.runs[run_id]
