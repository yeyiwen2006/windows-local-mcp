"""Exercise discovery, bounded search and versioned editing over a real MCP stdio session."""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_file_workflow_over_stdio(tmp_path):
    async def run():
        root = tmp_path / "project"
        root.mkdir()
        state = tmp_path / "service-state"
        env = dict(os.environ, WINDOWS_LOCAL_MCP_STATE=str(state), PYTHONIOENCODING="utf-8")
        params = StdioServerParameters(command=sys.executable,
                                      args=["-m", "windows_local_mcp"], env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                for name in ("search_files", "search_text"):
                    assert tools[name].annotations.readOnlyHint is True
                assert tools["edit_text_file"].annotations.readOnlyHint is False
                assert "expected_version" in tools["edit_text_file"].inputSchema["required"]

                async def call(name, arguments):
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result
                    return json.loads(result.content[0].text)

                status = await call("service_status", {})
                assert status["commands"]["enabled"] is False
                path = str(root / "中文.txt")
                await call("write_file", {"path": path, "content": "标题\r\n原始内容🙂\r\n"})
                matches = await call("search_text", {"root": str(root), "query": "原始内容🙂"})
                assert matches["results"][0]["line"] == 2
                names = await call("search_files", {"root": str(root), "name_pattern": "*.txt"})
                assert [item["path"] for item in names["results"]] == [path]
                read = await call("read_text_file", {"path": path})
                edited = await call("edit_text_file", {
                    "path": path, "old_text": "原始内容🙂", "new_text": "更新内容🙂",
                    "expected_version": read["version"],
                })
                assert edited["changed"] and edited["replacements"] == 1
                assert Path(edited["backup_path"]).read_bytes() == "标题\r\n原始内容🙂\r\n".encode()
                stale = await session.call_tool("edit_text_file", {
                    "path": path, "old_text": "更新内容🙂", "new_text": "不应写入",
                    "expected_version": read["version"],
                })
                assert stale.isError
                final = await call("read_text_file", {"path": path})
                assert final["text"] == "标题\r\n更新内容🙂\r\n"
                assert not (await call("search_text", {"root": str(root), "query": "原始内容🙂"}))["results"]
                await call("service_pause", {})
                assert (await session.call_tool("search_files", {"root": str(root)})).isError
                audit = "".join(p.read_text(encoding="utf-8") for p in (state / "audit").glob("*.jsonl"))
                assert "原始内容🙂" not in audit and "更新内容🙂" not in audit
    asyncio.run(run())
