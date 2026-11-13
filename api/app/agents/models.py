from typing import Any

from pydantic import BaseModel, Field

from app.rules.catalog import Category, Impact, Severity


class EvidenceRef(BaseModel):
    """A pointer to a stored fact. The id is the only thing that makes a claim checkable."""

    observation_id: str
    kind: str
    excerpt: str | None = None


class CandidateFinding(BaseModel):
    """What an agent is allowed to propose, before the validator sees it.

    Deliberately narrow: no free-form numbers, no root cause, no score. Everything the agent
    asserts has to be traceable to an observation, and the validator is the only thing that
    turns a candidate into a finding.
    """

    rule_id: str = Field(
        description="A claim id from the rule corpus, for example SEC-CSP-MISSING."
    )
    category: Category
    severity: Severity
    title: str = Field(max_length=160)
    summary: str = Field(max_length=600)
    suggested_fix: str = Field(max_length=600)
    impact: Impact = Field(default_factory=Impact)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # What the finding is about (an element, a URL). Two findings may cite one observation —
    # two small targets, one responsive report — and only a subject tells them apart.
    subject: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=10)
    criterion: str | None = Field(
        default=None, description="For accessibility findings: the WCAG criterion id."
    )


class ObservationFacts(BaseModel):
    """The facts an agent may cite, as the validator sees them."""

    tool: str
    kind: str
    rule_ref: str | None = None
    viewport: str | None = None
    payload: dict[str, Any]


class Rejection(BaseModel):
    rule_id: str
    reasons: list[str]


class ValidationResult(BaseModel):
    accepted: list[CandidateFinding]
    rejected: list[Rejection]

    @property
    def ok(self) -> bool:
        return not self.rejected


class AgentBudget(BaseModel):
    """Hard limits per agent, from docs/PLAN.md section 6."""

    max_tool_calls: int = 12
    max_tokens: int = 60_000
    timeout_s: float = 180.0


class AgentSpec(BaseModel):
    name: str
    category: Category
    prompt_file: str
    tools: tuple[str, ...]
    budget: AgentBudget = Field(default_factory=AgentBudget)


class LlmCallStat(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class AgentRun(BaseModel):
    """What one agent did, whether it succeeded, and what it cost."""

    name: str
    status: str
    # Which model produced this, and what its tokens would cost at the price file in force.
    model: str = ""
    cost_estimate_usd: float | None = None
    accepted: list[CandidateFinding] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    latency_ms: int = 0
    error: str | None = None
    calls: list[LlmCallStat] = Field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status != "ok"


class OrchestrationResult(BaseModel):
    runs: list[AgentRun]

    @property
    def partial(self) -> bool:
        return any(run.failed for run in self.runs)

    @property
    def status(self) -> str:
        if not self.runs:
            return "completed"
        return "partial" if self.partial else "completed"
