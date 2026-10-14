import io
import struct
import unittest
from capture_studio.live_preview import PREVIEW_PNG_LIMIT, read_png


class PreviewFramingTests(unittest.TestCase):
    def test_concatenated_frames_remain_separate(self):
        frame = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 0) + b'IEND' + b'\0'*4
        stream = io.BytesIO(frame+frame)
        self.assertEqual(read_png(stream), frame)
        self.assertEqual(read_png(stream), frame)

    def test_truncated_chunk_is_rejected(self):
        with self.assertRaises(EOFError):
            read_png(io.BytesIO(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',10)+b'IDAT'+b'abc'))

    def test_oversized_chunk_is_rejected_before_read(self):
        with self.assertRaises(ValueError):
            read_png(io.BytesIO(b'\x89PNG\r\n\x1a\n'+struct.pack('>I', PREVIEW_PNG_LIMIT + 1)+b'IDAT'))
