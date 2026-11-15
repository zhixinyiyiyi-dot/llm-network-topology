import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = "http://127.0.0.1:39400/mcp"
    async with streamablehttp_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            result = await session.list_tools()

            wanted = {
                "pt_query_topology",
                "pt_cli",
                "pt_host_command",
                "pt_verify_connectivity",
            }
            selected = [
                tool.model_dump(mode="json")
                for tool in result.tools
                if tool.name in wanted
            ]

            output = json.dumps(
                selected, ensure_ascii=False, indent=2
            )
            Path("pt_tools.json").write_text(
                output, encoding="utf-8"
            )

            print("连接成功，找到工具：")
            for tool in selected:
                print("-", tool["name"])
            print("已保存 pt_tools.json")


asyncio.run(main())