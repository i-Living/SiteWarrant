import json
import uuid
from pathlib import Path
from typing import Any

from app.agents.llm import CassetteClient
from app.agents.models import AgentBudget, AgentSpec, ObservationFacts
from app.agents.runner import run_agent

DOM_ID = str(uuid.uuid4())


def observations() -> dict[str, ObservationFacts]:
    return {
        DOM_ID: ObservationFacts(
            tool="dom",
            kind="dom_snapshot",
            viewport="390x844",
            payload={
                "title": "Fixture",
                "meta_description": "short",
                "canonical": None,
                "h1_count": 1,
                "images_total": 12,
                "images_missing_alt": 3,
            },
        )
    }


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def schemas(self, names):  # type: ignore[no-untyped-def]
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"{name} (test double)",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in names
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        return json.dumps({"observation_id": DOM_ID, "payload": observations()[DOM_ID].payload})


def spec(**overrides: Any) -> AgentSpec:
    base: dict[str, Any] = {
        "name": "seo",
        "category": "seo",
        "prompt_file": "seo.md",
        "tools": ("list_observations",),
    }
    base.update(overrides)
    return AgentSpec.model_validate(base)


def reply(*, content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if tool_calls else "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls or [],
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def submit(call_id: str, findings: Any) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "submit_findings", "arguments": json.dumps({"findings": findings})},
    }


def fetch(call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "list_observations", "arguments": "{}"},
    }


def valid_finding(**overrides: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "rule_id": "SEO-CANONICAL",
        "category": "seo",
        "severity": "minor",
        "title": "Page declares no canonical URL",
        "summary": "The DOM snapshot has no canonical link, so duplicates compete in search.",
        "suggested_fix": "Add a canonical link pointing at the preferred URL.",
        "impact": {"seo": 2},
        "confidence": 0.9,
        "evidence": [{"observation_id": DOM_ID, "kind": "dom"}],
    }
    finding.update(overrides)
    return finding


def cassette(tmp_path: Path, responses: list[dict]) -> CassetteClient:
    path = tmp_path / "cassette.json"
    path.write_text(
        json.dumps(
            {"model": "deepseek-v4.1-flash", "interactions": [{"response": r} for r in responses]}
        ),
        encoding="utf-8",
    )
    return CassetteClient(path)


async def test_a_valid_submission_finishes_the_agent(tmp_path: Path) -> None:
    llm = cassette(tmp_path, [reply(tool_calls=[submit("c1", [valid_finding()])])])
    run = await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    assert run.status == "ok"
    assert len(run.accepted) == 1
    assert run.accepted[0].rule_id == "SEO-CANONICAL"
    assert run.tokens_in == 120
    assert run.llm_calls == 1


async def test_a_clean_page_is_an_empty_submission_not_a_failure(tmp_path: Path) -> None:
    llm = cassette(tmp_path, [reply(tool_calls=[submit("c1", [])])])
    run = await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    assert run.status == "ok"
    assert run.accepted == []


async def test_a_fabricated_citation_is_rejected_then_the_agent_can_fix_it(tmp_path: Path) -> None:
    invented = str(uuid.uuid4())
    llm = cassette(
        tmp_path,
        [
            reply(
                tool_calls=[
                    submit(
                        "c1",
                        [valid_finding(evidence=[{"observation_id": invented, "kind": "dom"}])],
                    )
                ]
            ),
            reply(tool_calls=[submit("c2", [valid_finding()])]),
        ],
    )
    run = await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    assert run.status == "ok"
    assert run.llm_calls == 2
    assert len(run.accepted) == 1
    # The rejected candidate never reaches the report.
    assert run.accepted[0].evidence[0].observation_id == DOM_ID


async def test_a_rejected_submission_is_answered_with_the_reasons(tmp_path: Path) -> None:
    llm = cassette(
        tmp_path,
        [
            reply(tool_calls=[submit("c1", [valid_finding(summary="Nine images are broken.")])]),
            reply(tool_calls=[submit("c2", [])]),
        ],
    )
    run = await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    assert run.status == "ok"
    request = llm.recorded[1]["request"]["messages"]
    rejection = [message for message in request if message["role"] == "tool"][-1]["content"]
    assert "validator rejected" in rejection
    assert "number 9" in rejection


