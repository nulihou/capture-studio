"""Discover USB image nodes from sysfs, without querying camera controls."""
import socket
from pathlib import Path


def usb_image_devices(sys_root: Path = Path('/sys/class/video4linux'),
                      dev_root: Path = Path('/dev')) -> list[dict[str, str]]:
    result = []
    for entry in sorted(sys_root.glob('video[0-9]*')):
        # UVC exposes the image interface at index 0 and a metadata node at 1.
        # Keep this discovery scoped to USB cameras; do not guess CSI formats.
        try:
            if (entry / 'index').read_text().strip() != '0':
                continue
            interface = (entry / 'device').resolve()
            usb = next((p for p in (interface, *interface.parents)
                        if (p / 'idVendor').is_file() and (p / 'idProduct').is_file()), None)
            if usb is None:
                continue
            def text(name: str) -> str:
                path = usb / name
                return path.read_text().strip() if path.is_file() else ''

            result.append({'device': str(dev_root / entry.name),
                           'name': (entry / 'name').read_text().strip(),
                           'vid': (usb / 'idVendor').read_text().strip(),
                           'pid': (usb / 'idProduct').read_text().strip(),
                           'serial': text('serial'),
                           'usb_path': usb.name,
                           'speed': text('speed'),
                           'manufacturer': text('manufacturer'),
                           'product': text('product')})
        except (OSError, ValueError):
            # A node can disappear during unplug; never return a stale guess.
            continue
    return result


def select_usb_image_device(devices: list[dict[str, str]], requested: str | None,
                            serial: str) -> str:
    if requested:
        matches = [d for d in devices if d['device'] == requested]
    else:
        matches = [d for d in devices if serial and d.get('serial') == serial]
        # Another computer may have one camera whose serial is not the saved one.
        # Do not guess when several image nodes are present.
        if len(matches) != 1 and len(devices) == 1:
            return devices[0]['device']
    if len(matches) != 1:
        found = ', '.join(f"{d.get('device', '?')} serial={d.get('serial') or 'none'}"
                          for d in devices) or 'none'
        raise RuntimeError(f'Expected one USB image node; found {len(matches)} for '
                           f'{requested or ("serial=" + serial)}. Nodes: {found}.')
    return matches[0]['device']


def board_facts(model_path: Path = Path('/proc/device-tree/model'),
                hostname: str | None = None) -> dict[str, str]:
    """Board identity that does not open a camera. Missing device-tree is normal off-target."""
    model = ''
    try:
        if model_path.is_file():
            model = model_path.read_bytes().split(b'\x00', 1)[0].decode('utf-8', 'replace').strip()
    except OSError:
        model = ''
    return {'model': model,
            'hostname': socket.gethostname() if hostname is None else hostname}


def selection_note(devices: list[dict[str, str]], selected: str, serial: str) -> str:
    chosen = next((item for item in devices if item.get('device') == selected), None)
    if chosen is None or (serial and chosen.get('serial') == serial):
        return ''
    label = chosen.get('serial') or '无'
    return f'未找到序号 {serial or "（未填）"}，已选用唯一的 USB 摄像头 {selected}（序号 {label}）'
