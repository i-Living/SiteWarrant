"""Wrappers that put an agent's work on the trace and count what it costs.

The runner does not know about tracing or money: it asks a client for a reply and a tool provider
for facts. Wrapping both keeps the loop readable and makes the nesting honest — a model span is a
child of the agent span because the context variable says so, not because someone passed a parent
around by hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agents.llm import LlmClient, LlmReply
from app.agents.models import ToolResult
from app.agents.runner import ToolProvider
from app.pricing import Price
from app.telemetry import Tracer


class CostLimitExceeded(RuntimeError):
    """The audit's cost ceiling was reached; the agent stops rather than finishing the page."""

    def __init__(self, spent_usd: float, limit_usd: float) -> None:
        super().__init__(f"audit cost limit reached: {spent_usd:.6f} of {limit_usd:.6f} USD")
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd


class TracedLlm:
    """A model client that records a span and the estimated cost of every call."""

    def __init__(
        self,
        inner: LlmClient,
        *,
        tracer: Tracer,
        agent: str,
        price: Price | None = None,
        cost_limit_usd: float | None = None,
    ) -> None:
        self._inner = inner
        self._tracer = tracer
        self._agent = agent
        self._price = price
        self._limit = cost_limit_usd
        # A plain attribute, not a property: the client protocol promises a settable name.
        self.model = inner.model
        self.spent_usd = 0.0
        self.calls = 0

    async def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LlmReply:
        if self._limit is not None and self.spent_usd >= self._limit:
            raise CostLimitExceeded(self.spent_usd, self._limit)
        with self._tracer.span("llm.call", agent=self._agent, model=self.model) as span:
            reply = await self._inner.complete(messages=messages, tools=tools)
            cost = (
                None if self._price is None else self._price.cost(reply.tokens_in, reply.tokens_out)
            )
            span.attributes.update(
                {
                    "tokens_in": reply.tokens_in,
                    "tokens_out": reply.tokens_out,
                    "latency_ms": reply.latency_ms,
                    "tool_calls": len(reply.tool_calls),
                    # An unpriced model leaves the attribute out: absent, not zero.
                    "cost_estimate_usd": cost,
                }
            )
        self.calls += 1
        if cost is not None:
            self.spent_usd = round(self.spent_usd + cost, 6)
        return reply


class TracedTools:
    """A tool provider that records one span per call, with the size of what came back."""

    def __init__(self, inner: ToolProvider, *, tracer: Tracer, agent: str) -> None:
        self._inner = inner
        self._tracer = tracer
        self._agent = agent

    async def schemas(self, names: Sequence[str]) -> list[dict[str, Any]]:
        return await self._inner.schemas(names)

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        with self._tracer.span("tool.call", agent=self._agent, tool=name) as span:
            result = await self._inner.call(name, arguments)
            span.attributes["result_chars"] = len(result.text)
            span.attributes["result_images"] = len(result.images)
        return result
