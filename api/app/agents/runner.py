import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from app.agents.digest import build_digest
from app.agents.llm import LlmClient, LlmError
from app.agents.models import (
    AgentRun,
    AgentSpec,
    CandidateFinding,
    LlmCallStat,
    ObservationFacts,
    Rejection,
)
from app.agents.prompts import system_prompt, user_prompt
from app.agents.validator import finding_identity, validate_all

MAX_TOOL_RESULT_CHARS = 2500
BUDGET_WARNING_SHARE = 0.7
MAX_REMINDERS = 1

SUBMIT_FINDINGS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_findings",
        "description": (
            "Submit your findings for this page. An empty list means the page is clean for "
            "your category. The validator checks every citation and every number before a "
            "finding is accepted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule_id": {"type": "string"},
                            "category": {"type": "string"},
                            "severity": {
                                "type": "string",
                                "enum": ["blocker", "major", "minor", "info"],
                            },
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "suggested_fix": {"type": "string"},
                            "impact": {
                                "type": "object",
                                "properties": {
                                    "conversion": {"type": "integer", "minimum": 0, "maximum": 3},
                                    "seo": {"type": "integer", "minimum": 0, "maximum": 3},
                                    "ux": {"type": "integer", "minimum": 0, "maximum": 3},
                                },
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "criterion": {"type": "string"},
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "observation_id": {"type": "string"},
                                        "kind": {"type": "string"},
                                        "excerpt": {"type": "string"},
                                    },
                                    "required": ["observation_id", "kind"],
                                },
                            },
                        },
                        "required": [
                            "rule_id",
                            "category",
                            "severity",
                            "title",
                            "summary",
                            "suggested_fix",
                            "evidence",
                        ],
                    },
                }
            },
            "required": ["findings"],
        },
    },
}


class ToolProvider(Protocol):
    """The MCP surface the loop needs: schemas to offer, and a call that returns text."""

    async def schemas(self, names: Sequence[str]) -> list[dict[str, Any]]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> str: ...


