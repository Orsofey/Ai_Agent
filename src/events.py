"""In-process event bus → Server-Sent Events for all open windows."""
import json
import queue
import threading
import time


class EventBus:
    def __init__(self):
        self.subscribers = set()
        self.lock = threading.Lock()
        self.last_level = 0.0

    def emit(self, kind, **data):
        payload = json.dumps(dict(data, type=kind, time=time.time()), ensure_ascii=False)
        with self.lock:
            targets = list(self.subscribers)
        for q in targets:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    def level(self, value):
        """Уровень микрофона для анимации — не чаще 12 раз в секунду."""
        now = time.monotonic()
        if now - self.last_level >= 0.08:
            self.last_level = now
            self.emit('level', value=round(min(1.0, value * 8), 3))

    def stream(self, heartbeat=15.0):
        q = queue.Queue(maxsize=300)
        with self.lock:
            self.subscribers.add(q)
        try:
            yield 'retry: 2000\n\n'
            while True:
                try:
                    payload = q.get(timeout=heartbeat)
                    yield f'data: {payload}\n\n'
                except queue.Empty:
                    yield ': ping\n\n'
        finally:
            with self.lock:
                self.subscribers.discard(q)
