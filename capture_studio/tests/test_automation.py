"""Failure-injection tests for attended capture. No camera or board is opened."""
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from capture_studio import product
from capture_studio.automation import download_with_retry, session_result
from capture_studio.gates import ORDER, combine_gates

SID = '20261017T010000Z_00000001'
OTHER = '20261017T010000Z_00000002'


def gates(short=True):
    return combine_gates(*({'status': 'pending' if k == 'frame_rate' and short else 'pass',
                           'detail': k} for k in ORDER))


@pytest.fixture
def studio(tmp_path):
    with patch.object(product.Studio, '_load', return_value={
            'output': str(tmp_path), 'host': 'original', 'board_root': '/captures'}):
        s = product.Studio()
    s._save = Mock()
    s._tool = Mock(return_value=Path('ffprobe.exe'))
    s.stop_live = Mock()
    s._arm = Mock()
    return s


def write_session(root, status='recorded', **extra):
    session = root / SID
    session.mkdir(exist_ok=True)
    manifest = {'session_id': SID, 'status': status, **extra}
    (session / 'session.json').write_text(json.dumps(manifest), encoding='utf-8')
    return session, manifest


def fake_audit(session, tool):
    path = session / 'session.json'
    m = json.loads(path.read_text(encoding='utf-8'))
    m.update(status='audited', gates=gates(), audit={'frame_count': 1800})
    path.write_text(json.dumps(m), encoding='utf-8')
    return {'frame_count': 1800}  # real audit's return contract, not gates


def board(studio, root, *, active=True):
    session, manifest = write_session(root)
    client = Mock()
    client.request.side_effect = lambda method, endpoint, *a, **k: (
        {'recording': active, 'session': {'session_id': SID}} if endpoint == '/status' else manifest)
    client.download_session.return_value = session
    studio.client = client
    studio.recording = {'mode': 'board', 'session_id': SID, 'root': root,
                        'host': 'original', 'board_root': '/captures'}
    return client, session, manifest


def run_job(studio, action):
    done = threading.Event()
    # Wait on the actual worker without patching its error handling.
    real_thread = threading.Thread
    def factory(*args, **kwargs):
        target = kwargs.pop('target')
        def wrapped():
            try:
                target()
            finally:
                done.set()
        return real_thread(*args, target=wrapped, **kwargs)
    with patch.object(product.threading, 'Thread', side_effect=factory):
        action()
        assert done.wait(5)


def test_gate_counters_are_not_gate_results():
    assert not session_result({'audit': {'frame_count': 1800}})['dataset_ready']
    m = {'status': 'audited', 'gates': gates(), 'audit': {'frame_count': 1800}}
    result = session_result(m)
    assert '帧率未测' in result['summary']
    assert not result['dataset_ready']


def test_ready_is_derived_from_all_four_gates():
    m = {'status': 'audited', 'gates': gates()}
    m['gates']['dataset_ready'] = True
    assert not session_result(m)['dataset_ready']
    m['gates'] = gates(short=False)
    assert session_result(m)['dataset_ready']
    m['status'] = 'failed'
    assert not session_result(m)['dataset_ready']


def test_transient_download_bounded_and_checksum_not_retried():
    download = Mock(side_effect=[RuntimeError('connection reset'), OSError('timed out'), 'ok'])
    notify, wait = Mock(), Mock()
    assert download_with_retry(download, notify, wait) == 'ok'
    assert download.call_count == 3 and notify.call_count == 2
    bad = Mock(side_effect=RuntimeError('checksum mismatch'))
    with pytest.raises(RuntimeError, match='checksum'):
        download_with_retry(bad, notify, wait)
    assert bad.call_count == 1
    forever = Mock(side_effect=RuntimeError('timeout'))
    with pytest.raises(RuntimeError):
        download_with_retry(forever, notify, wait)
    assert forever.call_count == 3


