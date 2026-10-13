"""Native V4L2 acquisition with unchanged segmented Matroska recording."""
import json
from pathlib import Path
import signal
import sys
import time

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from .core import CaptureOptions
from .native_source import NativeSource


def main():
    options = CaptureOptions(**json.loads(sys.argv[1]))
    session = Path(sys.argv[2])
    Gst.init(None)
    source = Gst.ElementFactory.make('appsrc', 'camera')
    source.set_property('is-live', True)
    source.set_property('format', Gst.Format.TIME)
    source.set_property('block', True)
    source.set_property('max-bytes', 1048576)
    source.set_property('caps', Gst.Caps.from_string(
        'image/jpeg,parsed=true,width=640,height=480,framerate=30/1'))
    queue = Gst.ElementFactory.make('queue')
    queue.set_property('max-size-buffers', 256)
    queue.set_property('max-size-bytes', 33554432)
    queue.set_property('max-size-time', 0)
    sink = Gst.ElementFactory.make('splitmuxsink')
    sink.set_property('location', str(session/'segments/part_%05d.mkv'))
    sink.set_property('max-size-time', options.segment_seconds*1000000000)
    sink.set_property('muxer-factory', 'matroskamux')
    sink.set_property('async-finalize', True)
    sink.set_property('muxer-properties', Gst.Structure.new_from_string(
        'properties,timecodescale=(gint64)1000'))
    pipeline = Gst.Pipeline.new(None)
    for element in (source, queue, sink):
        pipeline.add(element)
    if not source.link(queue) or not queue.link(sink):
        raise RuntimeError('native recording pipeline failed to link')
    stopping = False
    def request_stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    native = None
    error = None
    try:
        pipeline.set_state(Gst.State.PLAYING)
        native = NativeSource(options, source, session/'native_capture.json', Gst)
        bus = pipeline.get_bus()
        reported = time.monotonic()
        while True:
            if stopping and native.process.poll() is None:
                native.process.send_signal(signal.SIGINT)
            msg = bus.timed_pop_filtered(100000000, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if time.monotonic()-reported >= 5:
                print(json.dumps({'native_frames': native.count}), flush=True)
                reported = time.monotonic()
            if msg:
                if msg.type == Gst.MessageType.ERROR:
                    error = str(msg.parse_error()[0])
                break
        if error:
            pipeline.set_state(Gst.State.NULL)
        native.stop()
        if error:
            raise RuntimeError(error)
    finally:
        if native and native.process.poll() is None:
            pipeline.set_state(Gst.State.NULL)
            native.stop()
        pipeline.set_state(Gst.State.NULL)


if __name__ == '__main__':
    main()
