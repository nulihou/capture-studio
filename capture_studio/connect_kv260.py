"""Open the existing desktop platform with an authenticated local SSH connection.

Connecting copies the current board package to the KV260 and restarts its
agent when the files differ. An in-progress recording is left running.
Credentials travel over SSH and stay in process memory, never in a report.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

REPO = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
        else Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(REPO))
from capture_studio.desktop import BoardClient, CaptureDesktop


def open_connection(args):
    ssh = shutil.which('ssh')
    if not ssh or not args.ssh_key.is_file():
        raise RuntimeError('OpenSSH and the configured KV260 SSH key are required')
    ssh_args = [ssh, '-i', str(args.ssh_key), '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=accept-new',
                '-o', 'ConnectTimeout=10', f'{args.user}@{args.host}']
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    from capture_studio.board_sync import authentication_failed, install_authorized_key, sync_board_package
    try:
        setup = sync_board_package(ssh_args, args.board_root)
    except RuntimeError as error:
        password = getattr(args, 'password', '') or ''
        if not authentication_failed(str(error)):
            raise
        if not password:
            raise RuntimeError('这台电脑的公钥还没有装到这块开发板上。新板第一次请在连接窗口填写登录密码，软件会把公钥装上；密码不会保存。') from error
        install_authorized_key(ssh, args.ssh_key, args.user, args.host, password)
        setup = sync_board_package(ssh_args, args.board_root)
    token = setup['token']
    from capture_studio.board_devices import select_usb_image_device, selection_note
    args.device = select_usb_image_device(setup['cameras'], args.device, args.camera_serial)
    note = selection_note(setup['cameras'], args.device, args.camera_serial)
    url = f'http://127.0.0.1:{args.local_port}'
    client = BoardClient(url, token)
    owned_tunnel = None
    with socket.socket() as sock:
        sock.settimeout(0.5)
        listening = sock.connect_ex(('127.0.0.1', args.local_port)) == 0
    if not listening:
        owned_tunnel = subprocess.Popen(
            ssh_args[:-1] + ['-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
                            '-o', 'ServerAliveCountMax=3', '-N', '-L',
                            f'127.0.0.1:{args.local_port}:127.0.0.1:8765', ssh_args[-1]],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        for attempt in range(20):
            try:
                status = client.request('GET', '/status', timeout=3)
                break
            except RuntimeError:
                if owned_tunnel is None or owned_tunnel.poll() is not None or attempt == 19:
                    raise
                time.sleep(0.25)
        devices = client.request('GET', '/devices')['devices']
        if args.device not in devices:
            raise RuntimeError(f'Configured video node unavailable: {args.device}; nodes={devices}')
        return {'client': client, 'url': url, 'token': token, 'device': args.device,
                'devices': devices, 'status': status, 'tunnel': owned_tunnel,
                'selection_note': note, 'sync_note': setup.get('sync_note', '')}
    except BaseException:
        if owned_tunnel is not None:
            owned_tunnel.terminate()
            owned_tunnel.wait(timeout=10)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='')
    parser.add_argument('--user', default='ubuntu')
    parser.add_argument('--ssh-key', type=Path, default=Path.home() / '.ssh/id_ed25519_kv260')
    parser.add_argument('--board-root', default='/home/ubuntu/capture_studio')
    parser.add_argument('--local-port', type=int, default=38765)
    parser.add_argument('--device', help='Explicit image node override; otherwise resolve camera serial')
    parser.add_argument('--camera-serial', default='')
    parser.add_argument('--output-root', type=Path, default=REPO / ('captures' if getattr(sys, 'frozen', False) else 'capture_studio/captures'))
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--ui-state-file', type=Path)
    args = parser.parse_args()
    args.password = getattr(main, 'password', '') or ''
    main.password = ''
    if not args.host:
        raise SystemExit('请填写新开发板的 IP 或主机名。')
    connection = open_connection(args)
    owned_tunnel = connection['tunnel']
    url, token = connection['url'], connection['token']
    try:
        if args.check_only:
            print('Connected; device=' + connection['device'], flush=True)
            return
        app = CaptureDesktop()
        app.board_url.set(url)
        app.board_token.set(token)
        app.board_device.set(args.device)
        app.board_width.set('640')
        app.board_height.set('480')
        app.board_fps.set('30')
        app.board_format.set('mjpeg')
        app.output_var.set(str(args.output_root.resolve()))
        for name in ('ffmpeg', 'ffprobe'):
            tool_root = REPO / 'bin' if getattr(sys, 'frozen', False) else REPO / 'capture_studio/dist/CaptureStudio/bin'
            getattr(app, f'{name}_var').set(str(tool_root / f'{name}.exe'))
        app.board_tab.master.select(app.board_tab)

        def connect_when_idle():
            if app.working:
                app.after(500, connect_when_idle)
            else:
                app._board_status()

        app.after(800, connect_when_idle)
        last_refresh = time.monotonic()

        def refresh_state():
            nonlocal last_refresh
            if args.ui_state_file:
                args.ui_state_file.parent.mkdir(parents=True, exist_ok=True)
                args.ui_state_file.write_text(json.dumps({
                    'title': app.title(), 'board_connected': app._board_connected,
                    'board_url': app.board_url.get(), 'selected_node': app.board_device.get(),
                    'listed_video_nodes': app._board_devices,
                    'active_session_id': app.board_session_id,
                    'metrics': app.board_metrics_var.get(), 'output_root': app.output_var.get(),
                }, indent=2, ensure_ascii=False), encoding='utf-8')
            if time.monotonic() - last_refresh >= 30 and not app.working:
                app._board_status()
                last_refresh = time.monotonic()
            app.after(5000, refresh_state)

        app.after(5000, refresh_state)
        app.mainloop()
    finally:
        if owned_tunnel is not None:
            # Closing the GUI disconnects its tunnel, but never stops a board
            # recording. Reopen this launcher to reconnect and stop/fetch it.
            owned_tunnel.terminate()
            owned_tunnel.wait(timeout=10)


if __name__ == '__main__':
    main()
