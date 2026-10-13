"""Board-only GStreamer preview worker with source-pad arrival telemetry."""
import json
import signal
import sys
import tempfile
from pathlib import Path
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
from .frame_rates import FrameRates
from .core import CaptureOptions
from .native_source import NativeSource, uses_native
from .camera_lab import preview_frame_size, v4l2_source_launch


def main():
    options = json.loads(sys.argv[1])
    Gst.init(None)
    rates = FrameRates()
    caps = (f'image/jpeg,width={options["width"]},height={options["height"]},framerate={options["fps"]}/1'
            if options['source_format'] == 'mjpeg' else
            f'video/x-raw,width={options["width"]},height={options["height"]},framerate={options["fps"]}/1')
    decode = 'jpegdec ! ' if options['source_format'] == 'mjpeg' else ''
    native_options = CaptureOptions(**options)
    native_mode = uses_native(native_options)
    camera = ('appsrc name=camera is-live=true format=time block=true max-bytes=1048576 ! '
              if native_mode else
              v4l2_source_launch(native_options))
    # Limit preview work before decoding; the source probe still counts every
    # delivered buffer. This queue belongs only to preview, never recording.
    preview_caps = ('image/jpeg' if options['source_format'] == 'mjpeg' else 'video/x-raw')
    preview_width, preview_height = preview_frame_size(options["width"], options["height"])
    pipeline = Gst.parse_launch(
        camera + f'{caps} ! '
        'queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream ! '
        f'videorate drop-only=true ! {preview_caps},framerate={min(options["fps"], 30)}/1 ! '
        + decode +
        'videoconvert ! videoscale ! '
        f'video/x-raw,width={preview_width},height={preview_height} ! pngenc compression-level=1 ! '
        'appsink name=images emit-signals=true sync=false max-buffers=1 drop=true')
    loop = GLib.MainLoop()
    def source_buffer(pad, info):
        rates.tick()
        return Gst.PadProbeReturn.OK
    pipeline.get_by_name('camera').get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, source_buffer)
    def sample(sink):
        value = sink.emit('pull-sample')
        buffer = value.get_buffer()
        success, mapping = buffer.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR
        try:
            sys.stdout.buffer.write(mapping.data)
            sys.stdout.buffer.flush()
            rates.tick(source=False)
        except BrokenPipeError:
            loop.quit()
            return Gst.FlowReturn.ERROR
        finally:
            buffer.unmap(mapping)
        return Gst.FlowReturn.OK
    pipeline.get_by_name('images').connect('new-sample', sample)
    def report():
        print(json.dumps(rates.status()), file=sys.stderr, flush=True)
        return True
    def message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            error, _ = msg.parse_error()
            print(json.dumps({'error': str(error)}), file=sys.stderr, flush=True)
            loop.quit()
        elif msg.type == Gst.MessageType.EOS:
            loop.quit()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect('message', message)
    GLib.timeout_add_seconds(1, report)
    signal.signal(signal.SIGINT, lambda *_: loop.quit())
    signal.signal(signal.SIGTERM, lambda *_: loop.quit())
    native = None
    work = tempfile.TemporaryDirectory(prefix='capture_preview_') if native_mode else None
    try:
        pipeline.set_state(Gst.State.PLAYING)
        if native_mode:
            native = NativeSource(native_options, pipeline.get_by_name('camera'),
                                  Path(work.name)/'native_capture.json', Gst)
        loop.run()
    finally:
        if native:
            native.stop(allow_preview_drop=True)
        pipeline.set_state(Gst.State.NULL)
        if work:
            work.cleanup()


if __name__ == '__main__':
    main()
