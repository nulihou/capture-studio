"""Editable per-PC SSH connection settings for the portable application."""
import json
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading

from .board_discover import ensure_ssh_key, find_board
from .desktop import app_root
from .desktop_ui import BG, _styles


def resolve_connection_key(saved: str, home: Path) -> str:
    """Use a key that exists on this computer. A path copied from another PC is ignored."""
    if saved:
        path = Path(saved)
        if path.is_file() and not path.name.endswith('.pub'):
            return str(path)
    fallback = home / '.ssh' / 'id_ed25519_kv260'
    return str(fallback) if fallback.is_file() else ''


FRESH_BOARD = {'host': '', 'user': 'ubuntu', 'key': '',
               'board_root': '/home/ubuntu/capture_studio', 'serial': ''}


def connection_settings():
    root = app_root()
    config_file = root/'board_connection.json'
    defaults = dict(FRESH_BOARD)
    if config_file.exists():
        try:
            defaults.update(json.loads(config_file.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            pass
    defaults['key'] = resolve_connection_key(str(defaults.get('key') or ''), Path.home())
    if not defaults['key']:
        try:
            defaults['key'] = str(ensure_ssh_key(Path.home()))
        except (OSError, RuntimeError):
            defaults['key'] = ''
    return defaults


def configure(parent=None, on_connect=None):
    root = app_root()
    config_file = root/'board_connection.json'
    defaults = connection_settings()
    window = tk.Toplevel(parent) if parent is not None else tk.Tk()
    window.title("连接")
    window.geometry("560x420")
    window.configure(background=BG)
    if parent is None:
        _styles(window)
    panel = ttk.Frame(window, padding=(24, 20), style="Card.TFrame")
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(1, weight=1)
    ttk.Label(panel, text="连接开发板", style="CardTitle.TLabel").grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
    find_var = tk.StringVar(value="")
    ttk.Label(panel, textvariable=find_var, style="Hint.TLabel").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
    values = {}
    for row, (name, label) in enumerate([
            ("host", "地址"), ("user", "用户"), ("key", "私钥"),
            ("board_root", "板端目录"), ("serial", "摄像头序号")], 2):
        values[name] = tk.StringVar(value=defaults.get(name, ""))
        ttk.Label(panel, text=label, style="Field.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 16), pady=8)
        ttk.Entry(panel, textvariable=values[name], width=42).grid(row=row, column=1, sticky="ew")
    password = tk.StringVar()
    ttk.Label(panel, text="密码", style="Field.TLabel").grid(
        row=7, column=0, sticky="w", padx=(0, 16), pady=8)
    ttk.Entry(panel, textvariable=password, width=42, show="*").grid(row=7, column=1, sticky="ew")
    def choose():
        path = filedialog.askopenfilename(title='选择SSH私钥（不是.pub公钥）')
        if path: values['key'].set(path)
    ttk.Button(panel, text="选择", command=choose, style="Quiet.TButton").grid(row=4, column=2, padx=(8, 0))
    def search(replace=False):
        find_var.set("正在查找")
        def work():
            try:
                ip, note = find_board()
            except (OSError, RuntimeError) as error:
                ip, note = '', str(error)
            def apply():
                if ip and (replace or not values['host'].get().strip()):
                    values['host'].set(ip)
                find_var.set(note)
            try:
                window.after(0, apply)
            except tk.TclError:
                pass
        threading.Thread(target=work, daemon=True).start()
    ttk.Button(panel, text="查找", command=lambda: search(True), style="Quiet.TButton").grid(
        row=2, column=2, padx=(8, 0))
    selected = {}
    def connect():
        data = {name:value.get().strip() for name,value in values.items()}
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*',data['host']) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',data['user']):
            messagebox.showerror('连接设置','请填写有效主机名/IP和用户名。'); return
        if not Path(data['key']).is_file() or data['key'].endswith('.pub'):
            messagebox.showerror('SSH密钥','请选择这台电脑的SSH私钥，公钥需已添加到开发板。'); return
        if not data['board_root'].startswith('/'):
            messagebox.showerror('连接设置','板端目录需是 Linux 绝对路径。'); return
        config_file.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
        selected.update(data)
        selected['password'] = password.get()
        window.destroy()
        if on_connect is not None:
            on_connect(selected)
    ttk.Button(panel, text="保存并连接", command=connect, style="Primary.TButton").grid(
        row=8, column=1, sticky="e", pady=(16, 0))
    if not defaults.get('host'):
        search()
    if parent is not None:
        window.transient(parent)
        window.grab_set()
        return window
    window.mainloop()
    return selected


def main():
    root = app_root()
    selected = configure()
    if not selected: return
    from .connect_kv260 import main as connect_main
    previous = sys.argv
    sys.argv = [sys.argv[0],'--host',selected['host'],'--user',selected['user'],'--ssh-key',selected['key'],
                '--board-root',selected['board_root'],'--camera-serial',selected.get('serial') or '',
                '--output-root',str(root/'captures')]
    connect_main.password = selected.get('password') or ''
    try:
        connect_main()
    except Exception as error:
        alert = tk.Tk(); alert.withdraw()
        messagebox.showerror('开发板连接失败',str(error)+'\n请确认网络、Windows OpenSSH客户端和密钥授权。',parent=alert)
        alert.destroy()
    finally:
        sys.argv = previous


if __name__ == '__main__':
    main()
