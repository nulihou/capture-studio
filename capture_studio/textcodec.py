"""Decode bytes from the board, ssh, ffmpeg or Windows tools without mojibake.

Board/Linux tools emit UTF-8; Windows console tools (csc, ssh errors, cmd) often emit the
ANSI code page (GBK/cp936 on Chinese Windows). Try strict UTF-8 first, then the local
code page, then GBK, and only then fall back to replacement characters.
"""
from __future__ import annotations

import locale


def safe_decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", locale.getpreferredencoding(False) or "", "gbk"):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")
