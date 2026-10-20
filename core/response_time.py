"""Local, monotonic round-trip samples carried by optional ping probes."""

import threading
import time


FRESH_SECONDS = 3.0
_MAX_PROBE_ID = 2**31 - 1


class ResponseTime:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._next_id = 0
        self._pending = None
        self._sample = None

    def new_probe(self):
        now = self._clock()
        with self._lock:
            if self._pending is not None:
                if now - self._pending[1] < FRESH_SECONDS:
                    return None
                self._pending = None
            self._next_id += 1
            if self._next_id > _MAX_PROBE_ID:
                self._next_id = 1
            return self._next_id

    def sent(self, identifier):
        now = self._clock()
        with self._lock:
            self._pending = (identifier, now)

    def echoed(self, identifier):
        now = self._clock()
        with self._lock:
            pending = self._pending
            if pending is None or pending[0] != identifier:
                return False
            self._pending = None
            sent_at = pending[1]
            if now - sent_at > FRESH_SECONDS:
                return False
            self._sample = (now, max(0.0, now - sent_at))
            return True

    @property
    def response_time_ms(self):
        with self._lock:
            if self._sample is None:
                return None
            at, elapsed = self._sample
            if self._clock() - at > FRESH_SECONDS:
                self._sample = None
                return None
            return round(elapsed * 1000)

    def reset(self):
        with self._lock:
            self._pending = None
            self._sample = None
