"""Actual arrival counts over a monotonic rolling window."""
from collections import deque
import threading
import time


class FrameRates:
    def __init__(self, clock=time.monotonic, window=3.0):
        self.clock = clock
        self.window = window
        self.begin = clock()
        self.source = deque(maxlen=4096)
        self.preview = deque(maxlen=4096)
        self.source_total = 0
        self.lock = threading.Lock()

    def tick(self, source=True):
        with self.lock:
            now = self.clock()
            (self.source if source else self.preview).append(now)
            if source:
                self.source_total += 1

    def status(self):
        with self.lock:
            now = self.clock()
            for values in (self.source, self.preview):
                while values and values[0] <= now-self.window:
                    values.popleft()
            ready = now-self.begin >= self.window+2
            return {'source_fps': len(self.source)/self.window if ready else None,
                    'preview_fps': len(self.preview)/self.window if ready else None,
                    'window_seconds': self.window, 'source_buffers_total': self.source_total,
                    'measured_monotonic': now, 'warming_up': not ready,
                    'scope': 'V4L2 source-pad buffer deliveries before decode/preview limiting; not sensor exposures or unique-image proof'}
