"""The runner's tool reads land on the trace, as children of the agent span."""

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.agents.llm import LlmReply, ToolCall
from app.agents.models import AgentBudget, AgentSpec, ObservationFacts
from app.agents.runner import run_agent
from app.agents.traced import CostLimitExceeded, TracedLlm, TracedTools
from app.pricing import Price
from app.telemetry import Tracer

DOM_ID = "obs-1"
DOM_PATH = "html:nth-of-type(1) > body:nth-of-type(1) > h1:nth-of-type(1)"
PRICE = Price(model="test-model", input_usd_per_1m=0.30, output_usd_per_1m=1.20)


def observations() -> dict[str, ObservationFacts]:
    return {
        DOM_ID: ObservationFacts(
            tool="dom",
            kind="heading_outline",
            payload={"h1": 0, "h2": 1, "path": DOM_PATH, "text": "Field notes"},
        )
    }


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def schemas(self, names: Sequence[str]) -> list[dict[str, Any]]:
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


class ScriptedClient:
    """Reads one fact, then submits one finding: the shortest conversation with a tool call."""

    def __init__(self, spec: AgentSpec) -> None:
        self.model = "test-model"
        self._spec = spec
        self.replies: list[LlmReply] = [
            LlmReply(
                content=None,
                tool_calls=[ToolCall(id="c1", name="get_observation", arguments={"id": DOM_ID})],
                tokens_in=100,
                tokens_out=20,
                latency_ms=5,
            ),
            LlmReply(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="submit_findings",
                        arguments={
                            "findings": [
                                {
                                    "rule_id": "SEO-HEADING-ORDER",
                                    "category": "seo",
                                    "severity": "major",
                                    "title": "No h1",
                                    "summary": "The outline starts at h2, so no top level exists.",
                                    "suggested_fix": "Promote the first h2 to h1.",
                                    "evidence": [{"observation_id": DOM_ID, "kind": "dom"}],
                                }
                            ]
                        },
                    )
                ],
                tokens_in=120,
                tokens_out=40,
                latency_ms=5,
            ),
        ]
        self.seen = 0

    async def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LlmReply:
        reply = self.replies[min(self.seen, len(self.replies) - 1)]
        self.seen += 1
        return reply


def spec() -> AgentSpec:
    return AgentSpec(
        name="seo",
        category="seo",
        prompt_file="seo.md",
        tools=("get_observation",),
        budget=AgentBudget(max_tool_calls=4, max_tokens=10_000, timeout_s=30),
    )


async def run(*, cost_limit_usd: float | None = None) -> tuple[Any, Tracer]:
    tracer = Tracer()
    client = ScriptedClient(spec())
    inner = FakeTools()
    with tracer.span("agent", agent="seo"):
        result = await run_agent(
            spec(),
            llm=TracedLlm(
                client, tracer=tracer, agent="seo", price=PRICE, cost_limit_usd=cost_limit_usd
            ),
            tools=TracedTools(inner, tracer=tracer, agent="seo"),
            observations=observations(),
        )
    return result, tracer


async def test_a_tool_read_is_a_span_under_the_agent() -> None:
    result, tracer = await run()
    assert result.status == "ok"
    names = [span.name for span in tracer.spans]
    assert names.count("tool.call") == 1
    assert names.count("llm.call") == 2
    agent = next(span for span in tracer.spans if span.name == "agent")
    tool = next(span for span in tracer.spans if span.name == "tool.call")
    assert tool.parent_id == agent.span_id
    assert tool.attributes["tool"] == "get_observation"
    assert tool.attributes["result_chars"] > 0


async def test_model_calls_carry_tokens_and_a_priced_estimate() -> None:
    _, tracer = await run()
    calls = [span for span in tracer.spans if span.name == "llm.call"]
    assert [call.attributes["tokens_in"] for call in calls] == [100, 120]
    expected = PRICE.cost(100, 20) + PRICE.cost(120, 40)
    assert sum(call.attributes["cost_estimate_usd"] for call in calls) == pytest.approx(
        expected, abs=1e-9
    )


async def test_a_spent_ceiling_stops_the_next_call() -> None:
    tracer = Tracer()
    client = ScriptedClient(spec())
    traced = TracedLlm(client, tracer=tracer, agent="seo", price=PRICE, cost_limit_usd=0.00001)
    from app.agents.traced import TracedTools

    with tracer.span("agent", agent="seo"), pytest.raises(CostLimitExceeded) as caught:
        await run_agent(
            spec(),
            llm=traced,
            tools=TracedTools(FakeTools(), tracer=tracer, agent="seo"),
            observations=observations(),
        )
    # The first call is paid for; the second stops at the ceiling and says how much was spent.
    assert traced.spent_usd > 0
    assert caught.value.spent_usd == pytest.approx(traced.spent_usd)
    assert traced.calls == 1
