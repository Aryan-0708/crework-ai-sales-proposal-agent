"""Reusable DocuSign MCP client for the Sales Proposal Agent.

Uses the official MCP Python SDK with the DocuSign Demo MCP server.
The access token is read from .env and is never printed.

Examples:
    python docusign_mcp_client.py list-tools
    python docusign_mcp_client.py describe-tool createEnvelope
    python docusign_mcp_client.py describe-tool createEnvelopeFromTemplate
    python docusign_mcp_client.py call-tool getTemplates "{}"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

import httpx2
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

load_dotenv()

MCP_URL = os.getenv("DOCUSIGN_MCP_URL", "https://mcp-d.docusign.com/mcp")
ACCESS_TOKEN = os.getenv("DOCUSIGN_ACCESS_TOKEN")


class DocuSignMCPClient:
    """Small reusable wrapper around the official MCP Python SDK."""

    def __init__(self, mcp_url: str = MCP_URL, access_token: str | None = ACCESS_TOKEN):
        if not access_token:
            raise ValueError(
                "Missing DOCUSIGN_ACCESS_TOKEN in .env. "
                "Run get_docusign_token.py first."
            )
        self.mcp_url = mcp_url
        self.access_token = access_token

    async def _session(self) -> Any:
        """Create an authenticated MCP session.

        This is an async context manager factory used internally.
        """
        http_client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=60,
        )
        transport = streamable_http_client(
            self.mcp_url,
            http_client=http_client,
        )
        return http_client, transport

    async def list_tools(self) -> list[Any]:
        """Return the currently exposed DocuSign MCP tools."""
        http_client, transport = await self._session()
        try:
            async with http_client:
                async with transport as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return list(result.tools)
        finally:
            # The async-with blocks above own the network resources.
            pass

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Invoke one MCP tool and return the SDK result."""
        arguments = arguments or {}
        http_client, transport = await self._session()
        try:
            async with http_client:
                async with transport as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        return await session.call_tool(name, arguments)
        finally:
            pass


async def list_tools_command() -> None:
    client = DocuSignMCPClient()
    tools = await client.list_tools()

    print("=" * 72)
    print("DOCUSIGN MCP CLIENT — TOOL DISCOVERY")
    print("=" * 72)
    print(f"Endpoint: {client.mcp_url}")
    print(f"Tools returned: {len(tools)}\n")

    for i, tool in enumerate(tools, start=1):
        title = getattr(tool, "title", None)
        description = getattr(tool, "description", None)
        print(f"{i:02d}. {tool.name}")
        if title:
            print(f"    Title: {title}")
        if description:
            one_line = " ".join(description.split())
            print(f"    Description: {one_line}")
        print()

    # Save machine-readable discovery output for later steps.
    serializable = []
    for tool in tools:
        serializable.append(
            {
                "name": tool.name,
                "title": getattr(tool, "title", None),
                "description": getattr(tool, "description", None),
                "inputSchema": getattr(tool, "inputSchema", None),
            }
        )

    with open("docusign_tools.json", "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, default=str)

    print("Saved full tool metadata to docusign_tools.json")


async def describe_tool_command(name: str) -> None:
    client = DocuSignMCPClient()
    tools = await client.list_tools()

    for tool in tools:
        if tool.name == name:
            print("=" * 72)
            print(f"TOOL: {tool.name}")
            print("=" * 72)
            print(f"Title: {getattr(tool, 'title', None)}")
            print(f"Description:\n{getattr(tool, 'description', '')}\n")
            print("Input schema:")
            print(
                json.dumps(
                    getattr(tool, "inputSchema", {}),
                    indent=2,
                    default=str,
                )
            )
            return

    raise SystemExit(f"Tool not found: {name}")


async def call_tool_command(name: str, arguments_json: str, args_file: str | None = None) -> None:
    """Invoke one MCP tool with explicit JSON arguments and print the raw result."""
    if args_file:
        with open(args_file, "r", encoding="utf-8-sig") as f:
            arguments = json.load(f)
    else:
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as e:
            raise SystemExit(f"Invalid JSON in arguments: {e}")

    client = DocuSignMCPClient()
    result = await client.call_tool(name, arguments)

    print("=" * 72)
    print(f"CALL TOOL: {name}")
    print("=" * 72)
    print(f"Arguments sent: {json.dumps(arguments, indent=2)}\n")

    is_error = getattr(result, "isError", False)
    print(f"isError: {is_error}\n")

    print("Result content:")
    content = getattr(result, "content", None) or []
    if not content:
        print(json.dumps(result, indent=2, default=str))
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            # Pretty-print if it's JSON text, otherwise print as-is.
            try:
                parsed = json.loads(text)
                print(json.dumps(parsed, indent=2))
            except (json.JSONDecodeError, TypeError):
                print(text)
        else:
            print(item)


async def main() -> None:
    parser = argparse.ArgumentParser(description="DocuSign MCP client")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-tools", help="List all exposed MCP tools")

    # Also accept the dashed form used in the instructions.
    sub.add_parser("describe-tool", help="Print one tool's schema").add_argument("name")

    call_parser = sub.add_parser("call-tool", help="Invoke one MCP tool with JSON arguments")
    call_parser.add_argument("name")
    call_parser.add_argument(
        "args_json",
        nargs="?",
        default="{}",
        help="JSON string of arguments, e.g. '{\"key\": \"value\"}'. Defaults to {}.",
    )
    call_parser.add_argument(
        "--args-file",
        dest="args_file",
        default=None,
        help="Path to a JSON file with the arguments (use this on Windows/PowerShell "
        "to avoid double-quote mangling on the command line).",
    )

    args = parser.parse_args()

    if args.command == "list-tools":
        await list_tools_command()
    elif args.command == "describe-tool":
        await describe_tool_command(args.name)
    elif args.command == "call-tool":
        await call_tool_command(args.name, args.args_json, args.args_file)


if __name__ == "__main__":
    asyncio.run(main())