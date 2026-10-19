"""Explicitly local runtime test fixtures; no credentials or database."""
from copy import deepcopy
from io import BytesIO
from threading import RLock


class MemoryRuns:
    def __init__(self): self.rows = {}; self.lock = RLock()
    def create_agent_run(self, **kwargs):
        with self.lock:
            key = 'r-test-' + str(len(self.rows))
            self.rows[key] = {'id': key, 'status': kwargs.get('status'), 'input': kwargs.get('input_data', {}),
                              'events': deepcopy(kwargs.get('events', [])), 'output': deepcopy(kwargs.get('output', {}))}
            return deepcopy(self.rows[key])
    def append_agent_run_event(self, key, event):
        with self.lock:
            if key not in self.rows: return None
            self.rows[key]['events'].append(deepcopy(event)); return deepcopy(self.rows[key])
    def finish_agent_run(self, key, status, output):
        with self.lock:
            if key not in self.rows: return None
            self.rows[key].update(status=status, output=deepcopy(output)); return deepcopy(self.rows[key])
    def get_agent_run(self, key): return deepcopy(self.rows.get(key))


class Response(BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
