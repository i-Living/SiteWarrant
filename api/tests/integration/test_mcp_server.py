import base64
import re
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
            "page_image",
            "rules_lookup",
        }
        schemas = await tools.schemas(["list_observations"])
        assert schemas[0]["function"]["parameters"]["type"] == "object"


async def test_the_agent_reads_the_same_facts_the_audit_stored() -> None:
    report = await run_audit(URL, allow_private=True)
    async with McpToolProvider(report.audit_id) as tools:
        pages = await tools.call("list_pages", {})
        assert "page_key" in pages.text

        contrast = await tools.call("list_observations", {"tool": "contrast"})
        assert "contrast_violation" in contrast.text

        one = await tools.call("channel_report", {"channel": "contrast", "viewport": "390x844"})
        assert "ratio" in one.text


async def test_an_observation_from_another_audit_is_refused() -> None:
    report = await run_audit(URL, allow_private=True)
    invented = str(uuid.uuid4())
    async with McpToolProvider(report.audit_id) as tools:
        answer = await tools.call("get_observation", {"observation_id": invented})
    assert "does not exist in this audit" in answer.text


async def test_the_corpus_is_queryable_through_the_protocol() -> None:
    report = await run_audit(URL, allow_private=True)
    async with McpToolProvider(report.audit_id) as tools:
        answer = await tools.call("rules_lookup", {"query": "contrast ratio of text", "limit": 3})
    assert "WCAG-1.4.3" in answer.text


async def test_the_page_reaches_the_model_as_an_image() -> None:
    """Decision 5a: one full capture per viewport, and the agent may look at it."""
    report = await run_audit(URL, allow_private=True)
    async with McpToolProvider(report.audit_id) as tools:
        for viewport in ("390x844", "768x1024", "1440x900"):
            answer = await tools.call("page_image", {"viewport": viewport})
            assert answer.images, answer.text
            image = answer.images[0]
            assert image.mime_type == "image/png"
            assert base64.b64decode(image.data_b64)[:8] == b"\x89PNG\r\n\x1a\n"
            assert viewport in answer.text
            # The caption names the observation the dimensions came from, and it resolves.
            cited = re.search(r"observation ([0-9a-f-]{36})", answer.text)
            assert cited, answer.text
            fact = await tools.call("get_observation", {"observation_id": cited.group(1)})
            assert f'"viewport": "{viewport}"' in fact.text
            assert '"tool": "screenshot"' in fact.text


async def test_a_run_that_stored_no_bytes_answers_with_a_refusal() -> None:
    """The eval corpus turns artifacts off; the tool says so instead of inventing a picture."""
    report = await run_audit(URL, allow_private=True, store_artifacts=False)
    async with McpToolProvider(report.audit_id) as tools:
        answer = await tools.call("page_image", {"viewport": "1440x900"})
    assert answer.images == []
    assert "stored no screenshot bytes" in answer.text


async def test_a_viewport_the_audit_never_captured_is_refused() -> None:
    report = await run_audit(URL, allow_private=True)
    async with McpToolProvider(report.audit_id) as tools:
        answer = await tools.call("page_image", {"viewport": "1920x1080"})
    assert answer.images == []
    assert "has no capture" in answer.text