def test_pc_stop_audit_uses_persisted_gates(studio, tmp_path):
    session, manifest = write_session(tmp_path)
    recorder = Mock(session=session)
    recorder.stop.return_value = manifest
    studio.recording = {'mode': 'pc', 'session_id': SID}
    studio.local_recorder = recorder
    with patch.object(product, 'audit_session', side_effect=fake_audit):
        studio._complete_recording()
    assert studio.recording is None and studio.completion is None
    assert studio.last_session['audit']['frame_count'] == 1800
    assert not studio.last_session['dataset_ready']
    assert '帧率未测' in studio.gates
    recorder.stop.assert_called_once()


def test_download_failure_resumes_without_second_stop_or_changing_root(studio, tmp_path):
    client, session, manifest = board(studio, tmp_path)
    client.download_session.side_effect = [RuntimeError('checksum mismatch'), session]
    with pytest.raises(RuntimeError, match='checksum'):
        studio._complete_recording()
    assert studio.completion['stage'] == 'downloading' and studio.recording is None
    studio.settings['output'] = str(tmp_path / 'changed')
    with patch.object(product, 'audit_session', side_effect=fake_audit):
        studio._complete_recording()
    assert sum(c.args[:2] == ('POST', '/stop') for c in client.request.call_args_list) == 1
    assert all(c.args[1] == tmp_path for c in client.download_session.call_args_list)


def test_lost_stop_response_queries_session_on_retry(studio, tmp_path):
    client, session, manifest = board(studio, tmp_path)
    requests = [
        {'recording': True, 'session': {'session_id': SID}},
        RuntimeError('timeout'), {'recording': False}, manifest]
    client.request.side_effect = requests
    with pytest.raises(RuntimeError, match='timeout'):
        studio._complete_recording()
    with patch.object(product, 'audit_session', side_effect=fake_audit):
        studio._complete_recording()
    assert [c.args[:2] for c in client.request.call_args_list] == [
        ('GET', '/status'), ('POST', '/stop'), ('GET', '/status'), ('GET', '/sessions/' + SID)]


def test_audit_failure_resumes_local_copy(studio, tmp_path):
    client, session, manifest = board(studio, tmp_path)
    with patch.object(product, 'audit_session', side_effect=RuntimeError('ffprobe failed')):
        with pytest.raises(RuntimeError):
            studio._complete_recording()
    assert studio.completion['stage'] == 'auditing'
    client.request.reset_mock()
    with patch.object(product, 'audit_session', side_effect=fake_audit):
        studio._complete_recording()
    client.request.assert_not_called()
    client.download_session.assert_called_once()


def test_never_stop_other_session_or_other_host(studio, tmp_path):
    client, _, _ = board(studio, tmp_path)
    client.request.return_value = {'recording': True, 'session': {'session_id': OTHER}}
    client.request.side_effect = None
    with pytest.raises(RuntimeError, match='不同'):
        studio._complete_recording()
    assert client.request.call_count == 1
    client.request.reset_mock()
    studio.settings['host'] = 'another'
    with pytest.raises(RuntimeError, match='原开发板'):
        studio._complete_recording()
    client.request.assert_not_called()


def test_duplicate_start_preserves_resume_and_settings(studio, tmp_path):
    studio.completion = {'session_id': SID}
    studio._retry = ('resume', lambda: None)
    previous = studio._retry
    studio.start_record({'output': 'changed', '_output_once': 'changed'}, 'pc')
    assert studio._retry is previous
    assert studio.settings['output'] == str(tmp_path)
    assert studio.output_once is None


