"""Version-keyed in-process deduplication. Database checks provide write safety."""
from dataclasses import dataclass, field
from threading import Event, Lock


@dataclass
class _Flight:
    done: Event = field(default_factory=Event)
    result: object = None
    error: BaseException | None = None


class SingleFlight:
    def __init__(self):
        self._lock = Lock()
        self._active = {}

    def run(self, key, callback, *, on_join=None):
        with self._lock:
            flight = self._active.get(key)
            owner = flight is None
            if owner:
                flight = _Flight()
                self._active[key] = flight
        if not owner:
            if on_join is not None: on_join()
            flight.done.wait()
            if flight.error is not None: raise flight.error
            return flight.result
        try:
            flight.result = callback()
            return flight.result
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._active.pop(key, None)
                flight.done.set()
