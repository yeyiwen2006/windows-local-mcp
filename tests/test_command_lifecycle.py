"""Abnormal lifecycle regressions against real Windows processes, in temporary data only."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from windows_local_mcp.commands import Commands, WindowsProcess
from windows_local_mcp.guard import Guard

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Real Windows lifecycle regression')


@pytest.fixture
def runner(tmp_path):
    guard = Guard(tmp_path / 'state')
    (guard.state / 'COMMANDS_ENABLED').write_text('isolated test opt-in\n')
    manager = Commands(guard)
    try:
        yield manager
    finally:
        manager.close()
        guard.close()


def launch(runner, tmp_path, code):
    return runner.start(sys.executable, ['-B', '-c', code], str(tmp_path), timeout_seconds=20)


def finished(runner, started):
    result = runner.poll(started['job_id'], wait_seconds=10)
    assert result['state'] != 'running', result
    return result


def test_stdin_is_closed_not_an_interactive_prompt(runner, tmp_path):
    result = finished(runner, launch(runner, tmp_path, "import sys;assert sys.stdin.read()=='';print('eof')"))
    assert result['success'] and result['stdout']['text'].strip() == 'eof'


def test_failed_final_audit_is_not_reported_as_success(runner, tmp_path, monkeypatch):
    original = runner.guard.audit
    def audit(record):
        if record.get('tool') == 'command_job' and record.get('result') != 'starting':
            raise OSError('synthetic final audit failure')
        original(record)
    monkeypatch.setattr(runner.guard, 'audit', audit)
    result = finished(runner, launch(runner, tmp_path, 'pass'))
    assert result['state'] == 'failed' and result['error_type'] == 'AuditWriteError'
    assert not result['success']


def test_pause_disk_failure_still_stops_running_jobs(runner, tmp_path, monkeypatch):
    job = launch(runner, tmp_path, 'import time;time.sleep(30)')
    original = Path.write_text
    def write(path, *args, **kwargs):
        if path == runner.guard.paused_file:
            raise OSError('synthetic pause disk failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', write)
    with pytest.raises(OSError):
        runner.guard.pause()
    tracked = runner._lookup(job['job_id'])
    assert tracked.done.wait(5)
    assert tracked.snapshot()['state'] == 'paused'
    with pytest.raises(PermissionError):
        launch(runner, tmp_path, 'pass')


def test_watchdog_thread_start_failure_kills_suspended_process(runner, tmp_path, monkeypatch):
    marker = tmp_path / 'must-not-execute'
    original = threading.Thread.start
    def start(thread):
        if thread.name.startswith('command-'):
            raise RuntimeError('synthetic watchdog start failure')
        return original(thread)
    monkeypatch.setattr(threading.Thread, 'start', start)
    with pytest.raises(RuntimeError):
        launch(runner, tmp_path, f'from pathlib import Path;Path({str(marker)!r}).touch()')
    assert not runner.jobs and not marker.exists()


def test_reader_thread_start_failure_kills_suspended_process(runner, tmp_path, monkeypatch):
    marker = tmp_path / 'must-not-execute'
    original = threading.Thread.start
    def start(thread):
        if getattr(getattr(thread, '_target', None), '__name__', '') == 'drain':
            raise RuntimeError('synthetic reader start failure')
        return original(thread)
    monkeypatch.setattr(threading.Thread, 'start', start)
    result = finished(runner, launch(runner, tmp_path, f'from pathlib import Path;Path({str(marker)!r}).touch()'))
    assert result['state'] == 'failed' and not marker.exists()


def test_resume_failure_kills_suspended_process(runner, tmp_path, monkeypatch):
    marker = tmp_path / 'must-not-execute'
    def resume(_process):
        raise OSError('synthetic resume failure')
    monkeypatch.setattr(WindowsProcess, 'resume', resume)
    result = finished(runner, launch(runner, tmp_path, f'from pathlib import Path;Path({str(marker)!r}).touch()'))
    assert result['state'] == 'failed' and not marker.exists()


def test_abrupt_executor_death_kills_root_and_grandchild(tmp_path):
    ready, orphan = tmp_path / 'grandchild-ready', tmp_path / 'orphan-must-not-survive'
    grandchild = (f'from pathlib import Path;import time;Path({str(ready)!r}).touch();'
                  f'time.sleep(2.5);Path({str(orphan)!r}).touch();time.sleep(30)')
    parent = f'import subprocess,sys,time;subprocess.Popen([sys.executable,"-B","-c",{grandchild!r}]);time.sleep(30)'
    host = ('from pathlib import Path;import sys,time;from windows_local_mcp.guard import Guard;'
            'from windows_local_mcp.commands import Commands;'
            f'g=Guard(Path({str(tmp_path / "crash-state")!r}));'
            '(g.state/"COMMANDS_ENABLED").write_text("isolated crash test");'
            f'c=Commands(g);c.start(sys.executable,["-B","-c",{parent!r}],{str(tmp_path)!r});time.sleep(30)')
    process = subprocess.Popen([sys.executable, '-B', '-c', host], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None, 'Isolated executor exited before launching its tree'
            time.sleep(0.01)
        assert ready.exists(), 'Grandchild did not start'
        process.kill()  # Real abrupt executor death: its finally blocks cannot run.
        process.wait(timeout=5)
        time.sleep(3)
        assert not orphan.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_local_opt_in_requires_explicit_acknowledgement(tmp_path):
    state = tmp_path / 'local-control-state'
    env = dict(os.environ, WINDOWS_LOCAL_MCP_STATE=str(state))
    args = [sys.executable, '-B', '-m', 'windows_local_mcp.control', 'commands-enable']
    result = subprocess.run(args, env=env, capture_output=True, timeout=10)
    assert result.returncode != 0 and not (state / 'COMMANDS_ENABLED').exists()
    result = subprocess.run([*args, '--acknowledge-current-user-access'], env=env, capture_output=True, timeout=10)
    assert result.returncode == 0 and (state / 'COMMANDS_ENABLED').exists()
    result = subprocess.run([sys.executable, '-B', '-m', 'windows_local_mcp.control', 'commands-disable'],
                            env=env, capture_output=True, timeout=10)
    assert result.returncode == 0 and not (state / 'COMMANDS_ENABLED').exists()
