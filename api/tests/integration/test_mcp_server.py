import uuid

import pytest

from app.audit import run_audit
from app.mcp.client import McpToolProvider

pytestmark = pytest.mark.integration

URL = "http://localhost:8081/"


async def test_the_server_exposes_the_fact_tools() -> None:
    report = await run_audit(URL, allow_private=True)
    async with McpToolProvider(report.audit_id) as tools:
        assert set(tools.tool_names) == {
            "list_pages",
            "list_observations",
            "get_observation",
            "channel_report",
            "screenshot_artifact",
            "rules_lookup",
        }
        schemas = await tools.schemas(["list_observations"])
        assert schemas[0]["function"]["parameters"]["type"] == "object"


async def test_the_agent_reads_the_same_facts_the_audit_stored() -> None:
    report = await run_audit(URL, allow_private=True)
    async with McpToolProvider(report.audit_id) as tools:
        pages = await tools.call("list_pages", {})
        assert "page_key" in pages

        contrast = await tools.call("list_observations", {"tool": "contrast"})
        assert "contrast_violation" in contrast

        one = await tools.call("channel_report", {"channel": "contrast", "viewport": "390x844"})
        assert "ratio" in one


async def test_an_observation_from_another_audit_is_refused() -> None:
    report = await run_audit(URL, allow_private=True)
    invented = str(uuid.uuid4())
    async with McpToolProvider(report.audit_id) as tools:
        answer = await tools.call("get_observation", {"observation_id": invented})
    assert "does not exist in this audit" in answer


async def test_the_corpus_is_queryable_through_the_protocol() -> None:
    report = await run_audit(URL, allow_private=True)
    async with McpToolProvider(report.audit_id) as tools:
        answer = await tools.call("rules_lookup", {"query": "contrast ratio of text", "limit": 3})
    assert "WCAG-1.4.3" in answer
