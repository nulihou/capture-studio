"""Bounded, attended capture decisions; never invent device or quality evidence."""
from __future__ import annotations

from typing import Any, Callable
import time

from .gates import ORDER, _result, combine_gates, format_gates, incomplete_gates


def session_result(manifest: dict[str, Any]) -> dict[str, Any]:
    """Read persisted gates, not audit counters. Missing evidence stays pending."""
    gates = manifest.get('gates')
    if not isinstance(gates, dict) or any(not isinstance(gates.get(key), dict) or
            gates[key].get('status') not in ('pass', 'fail', 'pending') for key in ORDER):
        gates = incomplete_gates(_result('pending', '尚无收尾核验结果'))
    else:
        gates = combine_gates(*(gates[key] for key in ORDER))
    if manifest.get('status') == 'failed':
        gates = incomplete_gates(_result('fail', '录制失败，请保留日志并检查设备'))
    return {'session_id': manifest.get('session_id', ''), 'status': manifest.get('status', ''),
            'gates': gates, 'dataset_ready': gates.get('dataset_ready') is True,
            'summary': format_gates(gates), 'audit': manifest.get('audit') or {}}


def transient_transfer_error(exc: Exception) -> bool:
    text = str(exc).lower()
    # An authentication, integrity or contract error needs operator action.
    if any(x in text for x in ('checksum', 'sha256', 'unauthorized', 'forbidden', '401', '403',
                                'unsafe', 'invalid session', 'hash mismatch', 'permission')):
        return False
    return any(x in text for x in ('timed out', 'timeout', 'reset', 'refused', 'disconnected',
                                   'remote end closed', 'incomplete read', 'incompleteread',
                                   'connection aborted', '10054', '10061', '10060'))


def download_with_retry(download: Callable[[], Any], notify: Callable[[str], None],
                        wait: Callable[[float], Any] = time.sleep) -> Any:
    """At most three read-only download attempts. Never retry start/stop or bad hashes."""
    for attempt in range(3):
        try:
            return download()
        except (RuntimeError, OSError) as exc:
            if attempt == 2 or not transient_transfer_error(exc):
                raise
            notify(f'取回暂时中断，自动重试 {attempt + 1}/2；已核对文件将复用')
            wait(0.5 * (attempt + 1))


def require_recorded_session(manifest: dict[str, Any], expected_id: str) -> None:
    if manifest.get('session_id') != expected_id:
        raise RuntimeError('会话身份不一致，已停止自动收尾，请重新查询会话')
    if manifest.get('status') not in ('recorded', 'failed', 'audited', 'needs_review'):
        raise RuntimeError('会话尚未确认停止，已保留状态，请重新查询开发板')
