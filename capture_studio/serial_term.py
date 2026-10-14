"""Serial terminal helpers (v7).  Ports are opened only on explicit user action.

Board ports: one ssh process runs `stty` + `cat` on the board; stdout = received bytes, stdin = sent bytes.
PC ports: pyserial.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
from typing import Any, Callable

BAUDS = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1500000)
_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
PORT_RE = re.compile(r"^/dev/tty(USB|ACM|PS|AMA|THS|S)\d+$")


def hexdump(data: bytes, offset: int = 0, width: int = 16) -> str:
    lines = []
    for start in range(0, len(data), width):
        chunk = data[start:start + width]
        hexes = " ".join(f"{b:02X}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset + start:08X}  {hexes:<{width * 3 - 1}}  {text}")
    return "\n".join(lines)


def parse_send(text: str, hex_mode: bool, line_ending: str = "\r\n") -> bytes:
    if hex_mode:
        cleaned = re.sub(r"(0x|[\s,;:])", "", text, flags=re.I)
        if len(cleaned) % 2 or not re.fullmatch(r"[0-9A-Fa-f]*", cleaned):
            raise ValueError("十六进制格式不对，例如：55 AA 01")
        return bytes.fromhex(cleaned)
    return (text + line_ending).encode("utf-8")


def board_command(ssh_args: list[str], port: str, baud: int) -> list[str]:
    if not PORT_RE.match(port) or int(baud) not in BAUDS:
        raise ValueError("串口或波特率无效")
    remote = (f"stty -F {shlex.quote(port)} {int(baud)} raw -echo -echoe -echok cs8 -cstopb -parenb && "
              f"(cat {shlex.quote(port)} & CAT=$!; trap 'kill $CAT' EXIT; cat > {shlex.quote(port)})")
    return list(ssh_args) + [remote]


class Session:
    """Common interface: start(on_data), write(bytes), close()."""

    def __init__(self, opener: Callable[[], Any], kind: str) -> None:
        self._opener, self.kind = opener, kind
        self._handle: Any = None
        self._stop = threading.Event()
        self.error = ""

    def start(self, on_data: Callable[[bytes], None]) -> None:
        self._handle = self._opener()
        threading.Thread(target=self._pump, args=(on_data,), daemon=True).start()

    def _pump(self, on_data: Callable[[bytes], None]) -> None:
        try:
            while not self._stop.is_set():
                if self.kind == "board":
                    chunk = self._handle.stdout.read1(4096) if hasattr(self._handle.stdout, "read1") else self._handle.stdout.read(1)
                else:
                    handle = self._handle
                    if handle is None:
                        break
                    chunk = handle.read(handle.in_waiting or 1)
                if chunk:
                    on_data(bytes(chunk))
                elif self.kind == "board":
                    break
        except Exception as exc:
            if not self._stop.is_set():  # a read interrupted by close() is not an error
                self.error = str(exc)

    def write(self, data: bytes) -> None:
        if self.kind == "board":
            self._handle.stdin.write(data)
            self._handle.stdin.flush()
        else:
            self._handle.write(data)

    def close(self) -> None:
        self._stop.set()
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if self.kind == "board":
                handle.terminate()
            else:
                handle.close()
        except Exception:
            pass


def open_board(ssh_args: list[str], port: str, baud: int, popen: Callable[..., Any] = subprocess.Popen) -> Session:
    command = board_command(ssh_args, port, baud)
    return Session(lambda: popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, creationflags=_FLAGS), "board")


def open_pc(port: str, baud: int, serial_factory: Any = None) -> Session:
    def opener() -> Any:
        factory = serial_factory
        if factory is None:
            import serial
            factory = serial.Serial
        return factory(port, int(baud), timeout=0.2)
    return Session(opener, "pc")
