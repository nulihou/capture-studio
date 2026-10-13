"""The verified HHW001 V4L2 producer; native timestamps feed GStreamer appsrc."""
import json
from dataclasses import replace
from pathlib import Path
import signal
import struct
import subprocess
import threading

from .board_devices import usb_image_devices


def uses_native(options):
    from .camera_lab import has_image_tuning
    # Extra image controls are applied by the generic V4L2 source. The verified
    # HHW001 path only owns exposure, so any other request leaves that path.
    if has_image_tuning(options):
        return False
    return (options.source_format == 'mjpeg' and
            (options.width, options.height, options.fps) == (640, 480, 30) and
            any(d['device'] == options.device and
                (d['vid'], d['pid'], d['serial']) == ('1c45', '6200', 'HHW001')
                for d in usb_image_devices()))


def effective_exposure(options):
    """Preview and recording share one policy. Unset means auto, the visible path."""
    if options.exposure_mode is None:
        return replace(options, exposure_mode=0)
    return options


def native_argv(binary, options, report, *, duration_sec=86400, sample_jpeg=None):
    options = effective_exposure(options)
    mode = options.exposure_mode
    # The capture program requires a positive absolute value even for auto.
    # Auto mode does not apply it and records the request as null.
    absolute = 1 if mode == 0 else options.exposure_absolute
    argv = [str(binary), '--device', options.device, '--exposure-mode', str(mode),
            '--manual-exposure', str(absolute), '--warmup-sec', '2',
            '--duration-sec', str(duration_sec), '--output-json', str(report)]
    if sample_jpeg is not None:
        argv.extend(['--sample-jpeg', str(sample_jpeg)])
    return argv


def read_exact(stream, size):
    result = bytearray()
    while len(result) < size:
        block = stream.read(size-len(result))
        if not block:
            if not result:
                raise EOFError
            raise RuntimeError('partial native frame')
        result.extend(block)
    return bytes(result)


class NativeSource:
    def __init__(self, options, appsrc, report, Gst):
        options = effective_exposure(options)
        if not uses_native(options):
            raise ValueError('native mode requires HHW001 MJPEG640x480/30')
        self.report = Path(report)
        self.appsrc = appsrc
        self.Gst = Gst
        self.error = None
        self.count = 0
        self.first_pts = self.last_pts = None
        self.stopping = False
        self.process = subprocess.Popen(
            native_argv(Path(__file__).with_name('native_capture'), options, self.report),
            stdout=subprocess.PIPE, stderr=None)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while True:
                stamp, size = struct.unpack('<QI', read_exact(self.process.stdout, 12))
                if not 1 <= size <= 153600:
                    raise RuntimeError('invalid native JPEG length')
                data = read_exact(self.process.stdout, size)
                if self.first_pts is None:
                    self.first_pts = stamp
                if self.last_pts is not None and stamp <= self.last_pts:
                    raise RuntimeError('nonmonotonic native timestamp')
                buffer = self.Gst.Buffer.new_allocate(None, size, None)
                buffer.fill(0, data)
                buffer.pts = stamp-self.first_pts
                buffer.dts = self.Gst.CLOCK_TIME_NONE
                buffer.duration = self.Gst.CLOCK_TIME_NONE
                if self.appsrc.emit('push-buffer', buffer) != self.Gst.FlowReturn.OK:
                    if self.stopping:
                        break
                    raise RuntimeError('native mux rejected a buffer')
                self.last_pts = stamp
                self.count += 1
        except EOFError:
            pass
        except Exception as error:
            self.error = str(error)
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
        finally:
            self.appsrc.emit('end-of-stream')

    def stop(self, allow_preview_drop=False):
        self.stopping = True
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError('native source did not drain; restoration unconfirmed')
        self.process.wait(timeout=5)
        self.process.stdout.close()
        report = json.loads(self.report.read_text())
        if not report['restoration']['verified']:
            raise RuntimeError('native camera controls were not restored')
        if self.process.returncode or self.error or (not allow_preview_drop and report['buffers'] != self.count):
            raise RuntimeError(self.error or 'native producer failed or frame count differs')
        return report