class BudgetExceeded(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_candidates(raw: Any) -> list[CandidateFinding]:
    if not isinstance(raw, list):
        raise ValueError("findings must be a list")
    return [CandidateFinding.model_validate(item) for item in raw]


def tool_message(call_id: str, text: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": text[:MAX_TOOL_RESULT_CHARS]}


def rejection_text(rejected: Sequence[Rejection]) -> str:
    lines = ["The validator rejected these findings. Fix them and submit again:"]
    for rejection in rejected:
        lines.append(f"- {rejection.rule_id}: {'; '.join(rejection.reasons)}")
    return "\n".join(lines)


async def run_agent(
    spec: AgentSpec,
    *,
    llm: LlmClient,
    tools: ToolProvider,
    observations: Mapping[str, ObservationFacts],
) -> AgentRun:
    """One agent, one bounded conversation.

    The loop stops on a validated submission, on a budget, or on a model that will not use
    the submit tool. Every exit other than a validated submission is a failure, because a
    silent agent that produced nothing would otherwise look like a clean page.
    """
    started = time.monotonic()
    digest = build_digest(list(observations.items()))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(spec, facts_digest=digest)},
        {"role": "user", "content": user_prompt()},
    ]
    tool_calls = 0
    tokens_in = 0
    tokens_out = 0
    llm_calls = 0
    reminders = 0
    calls: list[LlmCallStat] = []
    rejected_seen: list[Rejection] = []
    warned = False
    warned_calls = 0
    accepted_so_far: list[CandidateFinding] = []
    seen_candidates: set[tuple[str, str]] = set()

    def run(
        *,
        status: str,
        error: str | None = None,
        accepted: Sequence[CandidateFinding] | None = None,
    ) -> AgentRun:
        return AgentRun(
            name=spec.name,
            status=status,
            accepted=accepted or [],
            rejected=list(rejected_seen),
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            llm_calls=llm_calls,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=error,
            calls=calls,
        )

    def remaining() -> float:
        return spec.budget.timeout_s - (time.monotonic() - started)

    # Loading the tool schemas is awaited work like any other and is bounded by what is left,
    # not by the whole budget: the digest and the prompt were built before this point.
    if remaining() <= 0:
        return run(status="timeout", error=f"exceeded {spec.budget.timeout_s:.0f} s before setup")
    try:
        async with asyncio.timeout(remaining()):
            schemas = await tools.schemas(spec.tools)
    except TimeoutError:
        return run(
            status="timeout",
            error=f"exceeded {spec.budget.timeout_s:.0f} s loading tool schemas",
        )
    schemas.append(SUBMIT_FINDINGS_TOOL)

    while True:
        # The deadline covers the awaited work, not just the gap between calls: one slow
        # model reply must not let the agent finish after its budget is gone.
        if remaining() <= 0:
            return run(status="timeout", error=f"exceeded {spec.budget.timeout_s:.0f} s")
        # After the warning the token cap no longer stops the loop: the point of the warning
        # is to reserve room for the submission. The call count below is what bounds it.
        if not warned and tokens_in + tokens_out > spec.budget.max_tokens:
            return run(
                status="budget_exhausted",
                error=f"exceeded {spec.budget.max_tokens} tokens",
            )
        if warned:
            if warned_calls >= 2:
                return run(
                    status="budget_exhausted",
                    error="no submission after the budget warning",
                )
            warned_calls += 1
        if llm_calls >= spec.budget.max_tool_calls + 2:
            return run(status="budget_exhausted", error="too many model calls")

        # A conversation that keeps reading until the budget dies produces nothing at all.
        # Warn while there is still room, then refuse reads so the only way forward is a
        # submission; a report that silently loses an agent's work is the failure mode here.
        if not warned and tokens_in + tokens_out > spec.budget.max_tokens * BUDGET_WARNING_SHARE:
            warned = True
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Most of the token budget is spent. Submit what the facts already "
                        "support with `submit_findings`; further reads will be refused."
                    ),
                }
            )

        try:
            async with asyncio.timeout(remaining()):
                reply = await llm.complete(messages=messages, tools=schemas)
        except TimeoutError:
            return run(
                status="timeout",
                error=f"exceeded {spec.budget.timeout_s:.0f} s waiting for the model",
            )
        except LlmError as error:
            return run(status="llm_error", error=str(error)[:500])
        llm_calls += 1
        tokens_in += reply.tokens_in
        tokens_out += reply.tokens_out
        calls.append(
            LlmCallStat(
                tokens_in=reply.tokens_in,
                tokens_out=reply.tokens_out,
                latency_ms=reply.latency_ms,
            )
        )

        if not reply.tool_calls:
            if reminders >= MAX_REMINDERS:
                return run(status="no_submission", error="the model never called submit_findings")
            reminders += 1
            messages.append({"role": "assistant", "content": reply.content or ""})
            messages.append(
                {
                    "role": "user",
                    "content": "Submit your findings now with the `submit_findings` tool.",
                }
            )
            continue

        messages.append(
            {
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in reply.tool_calls
                ],
            }
        )

        for call in reply.tool_calls:
            if call.name != "submit_findings":
                if warned:
                    messages.append(
                        tool_message(
                            call.id,
                            "refused: the token budget is nearly spent, call submit_findings",
                        )
                    )
                    continue
                tool_calls += 1
                if tool_calls > spec.budget.max_tool_calls:
                    return run(
                        status="budget_exhausted",
                        error=f"exceeded {spec.budget.max_tool_calls} tool calls",
                    )
                if remaining() <= 0:
                    return run(
                        status="timeout",
                        error=f"exceeded {spec.budget.timeout_s:.0f} s before tool {call.name}",
                    )
                try:
                    async with asyncio.timeout(remaining()):
                        text = await tools.call(call.name, call.arguments)
                except TimeoutError:
                    return run(
                        status="timeout",
                        error=f"exceeded {spec.budget.timeout_s:.0f} s in tool {call.name}",
                    )
                except Exception as error:
                    text = f"tool {call.name} failed: {error}"
                messages.append(tool_message(call.id, text))
                continue

            try:
                candidates = parse_candidates(call.arguments.get("findings"))
            except (ValidationError, ValueError) as error:
                messages.append(tool_message(call.id, f"invalid findings payload: {error}"))
                continue

            result = validate_all(candidates, observations=observations, agent=spec.name)
            # A retry usually resubmits only the rejected candidate, so accepted ones have to
            # survive the round. Identical resubmissions are dropped; distinct findings that
            # happen to share an observation are not, because that is the chief auditor's call.
            for candidate in result.accepted:
                # Same identity rule as the validator: a subject the evidence contains, or the
                # evidence itself. Two distinct targets keep both findings across retries.
                key = (candidate.rule_id, finding_identity(candidate, observations))
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                accepted_so_far.append(candidate)
            if result.rejected:
                rejected_seen.extend(result.rejected)
                messages.append(tool_message(call.id, rejection_text(result.rejected)))
                continue
            return run(status="ok", accepted=accepted_so_far)