async def test_the_tool_budget_stops_the_agent(tmp_path: Path) -> None:
    llm = cassette(
        tmp_path,
        [
            reply(tool_calls=[fetch("c1")]),
            reply(tool_calls=[fetch("c2")]),
            reply(tool_calls=[submit("c3", [])]),
        ],
    )
    tools = FakeTools()
    run = await run_agent(
        spec(budget=AgentBudget(max_tool_calls=1)),
        llm=llm,
        tools=tools,
        observations=observations(),
    )

    assert run.status == "budget_exhausted"
    assert run.tool_calls == 2
    assert len(tools.calls) == 1


async def test_a_model_that_never_submits_fails_loudly(tmp_path: Path) -> None:
    llm = cassette(tmp_path, [reply(content="Looks fine to me."), reply(content="Really fine.")])
    run = await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    assert run.status == "no_submission"
    assert run.error is not None


async def test_a_malformed_payload_is_reported_to_the_model(tmp_path: Path) -> None:
    llm = cassette(
        tmp_path,
        [
            reply(tool_calls=[submit("c1", [{"rule_id": "SEO-CANONICAL"}])]),
            reply(tool_calls=[submit("c2", [valid_finding()])]),
        ],
    )
    run = await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    assert run.status == "ok"
    assert len(run.accepted) == 1
    request = llm.recorded[1]["request"]["messages"]
    tool_text = [message for message in request if message["role"] == "tool"][-1]["content"]
    assert "invalid findings payload" in tool_text


async def test_a_tool_failure_does_not_kill_the_agent(tmp_path: Path) -> None:
    class BrokenTools(FakeTools):
        async def call(self, name: str, arguments: dict[str, Any]) -> str:
            raise RuntimeError("database is down")

    llm = cassette(
        tmp_path,
        [reply(tool_calls=[fetch("c1")]), reply(tool_calls=[submit("c2", [valid_finding()])])],
    )
    run = await run_agent(spec(), llm=llm, tools=BrokenTools(), observations=observations())

    assert run.status == "ok"
    assert len(run.accepted) == 1


async def test_the_prompt_carries_the_claims_and_the_fact_ids(tmp_path: Path) -> None:
    llm = cassette(tmp_path, [reply(tool_calls=[submit("c1", [])])])
    await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    system = llm.recorded[0]["request"]["messages"][0]["content"]
    assert "SEO-CANONICAL" in system
    assert DOM_ID in system
    assert "submit_findings" in json.dumps(llm.recorded[0]["request"]["tools"])


async def test_an_empty_cassette_fails_instead_of_hanging(tmp_path: Path) -> None:
    llm = cassette(tmp_path, [])
    run = await run_agent(spec(), llm=llm, tools=FakeTools(), observations=observations())

    assert run.status == "llm_error"
    assert run.error is not None and "cassette" in run.error


async def test_the_agent_is_warned_before_the_token_budget_runs_out(tmp_path: Path) -> None:
    """A conversation that reads until the budget dies produces nothing at all."""
    llm = cassette(
        tmp_path,
        [reply(tool_calls=[fetch("c1")]), reply(tool_calls=[submit("c2", [])])],
    )
    run = await run_agent(
        spec(budget=AgentBudget(max_tokens=200)),
        llm=llm,
        tools=FakeTools(),
        observations=observations(),
    )

    assert run.status == "ok"
    assert len(llm.recorded) == 2
    second_request = llm.recorded[1]["request"]["messages"]
    assert any(
        "Most of the token budget is spent" in str(message.get("content"))
        for message in second_request
    )


async def test_a_read_after_the_warning_is_refused(tmp_path: Path) -> None:
    """Past the warning the only way forward is a submission, not another read."""
    tools = FakeTools()
    llm = cassette(
        tmp_path,
        [
            reply(tool_calls=[fetch("c1")]),
            reply(tool_calls=[fetch("c2")]),
            reply(tool_calls=[submit("c3", [])]),
        ],
    )
    run = await run_agent(
        spec(budget=AgentBudget(max_tokens=200)), llm=llm, tools=tools, observations=observations()
    )

    assert run.status == "ok"
    assert len(tools.calls) == 1, "the read after the warning is refused, not executed"
    third_request = llm.recorded[2]["request"]["messages"]
    refusals = [
        message
        for message in third_request
        if message.get("role") == "tool" and "refused" in str(message.get("content"))
    ]
    assert refusals, "the model must be told why its read did not happen"
