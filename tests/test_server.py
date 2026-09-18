import asyncio
import json
import os
import sys
import time

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from windows_local_mcp.desktop import DesktopError
from windows_local_mcp.guard import Guard
from windows_local_mcp.server import Runtime


def test_observation_is_recent_and_single_use(tmp_path):
    r = Runtime(Guard(tmp_path / "state"))
    class FakeDesktop:
        def __init__(self):
            self.allowed = True
            self.expected_foreground_hwnd = None

        def foreground_window(self):
            return 10

        def validate_input_target(self, hwnd):
            if not self.allowed:
                raise DesktopError("Desktop input is locked to another program")
            assert hwnd == 10
            return {"hwnd": 10, "pid": 100, "title": "Target"}

    fake = FakeDesktop()
    r._desktop = fake
    with pytest.raises(ValueError):
        r.observed_input("missing")
    r.observation = {"id": "ok", "time": time.monotonic(), "foreground_hwnd": 10}
    r.observed_input("ok")
    with pytest.raises(ValueError):
        r.observed_input("ok")
    r.observation = {"id": "old", "time": time.monotonic() - 61, "foreground_hwnd": 10}
    with pytest.raises(ValueError, match="expired"):
        r.observed_input("old")
    fake.allowed = False
    r.observation = {"id": "other-program", "time": time.monotonic(), "foreground_hwnd": 10}
    with pytest.raises(DesktopError, match="locked"):
        r.observed_input("other-program")
    fake.allowed = True
    r.observation = {"id": "changed", "time": time.monotonic(), "foreground_hwnd": 11}
    with pytest.raises(ValueError, match="Foreground"):
        r.observed_input("changed")


def test_real_stdio_protocol_files_and_pause(tmp_path):
    async def run():
        env = dict(os.environ, WINDOWS_LOCAL_MCP_STATE=str(tmp_path / "state"), PYTHONIOENCODING="utf-8")
        params = StdioServerParameters(command=sys.executable, args=["-m", "windows_local_mcp"], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                tool_map = {t.name: t for t in tools}
                assert tool_map["write_file"].annotations.readOnlyHint is False
                assert tool_map["desktop_type_text"].annotations.openWorldHint is True
                assert tool_map["read_text_file"].annotations.readOnlyHint is True
                p = str(tmp_path / "协议测试.txt")
                write_result = await session.call_tool("write_file", {"path": p, "content": "通过MCP写入中文🙂"})
                assert not write_result.isError
                read_result = await session.call_tool("read_text_file", {"path": p})
                assert not read_result.isError
                assert "通过MCP写入中文🙂" in read_result.content[0].text
                overwrite = await session.call_tool("write_file", {"path": p, "content": "替换", "overwrite": True})
                assert not overwrite.isError
                assert "backup_path" in overwrite.content[0].text
                await session.call_tool("service_pause", {})
                blocked = await session.call_tool("read_text_file", {"path": p})
                assert blocked.isError
                status = await session.call_tool("service_status", {})
                assert not status.isError and "true" in status.content[0].text.lower()
    asyncio.run(run())
