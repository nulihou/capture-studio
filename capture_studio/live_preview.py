"""Bounded latest-PNG preview from one persistent GStreamer camera stream."""
import signal
import struct
import subprocess
import threading
import time
import json
import sys
from pathlib import Path


PREVIEW_PNG_LIMIT = 8_000_000


def read_exact(stream, count):
    body = bytearray()
    while len(body) < count:
        block = stream.read(count-len(body))
        if not block:
            raise EOFError('preview stream ended')
        body.extend(block)
    return bytes(body)


def read_png(stream):
    body = bytearray(read_exact(stream, 8))
    if body != b'\x89PNG\r\n\x1a\n':
        raise ValueError('invalid preview PNG signature')
    while True:
        header = read_exact(stream, 8)
        size = struct.unpack('>I', header[:4])[0]
        if size > PREVIEW_PNG_LIMIT or len(body) + size + 12 > PREVIEW_PNG_LIMIT:
            raise ValueError('preview frame exceeds size limit')
        body.extend(header)
        body.extend(read_exact(stream, size+4))
        if header[4:] == b'IEND':
            return bytes(body)


class LivePreview:
    def __init__(self, options):
        command = [sys.executable, '-m', 'capture_studio.preview_worker', json.dumps(options.__dict__)]
        self.process = subprocess.Popen(command, cwd=Path(__file__).resolve().parent.parent,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lock = threading.Lock()
        self.frame = None
        self.frame_time = 0
        self.error = None
        self.last_access = time.monotonic()
        self.metrics = {'warming_up': True, 'source_fps': None, 'preview_fps': None}
        self.metrics_time = 0
        self.metrics_thread = threading.Thread(target=self._metrics, daemon=True)
        self.metrics_thread.start()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _metrics(self):
        for line in self.process.stderr:
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            with self.lock:
                if 'error' in value:
                    self.error = value['error']
                else:
                    self.metrics = value
                    self.metrics_time = time.monotonic()

    def telemetry(self):
        with self.lock:
            value = dict(self.metrics)
            value['stale'] = time.monotonic()-self.metrics_time > 3
            if value['stale'] or self.process.poll() is not None:
                value['source_fps'] = value['preview_fps'] = None
            return value

    def _read(self):
        try:
            while self.process.poll() is None:
                frame = read_png(self.process.stdout)
                with self.lock:
                    self.frame = frame
                    self.frame_time = time.monotonic()
                    abandoned = self.frame_time-self.last_access > 30
                if abandoned:
                    self.process.terminate()
                    break
        except (EOFError, OSError, ValueError) as error:
            self.error = str(error)
        finally:
            if self.process.poll() is None:
                self.process.terminate()

    def latest(self):
        with self.lock:
            self.last_access = time.monotonic()
            if self.process.poll() is not None or self.error:
                raise RuntimeError(self.error or 'preview process stopped')
            if self.frame is None:
                raise RuntimeError('preview warming up')
            if self.last_access-self.frame_time > 3:
                raise RuntimeError('preview frame is stale')
            return self.frame

    def stop(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.thread.join(timeout=2)
        self.metrics_thread.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()
