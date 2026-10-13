import io
import json
import struct
from pathlib import Path
import unittest
from unittest.mock import patch

from capture_studio.core import CaptureOptions, ProcessRecorder, new_session
from capture_studio.native_source import NativeSource, read_exact, uses_native
from test_capture import scratch


class NativeContractTests(unittest.TestCase):
    def test_source_preserves_irregular_pts_without_fabricating_duration(self):
        from types import SimpleNamespace
        pushed = []
        class Buffer:
            @staticmethod
            def new_allocate(*_):
                return Buffer()
            def fill(self, _, data):
                self.data = data
        class Sink:
            def emit(self, event, *args):
                if event == 'push-buffer':
                    pushed.append(args[0])
                return 0
        camera = NativeSource.__new__(NativeSource)
        camera.Gst = SimpleNamespace(Buffer=Buffer, CLOCK_TIME_NONE=-1,
                                     FlowReturn=SimpleNamespace(OK=0))
        camera.appsrc = Sink()
        camera.process = SimpleNamespace(stdout=io.BytesIO(
            struct.pack('<QI', 1000000000, 3)+b'one'+
            struct.pack('<QI', 1035951000, 3)+b'two'))
        camera.first_pts = camera.last_pts = None
        camera.error = None
        camera.count = 0
        camera.stopping = False
        camera._read()
        self.assertIsNone(camera.error)
        self.assertEqual([b'one', b'two'], [x.data for x in pushed])
        self.assertEqual([0, 35951000], [x.pts for x in pushed])
        self.assertTrue(all(x.dts == -1 and x.duration == -1 for x in pushed))
        self.assertEqual(camera.count, 2)

    def test_partial_packet_is_rejected(self):
        with self.assertRaises(RuntimeError):
            read_exact(io.BytesIO(b'abc'), 4)
        with self.assertRaises(EOFError):
            read_exact(io.BytesIO(), 4)

    def test_native_selection_requires_exact_camera_and_mode(self):
        options = CaptureOptions('/dev/video0', width=640, height=480,
                                 source_format='mjpeg', codec='copy')
        info = dict(device='/dev/video0', vid='1c45', pid='6200', serial='HHW001')
        with patch('capture_studio.native_source.usb_image_devices', return_value=[info]):
            self.assertTrue(uses_native(options))
            self.assertFalse(uses_native(CaptureOptions('/dev/video0', source_format='mjpeg', codec='copy')))
        with patch('capture_studio.native_source.usb_image_devices', return_value=[dict(info, serial='other')]):
            self.assertFalse(uses_native(options))
        tuned = CaptureOptions('/dev/video0', width=640, height=480, source_format='mjpeg',
                               codec='copy', gain=8)
        with patch('capture_studio.native_source.usb_image_devices', return_value=[info]):
            self.assertFalse(uses_native(tuned))

    def test_failed_control_restoration_fails_recording(self):
        class Process:
            returncode = 0
            stdin = None
            def poll(self):
                return 0
        with scratch() as directory:
            session = new_session(Path(directory), 'kv260_usb',
                                  CaptureOptions('/dev/video0', source_format='mjpeg', codec='copy'))
            (session/'segments/part_00000.mkv').write_bytes(b'media')
            report = dict(status='complete', buffers=2, whole_window_hz=30,
                          invalid_kernel_timestamps=0, duplicate_timestamps=0,
                          backward_timestamps=0, restoration={'verified': False})
            (session/'native_capture.json').write_text(json.dumps(report))
            recorder = ProcessRecorder(session, [], 'gst')
            recorder.process = Process()
            result = recorder.stop()
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['native_capture']['restoration']['verified'])
