from pathlib import Path
import unittest
from unittest.mock import patch
from capture_studio.board_devices import (board_facts, select_usb_image_device, selection_note,
                                          usb_image_devices)
from test_capture import scratch


class BoardDeviceIdentityTests(unittest.TestCase):
    def test_reenumeration_selects_image_node_by_serial_and_excludes_metadata(self):
        with scratch() as directory:
            root = Path(directory)
            usb = root / '1-1.4'
            interface = usb / 'interface'
            interface.mkdir(parents=True)
            for name, value in {'idVendor': '1c45', 'idProduct': '6200', 'serial': 'HHW001',
                                'speed': '480', 'product': 'USB Camera'}.items():
                (usb / name).write_text(value)
            sys_root = root / 'video'
            # First enumeration: image=video1, metadata=video2. After recovery:
            # image=video0, metadata=video1. Do not rely on old integer IDs.
            for image_id, metadata_id in [('video1', 'video2'), ('video0', 'video1')]:
                for entry in sys_root.glob('*'):
                    (entry / 'device').rmdir()
                    (entry / 'index').unlink()
                    (entry / 'name').unlink()
                    entry.rmdir()
                for name, index in [(image_id, '0'), (metadata_id, '1')]:
                    entry = sys_root / name
                    entry.mkdir(parents=True)
                    (entry / 'device').mkdir()
                    (entry / 'index').write_text(index)
                    (entry / 'name').write_text('USB Camera')
                # Windows test accounts need not have symlink privileges. Model
                # the sysfs link resolution while keeping enumeration on disk.
                original_resolve = Path.resolve
                def resolve_sysfs(path, *args, **kwargs):
                    return interface if path.name == 'device' and path.parent.parent == sys_root else original_resolve(path, *args, **kwargs)
                with patch.object(Path, 'resolve', resolve_sysfs):
                    devices = usb_image_devices(sys_root, root / 'dev')
                self.assertEqual([str(root / 'dev' / image_id)], [d['device'] for d in devices])
                self.assertEqual('480', devices[0]['speed'])
                self.assertEqual('USB Camera', devices[0]['product'])
                self.assertEqual(str(root / 'dev' / image_id), select_usb_image_device(devices, None, 'HHW001'))
                with self.assertRaises(RuntimeError):
                    select_usb_image_device(devices, str(root / 'dev' / metadata_id), 'HHW001')

    def test_missing_or_ambiguous_serial_requires_explicit_selection(self):
        devices = [{'device': '/dev/video0', 'serial': 'HHW001'},
                   {'device': '/dev/video2', 'serial': 'HHW001'}]
        with self.assertRaises(RuntimeError):
            select_usb_image_device(devices, None, 'HHW001')
        with self.assertRaises(RuntimeError):
            select_usb_image_device(devices, None, 'missing')
        self.assertEqual('/dev/video2', select_usb_image_device(devices, '/dev/video2', 'HHW001'))

    def test_one_camera_is_used_when_the_saved_serial_does_not_match(self):
        devices = [{'device': '/dev/video3', 'serial': 'CAM9'}]
        self.assertEqual('/dev/video3', select_usb_image_device(devices, None, 'HHW001'))
        self.assertIn('CAM9', selection_note(devices, '/dev/video3', 'HHW001'))
        self.assertEqual('', selection_note(devices, '/dev/video3', 'CAM9'))

    def test_several_cameras_are_not_guessed_when_the_serial_is_absent(self):
        devices = [{'device': '/dev/video0', 'serial': 'A'},
                   {'device': '/dev/video2', 'serial': 'B'}]
        with self.assertRaises(RuntimeError):
            select_usb_image_device(devices, None, 'HHW001')

    def test_board_facts_read_model_without_a_camera(self):
        with scratch() as directory:
            model = Path(directory) / 'model'
            model.write_bytes(b'Zynq UltraScale+ MPSoC\x00extra')
            facts = board_facts(model, hostname='kria')
        self.assertEqual('Zynq UltraScale+ MPSoC', facts['model'])
        self.assertEqual('kria', facts['hostname'])
