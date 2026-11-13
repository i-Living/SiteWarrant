"""The Chief Auditor's narration is checked like a finding: no number it does not have."""

import asyncio
import json
import uuid

from app.agents.llm import LlmError, LlmReply
from app.agents.models import AgentRun, OrchestrationResult
from app.audit import explain_causes, narration_is_affordable
from app.chief.narrate import (
    MAX_SUMMARY_CHARS,
    allowed_numbers,
    apply_narration,
    cause_facts,
    narrate,
    prompt_digest_sha,
    prompt_text,
)
from app.core.config import Settings
from app.core.report import EvidenceOut, FindingOut, ImpactOut, RootCauseOut
from app.telemetry import Tracer


def finding(
    *,
    rule_id: str = "A11Y-CONTRAST",
    category: str = "a11y",
    severity: str = "major",
    title: str = "Text below the contrast threshold",
) -> FindingOut:
    return FindingOut(
        id=str(uuid.uuid4()),
        rule_id=rule_id,
        category=category,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        summary="measured",
        suggested_fix="darken the text",
        impact=ImpactOut(conversion=1, seo=0, ux=2),
        confidence=1.0,
        agent="rules",
        page_url="http://localhost:8081/",
        page_key="localhost",
        evidence=[EvidenceOut(kind="contrast", observation_id="obs-1")],
    )


def cause(*, finding_ids: list[str], anchor: str = "header:nth-of-type(1)") -> RootCauseOut:
    return RootCauseOut(
        id="rc-1",
        kind="dom_anchor",
        anchor=anchor,
        label="header",
        categories=["a11y", "responsive"],
        summary="2 findings in 2 categories share header.",
        rationale="A11Y-CONTRAST, LAYOUT-OCCLUSION",
        severity="major",
        priority=2.5,
        finding_ids=finding_ids,
    )