@pytest.mark.parametrize('reason', ['missing_tool', 'disk_full'])
def test_preflight_blocks_before_camera(studio, reason):
    if reason == 'missing_tool':
        studio._tool.side_effect = FileNotFoundError('ffprobe missing')
    with patch.object(product.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
        run_job(studio, lambda: studio.start_record({}, 'pc'))
    assert studio.last_error and studio.recording is None
    studio.stop_live.assert_not_called()
    assert studio._retry is None


@pytest.mark.parametrize('reconcile', ['active', 'unreachable', 'rejected'])
def test_start_timeout_never_replays_post(studio, reconcile):
    options = SimpleNamespace(device='/dev/video0', planned_seconds=60)
    studio._options = Mock(return_value=options)
    studio.client = Mock()
    error = RuntimeError('Board returned 400: 画面过暗' if reconcile == 'rejected' else 'timeout')
    status = RuntimeError('timeout') if reconcile == 'unreachable' else {
        'recording': reconcile == 'active', 'session': {'session_id': SID, 'device': '/dev/video0'}}
    studio.client.request.side_effect = [error, status]
    with patch.object(product, 'has_image_tuning', return_value=False):
        run_job(studio, lambda: studio.start_record({}, 'board'))
    assert sum(c.args[:2] == ('POST', '/start') for c in studio.client.request.call_args_list) == 1
    assert studio._retry is None
    if reconcile == 'active':
        assert studio.recording['session_id'] == SID and not studio.start_uncertain
    elif reconcile == 'unreachable':
        assert studio.start_uncertain and studio.recording is None
    else:
        assert not studio.start_uncertain and '画面过暗' in studio.last_error


def test_watcher_waits_past_busy_and_handles_manual_early_exit(studio):
    # 70 busy ticks simulate >30 seconds. No real sleep needed.
    arm = product.Studio._arm.__get__(studio)
    studio.recording = {'session_id': SID}
    studio.local_recorder = Mock()
    studio.local_recorder.status.return_value = {'running': False}
    studio.stop_record = Mock(return_value=True)
    ticks = 0
    def tick(seconds):
        nonlocal ticks
        ticks += 1
        studio.busy = ticks <= 70
        return ticks > 75
    studio._closed = SimpleNamespace(wait=tick)
    with patch.object(product.threading, 'Thread') as thread:
        arm(SID, None)
        thread.call_args.kwargs['target']()
    assert ticks == 71
    studio.stop_record.assert_called_once_with(expected_session_id=SID)


def test_failed_capture_remains_failed_without_audit(studio, tmp_path):
    session, manifest = write_session(tmp_path, 'failed')
    studio.recording = {'mode': 'pc', 'session_id': SID}
    studio.local_recorder = Mock(session=session)
    studio.local_recorder.stop.return_value = manifest
    with patch.object(product, 'audit_session') as audit:
        studio._complete_recording()
    audit.assert_not_called()
    assert not studio.last_session['dataset_ready']
    assert '收尾未过' in studio.gates


def test_state_with_frozen_output_is_json_serializable(studio, tmp_path):
    studio.recording = {'session_id': SID, 'root': tmp_path, 'host': 'original'}
    json.dumps(studio.state())


def test_connect_adopts_active_session_without_reconfiguring_camera(studio, tmp_path):
    key = tmp_path / 'dummy_key'
    key.write_text('test fixture, not an SSH key', encoding='utf-8')
    studio.settings['key'] = str(key)
    studio._detect_board_modes = Mock()
    studio._probe_board = Mock()
    client = Mock()
    client.request.return_value = {'device_info': [], 'board': {}}
    conn = {'client': client, 'tunnel': Mock(), 'device': '/dev/video0',
            'status': {'recording': True, 'session': {'session_id': SID}}}
    with patch.object(product, 'open_connection', return_value=conn), patch.object(product, '_free_port', return_value=9999):
        run_job(studio, lambda: studio.connect({}))
    assert studio.recording['session_id'] == SID and studio.recording['seconds'] is None
    studio._detect_board_modes.assert_not_called()
    assert not studio.start_uncertain


def test_timed_watcher_handles_deadline_and_session_change(studio):
    arm = product.Studio._arm.__get__(studio)
    studio.recording = {'session_id': SID}
    studio.local_recorder = None
    studio.stop_record = Mock(return_value=True)
    studio._closed = SimpleNamespace(wait=Mock(side_effect=[False, False, True]))
    with patch.object(product.threading, 'Thread') as thread, patch.object(product.time, 'monotonic', side_effect=[0, 61]):
        arm(SID, 60)
        thread.call_args.kwargs['target']()
    studio.stop_record.assert_called_once_with(expected_session_id=SID)
    studio.stop_record.reset_mock()
    studio.recording = {'session_id': OTHER}
    with patch.object(product.threading, 'Thread') as thread:
        arm(SID, None)
        thread.call_args.kwargs['target']()
    studio.stop_record.assert_not_called()
