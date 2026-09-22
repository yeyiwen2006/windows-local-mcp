"""Real Windows process/stdio regressions. Only synthetic temporary files are used."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from windows_local_mcp.commands import Commands, Output, MAX_RETAINED, MAX_RUNNING
from windows_local_mcp.guard import Guard, PROJECT


def test_output_bounded_unicode_and_offsets():
    output = Output(5)
    output.add("甲乙🙂丙丁戊")
    assert output.read(0, 3) == {"text": "甲乙🙂", "next_offset": 3,
        "captured_chars": 5, "total_chars": 6, "truncated": True}
    assert output.read(3, 10)["text"] == "丙丁"
    with pytest.raises(ValueError):
        output.read(6, 10)


@pytest.fixture
def commands(tmp_path):
    guard = Guard(tmp_path / "state")
    # This is an independent test service, not the installed MCP service.
    (guard.state / "COMMANDS_ENABLED").write_text("enabled for isolated tests\n")
    commands = Commands(guard)
    try:
        yield commands
    finally:
        commands.close()
        guard.close()


WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Real Windows process regression")


def launch(commands, tmp_path, code, **kw):
    return commands.start(sys.executable, ["-B", "-c", code], str(tmp_path),
                          environment={"PYTHONIOENCODING": "utf-8"}, **kw)


def finish(commands, job, timeout=15):
    identifier = job["job_id"]
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = commands.poll(identifier, wait_seconds=1)
        if result["state"] != "running":
            return result
    pytest.fail("Process did not finish")


@WINDOWS
def test_stdout_stderr_unicode_exit_code_and_working_directory(commands, tmp_path):
    script = "import os,sys;print('中文🙂');print(os.getcwd());print('error-marker',file=sys.stderr);sys.exit(7)"
    result = finish(commands, launch(commands, tmp_path, script))
    assert result["state"] == "completed" and result["exit_code"] == 7
    assert result["success"] is False
    assert "中文🙂" in result["stdout"]["text"]
    assert str(tmp_path) in result["stdout"]["text"]
    assert "error-marker" in result["stderr"]["text"]
    second = commands.poll(result["job_id"], stdout_offset=result["stdout"]["next_offset"])
    assert second["stdout"]["text"] == ""


@WINDOWS
def test_arguments_are_not_interpreted_by_an_implicit_shell(commands, tmp_path):
    arguments = ["a b", 'a"b', "& echo NOT_EXECUTED", "中文", "trailing\\"]
    job = commands.start(sys.executable, ["-B", "-c", "import sys,json;print(json.dumps(sys.argv[1:]))", *arguments], str(tmp_path))
    result = finish(commands, job)
    assert result["success"]
    assert json.loads(result["stdout"]["text"]) == arguments


@WINDOWS
def test_cwd_with_unicode_spaces(commands, tmp_path):
    directory = tmp_path / "中文 path with spaces"
    directory.mkdir()
    result = finish(commands, launch(commands, directory, "import os;print(os.getcwd())"))
    assert result["success"] and str(directory) in result["stdout"]["text"]


@WINDOWS
def test_large_both_streams_are_drained_but_retained_output_is_bounded(commands, tmp_path):
    result = finish(commands, launch(commands, tmp_path,
        "import sys;sys.stdout.write('A'*2000000);sys.stderr.write('B'*2000000)", output_limit_chars=1024))
    assert result["success"]
    for stream in ("stdout", "stderr"):
        assert result[stream]["captured_chars"] == 1024
        assert result[stream]["total_chars"] == 2000000
        assert result[stream]["truncated"]


@WINDOWS
def test_timeout_terminates_root_and_child(commands, tmp_path):
    marker = tmp_path / "child-must-not-survive.txt"
    child = f"import time,pathlib;time.sleep(2);pathlib.Path({str(marker)!r}).write_text('bad')"
    parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-B','-c',{child!r}]);print('child-started',flush=True);time.sleep(30)"
    result = finish(commands, launch(commands, tmp_path, parent, timeout_seconds=1))
    assert result["state"] == "timed_out" and not result["success"]
    assert "child-started" in result["stdout"]["text"]
    time.sleep(2.1)
    assert not marker.exists()


@WINDOWS
def test_normal_parent_exit_does_not_leave_descendants(commands, tmp_path):
    marker = tmp_path / "orphan.txt"
    child = f"import time,pathlib;time.sleep(2);pathlib.Path({str(marker)!r}).write_text('bad')"
    parent = f"import subprocess,sys;subprocess.Popen([sys.executable,'-B','-c',{child!r}])"
    result = finish(commands, launch(commands, tmp_path, parent))
    assert result["success"]
    time.sleep(2.1)
    assert not marker.exists()


@WINDOWS
def test_explicit_cancellation_is_idempotent(commands, tmp_path):
    job = launch(commands, tmp_path, "import time;time.sleep(30)")
    assert commands.cancel(job["job_id"])["cancellation_requested"]
    result = finish(commands, job)
    assert result["state"] == "cancelled" and not result["success"]
    assert commands.cancel(job["job_id"])["finished"]


@WINDOWS
def test_local_pause_stops_running_jobs_and_prevents_new_ones(commands, tmp_path):
    job = launch(commands, tmp_path, "import time;time.sleep(30)")
    commands.guard.pause()
    assert commands._lookup(job["job_id"]).done.wait(5)
    assert commands._lookup(job["job_id"]).snapshot()["state"] == "paused"
    assert commands.cancel(job["job_id"])["finished"]
    with pytest.raises(PermissionError):
        commands.poll(job["job_id"])
    with pytest.raises(PermissionError):
        launch(commands, tmp_path, "print('no')")


@WINDOWS
def test_local_permission_revocation_stops_jobs(commands, tmp_path):
    job = launch(commands, tmp_path, "import time;time.sleep(30)")
    commands.enable_file.unlink()
    result = finish(commands, job)
    assert result["state"] == "permission_revoked"
    with pytest.raises(PermissionError):
        launch(commands, tmp_path, "print('no')")


@WINDOWS
def test_service_shutdown_stops_jobs(commands, tmp_path):
    job = launch(commands, tmp_path, "import time;time.sleep(30)")
    commands.close()
    assert commands._lookup(job["job_id"]).done.is_set()
    assert commands.poll(job["job_id"])["state"] == "service_stopped"
    with pytest.raises(RuntimeError, match="closed"):
        launch(commands, tmp_path, "print('no')")


@WINDOWS
def test_concurrency_limit_and_output_does_not_block_start_or_cancel(commands, tmp_path):
    jobs = [launch(commands, tmp_path, "import time;time.sleep(30)") for _ in range(MAX_RUNNING)]
    with pytest.raises(RuntimeError, match="concurrency"):
        launch(commands, tmp_path, "print('no')")
    waiting = threading.Thread(target=lambda: commands.poll(jobs[0]["job_id"], wait_seconds=10))
    waiting.start()
    started = time.monotonic()
    commands.cancel(jobs[0]["job_id"])
    result = finish(commands, jobs[0])
    waiting.join(2)
    assert not waiting.is_alive() and time.monotonic() - started < 3
    assert result["state"] == "cancelled"
    for job in jobs[1:]:
        commands.cancel(job["job_id"])


@WINDOWS
def test_completed_job_retention_is_bounded(commands, tmp_path):
    first = None
    for _ in range(MAX_RETAINED + 1):
        job = launch(commands, tmp_path, "pass")
        first = first or job["job_id"]
        assert finish(commands, job)["success"]
    assert len(commands.jobs) == MAX_RETAINED
    with pytest.raises(ValueError, match="expired"):
        commands.poll(first)


@WINDOWS
def test_runtime_credentials_not_inherited_and_command_content_not_audited(commands, tmp_path, monkeypatch):
    marker = "SYNTHETIC-SENSITIVE-MARKER-123"
    monkeypatch.setenv("OPENAI_API_KEY", marker)
    monkeypatch.setenv("CONTROL_PLANE_API_KEY", marker)
    code = "import os;assert 'OPENAI_API_KEY' not in os.environ;assert 'CONTROL_PLANE_API_KEY' not in os.environ;print('"+marker+"')"
    result = finish(commands, launch(commands, tmp_path, code))
    assert result["success"] and marker in result["stdout"]["text"]
    audit = "".join(p.read_text(encoding="utf-8") for p in (commands.guard.state / "audit").glob("*.jsonl"))
    assert marker not in audit and code not in audit


@WINDOWS
def test_audit_failure_prevents_launch(commands, tmp_path, monkeypatch):
    marker = tmp_path / "not-created"
    def fail(_record):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(commands.guard, "audit", fail)
    with pytest.raises(OSError):
        launch(commands, tmp_path, f"from pathlib import Path;Path({str(marker)!r}).touch()")
    assert not marker.exists() and not commands.jobs


@WINDOWS
def test_startup_failure_leaves_no_active_job(commands, tmp_path):
    invalid = tmp_path / "invalid.exe"
    invalid.write_text("not an executable")
    with pytest.raises(OSError):
        commands.start(str(invalid), [], str(tmp_path))
    assert not commands.jobs


@WINDOWS
def test_disabled_by_default_and_protected_working_directories(tmp_path, commands):
    disabled = Commands(Guard(tmp_path / "disabled-state"))
    assert not disabled.status()["enabled"]
    with pytest.raises(PermissionError, match="disabled"):
        disabled.start(sys.executable, [], str(tmp_path))
    for path in (PROJECT, commands.guard.state):
        with pytest.raises(PermissionError):
            commands.start(sys.executable, [], str(path))
    with pytest.raises(ValueError):
        commands.start("python.exe", [], str(tmp_path))
    with pytest.raises(ValueError):
        commands.start(sys.executable, ["bad\0argument"], str(tmp_path))
    with pytest.raises(ValueError):
        commands.start(sys.executable, [], str(tmp_path), timeout_seconds=True)
    with pytest.raises(ValueError):
        commands.start(sys.executable, [], str(tmp_path), environment={"OPENAI_API_KEY": "no"})


@WINDOWS
def test_git_and_powershell_without_desktop_focus(commands, tmp_path):
    git = shutil.which("git.exe")
    powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    assert git is not None, "Windows validation host must have Git installed"
    result = finish(commands, commands.start(git, ["--version"], str(tmp_path)))
    assert result["success"] and "git version" in result["stdout"]["text"]
    result = finish(commands, commands.start(powershell,
        ["-NoProfile", "-NonInteractive", "-Command", "Write-Output 'command-tool-powershell-ok'; exit 0"], str(tmp_path)))
    assert result["success"] and "command-tool-powershell-ok" in result["stdout"]["text"]


@WINDOWS
def test_real_stdio_protocol_command_execution_poll_cancel_and_pause(tmp_path):
    async def run():
        state = tmp_path / "protocol-state"
        state.mkdir()
        (state / ".windows-local-mcp-state").write_text("windows-local-mcp\n")
        (state / "COMMANDS_ENABLED").write_text("enabled for isolated test\n")
        env = dict(os.environ, WINDOWS_LOCAL_MCP_STATE=str(state), PYTHONIOENCODING="utf-8")
        params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "windows_local_mcp"], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tool_map = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert tool_map["command_start"].annotations.readOnlyHint is False
                assert tool_map["command_start"].annotations.openWorldHint is True
                assert tool_map["command_cancel"].annotations.idempotentHint is True
                start = await session.call_tool("command_start", {"executable": sys.executable,
                    "arguments": ["-B", "-c", "print('real-mcp-command-ok')"], "cwd": str(tmp_path)})
                assert not start.isError, start
                job = json.loads(start.content[0].text)
                result = await session.call_tool("command_poll", {"job_id": job["job_id"], "wait_seconds": 10})
                assert not result.isError
                result = json.loads(result.content[0].text)
                assert result["success"] and "real-mcp-command-ok" in result["stdout"]["text"]
                start = await session.call_tool("command_start", {"executable": sys.executable,
                    "arguments": ["-B", "-c", "import time;time.sleep(30)"], "cwd": str(tmp_path)})
                assert not start.isError
                identifier = json.loads(start.content[0].text)["job_id"]
                assert not (await session.call_tool("service_pause", {})).isError
                assert not (await session.call_tool("command_cancel", {"job_id": identifier})).isError
                status = await session.call_tool("service_status", {})
                assert not status.isError
                assert json.loads(status.content[0].text)["paused"]
                blocked = await session.call_tool("command_start", {"executable": sys.executable,
                    "arguments": [], "cwd": str(tmp_path)})
                assert blocked.isError
    asyncio.run(run())


@WINDOWS
def test_job_assignment_failure_never_runs_the_suspended_process(commands, tmp_path, monkeypatch):
    import win32job
    marker = tmp_path / 'not-executed'
    def fail(*_args):
        raise OSError('synthetic assignment failure')
    monkeypatch.setattr(win32job, 'AssignProcessToJobObject', fail)
    with pytest.raises(OSError):
        launch(commands, tmp_path, f"from pathlib import Path;Path({str(marker)!r}).touch()")
    assert not commands.jobs and not marker.exists()