class StubClient:
    """One reply, or one failure: the narration makes a single call and never a second."""

    model = "stub-model"

    def __init__(self, *, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[list[dict]] = []

    async def complete(self, *, messages: list[dict], tools: list[dict]) -> LlmReply:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return LlmReply(content=self.content, tokens_in=1200, tokens_out=180, latency_ms=900)


def narrated(payload: dict) -> StubClient:
    return StubClient(content=json.dumps(payload))


def one_cause() -> tuple[RootCauseOut, dict[str, FindingOut]]:
    first = finding()
    second = finding(rule_id="LAYOUT-OCCLUSION", category="responsive")
    return (
        cause(finding_ids=[first.id, second.id]),
        {first.id: first, second.id: second},
    )


def test_prose_within_the_facts_replaces_the_measured_text() -> None:
    item, findings = one_cause()
    client = narrated(
        {
            "causes": [
                {
                    "id": "rc-1",
                    "summary": "The header text is hard to read and the block crowds the page.",
                    "rationale": "Fixing the header closes two symptoms at once.",
                }
            ]
        }
    )
    result = asyncio.run(narrate([item], findings, client=client))

    assert result.status == "ok"
    assert result.accepted == 1
    assert result.causes[0].summary.startswith("The header text")
    assert result.tokens_in == 1200 and result.llm_calls == 1
    assert result.calls[0].tokens_out == 180
    assert len(client.calls) == 1, "narration is one call, not a conversation"


def test_an_invented_number_is_rejected_and_the_measured_text_stays() -> None:
    item, findings = one_cause()
    client = narrated(
        {
            "causes": [
                {
                    "id": "rc-1",
                    "summary": "Seven of the 41 visitors cannot read the header.",
                    "rationale": "Fixing the header closes two symptoms.",
                }
            ]
        }
    )
    result = asyncio.run(narrate([item], findings, client=client))

    assert result.status == "rejected"
    assert result.accepted == 0
    assert result.causes[0].summary == item.summary
    assert "41" in (result.error or "")


def test_a_count_the_facts_carry_is_allowed() -> None:
    item, findings = one_cause()
    client = narrated(
        {
            "causes": [
                {
                    "id": "rc-1",
                    "summary": "2 findings from 2 categories meet in the header.",
                    "rationale": "One fix in the header can close both.",
                }
            ]
        }
    )
    result = asyncio.run(narrate([item], findings, client=client))

    assert result.status == "ok", result.error


def test_a_claim_constant_is_not_a_measurement() -> None:
    """ "4.5:1" is the rule, and repeating it is not a claim about this page."""
    item = finding(rule_id="A11Y-CONTRAST")
    facts = cause_facts(cause(finding_ids=[item.id]), {item.id: item})
    numbers = allowed_numbers(facts, ["A11Y-CONTRAST"])

    assert 4.5 in numbers, "the claim's own constant is allowed"
    assert 3.7 not in numbers


def test_an_unknown_id_is_ignored_and_the_rest_still_lands() -> None:
    item, findings = one_cause()
    other = cause(finding_ids=[], anchor="main:nth-of-type(1)")
    other.id = "rc-2"
    payload = {
        "causes": [
            {"id": "rc-404", "summary": "nothing to see", "rationale": "nothing"},
            {"id": "rc-1", "summary": "The header hides its own content.", "rationale": "One fix."},
        ]
    }
    result = asyncio.run(narrate([item, other], findings, client=narrated(payload)))

    assert result.accepted == 1
    assert result.causes[0].summary == "The header hides its own content."
    assert result.causes[1].summary == other.summary, "a cause nobody wrote about keeps its text"
    assert "rc-404" in (result.error or "")


def test_an_overlong_sentence_is_rejected() -> None:
    item, findings = one_cause()
    client = narrated(
        {"causes": [{"id": "rc-1", "summary": "x" * (MAX_SUMMARY_CHARS + 1), "rationale": "y"}]}
    )
    result = asyncio.run(narrate([item], findings, client=client))

    assert result.status == "rejected"
    assert result.causes[0].summary == item.summary


def test_a_reply_that_is_not_json_is_reported_rather_than_used() -> None:
    item, findings = one_cause()
    result = asyncio.run(
        narrate([item], findings, client=StubClient(content="I think the header is bad."))
    )

    assert result.status == "unusable_reply"
    assert result.causes[0].summary == item.summary
    assert result.tokens_in == 1200, "the call happened, so its tokens are still measured"


def test_a_provider_failure_leaves_the_measured_text() -> None:
    item, findings = one_cause()
    result = asyncio.run(narrate([item], findings, client=StubClient(error=LlmError("no API key"))))

    assert result.status == "llm_error"
    assert result.causes[0].summary == item.summary
    assert result.tokens_in == 0


def test_no_cause_means_no_call() -> None:
    result = asyncio.run(narrate([], {}, client=StubClient(content="{}")))

    assert result.status == "skipped"
    assert result.llm_calls == 0


def test_apply_narration_does_not_need_a_client() -> None:
    """The pure half is testable without a model: this is what a reviewer reads first."""
    item, findings = one_cause()
    facts = cause_facts(item, findings)
    narrated, accepted, reasons = apply_narration(
        [item],
        {"causes": [{"id": "rc-1", "summary": "Header hides content.", "rationale": "Fix it."}]},
        {"rc-1": facts},
        {"rc-1": allowed_numbers(facts, facts["rules"])},
    )

    assert accepted == 1 and reasons == []
    assert narrated[0].rationale == "Fix it."
    assert narrated[0].finding_ids == item.finding_ids


def test_the_switch_and_the_cassette_both_keep_the_model_out() -> None:
    """Narration stays silent three ways: asked to, a cassette owns the conversation, no cluster."""
    item, findings = one_cause()

    class Forbidden:
        async def complete(self, **_: object) -> LlmReply:  # pragma: no cover - must not run
            raise AssertionError("no model call belongs here")

    def call(settings: Settings, causes: list) -> object:
        import app.audit as audit_module

        original = audit_module.OpenAiCompatibleClient
        audit_module.OpenAiCompatibleClient = lambda **_: Forbidden()  # type: ignore[assignment]
        try:
            return asyncio.run(
                explain_causes(
                    causes,
                    list(findings.values()),
                    settings=settings,
                    trace=Tracer(),
                    audit_id=uuid.uuid4(),
                )
            )
        finally:
            audit_module.OpenAiCompatibleClient = original  # type: ignore[assignment]

    assert call(Settings(chief_narration=False), [item]) is None
    assert call(Settings(chief_narration=True, llm_cassette="/tmp/recorded.json"), [item]) is None
    assert call(Settings(chief_narration=True), []) is None


def test_a_failed_narration_is_a_failed_span() -> None:
    """The trace shows the call that failed, not only the ones that worked."""
    item, findings = one_cause()
    trace = Tracer()

    class Failing:
        model = "stub"

        async def complete(self, **_: object) -> LlmReply:  # pragma: no cover - raises
            raise LlmError("provider down")

    import app.audit as audit_module

    original = audit_module.OpenAiCompatibleClient
    audit_module.OpenAiCompatibleClient = lambda **_: Failing()  # type: ignore[assignment]
    try:
        result = asyncio.run(
            explain_causes(
                [item],
                list(findings.values()),
                settings=Settings(chief_narration=True, llm_api_key="test-key", llm_cassette=""),
                trace=trace,
                audit_id=uuid.uuid4(),
            )
        )
    finally:
        audit_module.OpenAiCompatibleClient = original  # type: ignore[assignment]

    assert result is not None and result.status == "llm_error"
    spans = [record for record in trace.spans if record.name == "chief.narration"]
    assert len(spans) == 1
    assert spans[0].status == "error"
    assert "provider down" in (spans[0].error or "")


def test_the_digest_covers_the_instructions_appended_in_python() -> None:
    """Hashing only chief.md would let an edit to the appended rules keep the old version."""
    import hashlib

    file_only = hashlib.sha256(prompt_text().encode("utf-8")).hexdigest()[:16]

    assert prompt_digest_sha() != file_only


def test_the_rejection_count_is_recorded_when_every_cause_is_rejected() -> None:
    item, findings = one_cause()
    client = narrated(
        {"causes": [{"id": "rc-1", "summary": "41 visitors cannot read it", "rationale": "x"}]}
    )
    result = asyncio.run(narrate([item], findings, client=client))

    assert result.status == "rejected"
    assert result.rejected == 1, "a rejected narration is counted, not silently zero"


def test_the_rule_text_travels_with_the_facts() -> None:
    """The model may repeat a standard's constants, so it has to see the standard."""
    item = finding(rule_id="A11Y-CONTRAST")
    facts = cause_facts(cause(finding_ids=[item.id]), {item.id: item})

    text = " ".join(entry["text"] for entry in facts["rule_text"])
    assert "4.5:1" in text
    assert facts["rule_text"][0]["id"] == "A11Y-CONTRAST"


def _agent(status: str, cost: float | None) -> AgentRun:
    return AgentRun(name="a11y", status=status, model="m", cost_estimate_usd=cost)


def test_narration_is_skipped_once_the_ceiling_stopped_the_agents() -> None:
    settings = Settings(chief_narration=True, audit_cost_limit_usd=0.25)

    assert narration_is_affordable(OrchestrationResult(runs=[_agent("ok", 0.01)]), settings)
    assert not narration_is_affordable(
        OrchestrationResult(runs=[_agent("budget_exceeded", 0.30)]), settings
    ), "a stopped agent means the audit is at its ceiling"
    assert not narration_is_affordable(OrchestrationResult(runs=[_agent("ok", 0.25)]), settings), (
        "spent up to the ceiling leaves no room for another call"
    )
    assert narration_is_affordable(
        OrchestrationResult(runs=[_agent("ok", None)]), Settings(audit_cost_limit_usd=None)
    ), "no ceiling means no skip"
