"""The MCP server: the same facts an auditor reads, exposed as a protocol.

The server is scoped to one audit, passed in the environment, so a third-party MCP client can
connect to these tools and still see only the facts of the audit it was started for.
"""

import os
import uuid
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.mcp import tools

AUDIT_ENV = "SITEWARRANT_MCP_AUDIT_ID"


def audit_id_from_env() -> uuid.UUID:
    raw = os.environ.get(AUDIT_ENV)
    if not raw:
        raise SystemExit(f"{AUDIT_ENV} is not set; the server serves one audit at a time")
    return uuid.UUID(raw)


def build_server(audit_id: uuid.UUID) -> MCPServer:
    server = MCPServer(
        name="sitewarrant-facts",
        version="0.1.0",
        instructions=(
            "Read-only facts for one SiteWarrant audit. Every observation carries an "
            "observation_id; cite those ids when you claim something about the page."
        ),
    )

    @server.tool()
    async def list_pages() -> list[dict[str, Any]]:
        """List the pages of this audit with their page keys."""
        return await tools.list_pages(audit_id)

    @server.tool()
    async def list_observations(
        tool: str | None = None,
        rule_ref: str | None = None,
        viewport: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List observations of this audit, optionally filtered by channel, rule or viewport."""
        return await tools.list_observations(
            audit_id, tool=tool, rule_ref=rule_ref, viewport=viewport, limit=limit
        )

    @server.tool()
    async def get_observation(observation_id: str) -> dict[str, Any]:
        """Read one observation in full, including its payload."""
        return await tools.get_observation(audit_id, observation_id)

    @server.tool()
    async def channel_report(
        channel: str, viewport: str | None = None, page_key: str | None = None
    ) -> list[dict[str, Any]]:
        """Read every observation of one channel (http, dom, axe, contrast, responsive,
        occlusion, performance, screenshot) with full payloads."""
        return await tools.channel_report(
            audit_id, channel=channel, viewport=viewport, page_key=page_key
        )

    @server.tool()
    async def screenshot_artifact(viewport: str | None = None) -> list[dict[str, Any]]:
        """List the screenshot artifact keys of this audit, for a vision pass."""
        return await tools.screenshot_artifact(audit_id, viewport=viewport)

    @server.tool()
    async def rules_lookup(query: str, limit: int = 4) -> list[dict[str, Any]]:
        """Retrieve the rule corpus chunks that match a query, with their ids and text."""
        return await tools.rules_lookup(query, limit=limit)

    return server


def main() -> None:
    build_server(audit_id_from_env()).run("stdio")


if __name__ == "__main__":
    main()
