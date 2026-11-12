"""The orchestrator's MCP client: the agent loop talks to the tools over the protocol."""

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import TextContent

from app.mcp.server import AUDIT_ENV

API_DIR = Path(__file__).resolve().parents[2]


def server_parameters(audit_id: str, *, env: dict[str, str] | None = None) -> StdioServerParameters:
    """How to start the fact server for one audit.

    The child inherits the parent's environment so it reads the same database, and gets the
    audit id explicitly: the process boundary is what keeps one audit's facts out of another.
    """
    child_env = dict(os.environ if env is None else env)
    child_env[AUDIT_ENV] = audit_id
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        env=child_env,
        cwd=str(API_DIR),
    )


def openai_schema(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or tool.name,
            # MCP 2.x renamed the field; v1 clients call it inputSchema.
            "parameters": getattr(tool, "input_schema", None)
            or getattr(tool, "inputSchema", None)
            or {"type": "object", "properties": {}},
        },
    }


class McpToolProvider:
    """Implements the agent loop's ToolProvider over a real MCP session."""

    def __init__(self, audit_id: str, *, parameters: StdioServerParameters | None = None) -> None:
        self.audit_id = audit_id
        self.parameters = parameters or server_parameters(audit_id)
        self._client: Client | None = None
        self._context: Any = None
        self.tool_names: list[str] = []

    async def __aenter__(self) -> "McpToolProvider":
        self._context = Client(self.parameters, raise_exceptions=False)
        self._client = await self._context.__aenter__()
        listing = await self._client.list_tools()
        self.tool_names = [tool.name for tool in listing.tools]
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._context is not None:
            await self._context.__aexit__(*exc_info)

    @property
    def client(self) -> Client:
        if self._client is None:
            raise RuntimeError("McpToolProvider must be used as an async context manager")
        return self._client

    async def schemas(self, names: Sequence[str]) -> list[dict[str, Any]]:
        listing = await self.client.list_tools()
        available = {tool.name: tool for tool in listing.tools}
        missing = [name for name in names if name not in available]
        if missing:
            raise RuntimeError(f"the fact server has no tool(s): {', '.join(missing)}")
        return [openai_schema(available[name]) for name in names]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self.client.call_tool(name, arguments)
        texts = [block.text for block in result.content if isinstance(block, TextContent)]
        if not texts:
            return "the tool returned no text content"
        return "\n".join(texts)
