"""Chief Auditor narration: the model explains clusters the deterministic layer already built.

The grouping, the membership and the priority are decided in `app/chief/cluster.py` and never
here. This module asks for prose about a cluster that exists, and accepts it only when the prose
names no number the cluster's own facts do not contain — a narration that invents a measurement
would be indistinguishable from a finding, and the report must not gain one this way
(docs/PLAN.md section 6, invariants 1 and 3).

A rejected narration, a broken reply or an unreachable provider leaves the deterministic
`summary` and `rationale` in place: the audit reports fewer words, never fewer facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.llm import LlmClient, LlmError
from app.agents.models import LlmCallStat
from app.agents.validator import claimed_numbers, number_is_corroborated, payload_numbers
from app.core.report import FindingOut, RootCauseOut
from app.rules import corpus
from app.rules.catalog import RULES

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
MAX_SUMMARY_CHARS = 280
MAX_RATIONALE_CHARS = 600
# One cluster per cause, but a report with forty of them does not need forty paragraphs in one
# call: the eight with the highest priority speak for the page.
MAX_NARRATED_CAUSES = 8
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
# The instructions appended in Python are part of the brief, so they are part of its digest too:
# editing a sentence here has to move `agent_version` exactly like editing chief.md does.
SYSTEM_SUFFIX = (
    "Every id you answer must be one of the ids below. A number you write must appear in "
    "that cause's facts or in the rule text quoted with it."
)
USER_PROMPT_LEAD = "Clusters found in this audit, already grouped by the deterministic layer:"


@dataclass
class NarrationCall:
    """What the narration did, whether it was accepted, and what it cost."""

    causes: list[RootCauseOut]
    status: str = "skipped"
    accepted: int = 0
    rejected: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    latency_ms: int = 0
    error: str | None = None
    calls: list[LlmCallStat] = field(default_factory=list)


def prompt_text() -> str:
    """The brief, read like every other prompt in this repository."""
    return (PROMPT_DIR / "chief.md").read_text(encoding="utf-8").strip()


def prompt_digest_sha() -> str:
    """The narration prompt is part of `agent_version`: different brief, different agent.

    The brief is the file plus the sentences this module appends to it; hashing only the file would
    let an edit to the appended instructions keep the old version string.
    """
    parts = [prompt_text(), SYSTEM_SUFFIX, USER_PROMPT_LEAD]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def cause_facts(cause: RootCauseOut, findings: Mapping[str, FindingOut]) -> dict[str, Any]:
    """The facts a cluster may be described with. Nothing else is allowed into the call."""
    members = [findings[finding_id] for finding_id in cause.finding_ids if finding_id in findings]
    rules = sorted({finding.rule_id for finding in members})
    return {
        "id": cause.id,
        "anchor": cause.anchor,
        "label": cause.label,
        "categories": list(cause.categories),
        "severity": cause.severity,
        "priority": cause.priority,
        "findings": len(members),
        "categories_count": len(cause.categories),
        "rules": rules,
        "rule_text": _rule_text(rules),
        "subjects": sorted({finding.subject for finding in members if finding.subject})[:5],
        "titles": sorted({finding.title for finding in members})[:5],
    }


def _rule_text(rule_ids: Sequence[str]) -> list[dict[str, str]]:
    """The claim text behind each rule, because its constants are what the model may repeat.

    The model is told that a number has to come from the cluster or from the rule; without the rule
    text it could only guess which constants exist, and the validator would reject a number it was
    allowed to use. The fix is part of the claim — `SEO-TITLE` says "between 30 and 60 characters" —
    and `allowed_numbers` reads it too, so omitting it here would permit a number the model cannot
    see.
    """
    wanted = set(rule_ids)
    entries = [
        {
            "id": rule.id,
            "title": rule.title,
            "text": rule.summary,
            "fix": rule.suggested_fix,
        }
        for rule in RULES
        if rule.id in wanted
    ]
    entries.extend(
        {"id": entry.id, "title": entry.title, "text": entry.body}
        for entry in corpus.claims()
        if entry.id in wanted
    )
    return entries


def allowed_numbers(facts: Mapping[str, Any], rule_ids: Sequence[str]) -> list[float]:
    """Measured numbers from the cluster, plus the constants its own claims carry.

    "24 by 24 CSS pixels" and "4.5:1" are the rule, not a measurement of this page, so repeating
    one is allowed exactly as it is inside a finding (docs/PLAN.md section 6). The text comes from
    two places because a finding can name either a catalogue rule (`A11Y-CONTRAST`) or a corpus
    claim (`A11Y-TARGET-SIZE`); both are the claim behind the text the report already shows.
    """
    wanted = set(rule_ids)
    values = payload_numbers(dict(facts))
    for rule in RULES:
        if rule.id in wanted:
            values.extend(payload_numbers({"title": rule.title, "summary": rule.summary}))
            values.extend(payload_numbers({"fix": rule.suggested_fix}))
    for entry in corpus.claims():
        if entry.id in wanted:
            values.extend(payload_numbers({"title": entry.title, "body": entry.body}))
    return values


def narration_system_prompt() -> str:
    return f"{prompt_text()}\n\n{SYSTEM_SUFFIX}"


def narration_user_prompt(facts: Sequence[Mapping[str, Any]]) -> str:
    return (
        f"{USER_PROMPT_LEAD}\n"
        f"{json.dumps(list(facts), ensure_ascii=False, indent=1, sort_keys=True)}"
    )


def _clean(text: Any, limit: int) -> str | None:
    if not isinstance(text, str):
        return None
    collapsed = " ".join(text.split())
    if not collapsed or len(collapsed) > limit:
        return None
    return collapsed


def _parse_json(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None
    body = FENCE.sub("", content).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(body[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _rejection(summary: str | None, rationale: str | None, numbers: Sequence[float]) -> str | None:
    """Why a piece of prose cannot stand in the report, or None when it can."""
    if summary is None:
        return f"empty or longer than {MAX_SUMMARY_CHARS} characters"
    if rationale is None:
        return f"empty or longer than {MAX_RATIONALE_CHARS} characters"
    for text in (summary, rationale):
        for claimed in claimed_numbers(text):
            if not number_is_corroborated(claimed, numbers):
                return f"number {claimed} is not in this cluster's facts"
    return None


def apply_narration(
    causes: Sequence[RootCauseOut],
    payload: dict[str, Any],
    facts_by_id: Mapping[str, dict[str, Any]],
    numbers_by_id: Mapping[str, Sequence[float]],
) -> tuple[list[RootCauseOut], int, list[str]]:
    """Keep the prose that could be checked, drop the rest, and say why."""
    entries = payload.get("causes")
    if not isinstance(entries, list):
        return list(causes), 0, ["the reply carried no `causes` list"]
    written: dict[str, tuple[str, str]] = {}
    reasons: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cause_id = entry.get("id")
        if not isinstance(cause_id, str) or cause_id not in facts_by_id:
            reasons.append(f"unknown cause id {cause_id!r}")
            continue
        summary = _clean(entry.get("summary"), MAX_SUMMARY_CHARS)
        rationale = _clean(entry.get("rationale"), MAX_RATIONALE_CHARS)
        rejection = _rejection(summary, rationale, numbers_by_id[cause_id])
        if rejection is not None:
            reasons.append(f"{cause_id}: {rejection}")
            continue
        written[cause_id] = (summary or "", rationale or "")
    narrated = [
        cause.model_copy(
            update={"summary": written[cause.id][0], "rationale": written[cause.id][1]}
        )
        if cause.id in written
        else cause
        for cause in causes
    ]
    return narrated, len(written), reasons


async def narrate(
    causes: Sequence[RootCauseOut],
    findings: Mapping[str, FindingOut],
    *,
    client: LlmClient,
    model: str = "",
    timeout_s: float = 120.0,
) -> NarrationCall:
    """One model call about the clusters that already exist. Never raises."""
    unchanged = list(causes)
    if not unchanged:
        return NarrationCall(causes=unchanged, status="skipped", error="no root cause to explain")
    selected = unchanged[:MAX_NARRATED_CAUSES]
    facts = [cause_facts(cause, findings) for cause in selected]
    numbers = {str(item["id"]): allowed_numbers(item, item["rules"]) for item in facts}
    started = asyncio.get_running_loop().time()
    try:
        async with asyncio.timeout(timeout_s):
            reply = await client.complete(
                messages=[
                    {"role": "system", "content": narration_system_prompt()},
                    {"role": "user", "content": narration_user_prompt(facts)},
                ],
                tools=[],
            )
    except TimeoutError:
        return NarrationCall(
            causes=unchanged,
            status="timeout",
            error=f"the model did not answer within {timeout_s:.0f} s",
        )
    except LlmError as error:
        return NarrationCall(causes=unchanged, status="llm_error", error=str(error)[:500])
    latency_ms = int((asyncio.get_running_loop().time() - started) * 1000)

    def result(**update: Any) -> NarrationCall:
        measured = reply.latency_ms or latency_ms
        return NarrationCall(
            causes=update.pop("causes", unchanged),
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
            llm_calls=1,
            latency_ms=measured,
            calls=[
                LlmCallStat(
                    tokens_in=reply.tokens_in, tokens_out=reply.tokens_out, latency_ms=measured
                )
            ],
            **update,
        )

    payload = _parse_json(reply.content)
    if payload is None:
        return result(status="unusable_reply", error="the reply was not JSON")
    narrated, accepted, reasons = apply_narration(
        unchanged,
        payload,
        {str(item["id"]): item for item in facts},
        numbers,
    )
    if accepted == 0:
        return result(
            causes=narrated,
            status="rejected",
            rejected=len(selected),
            error="; ".join(reasons)[:500],
        )
    return result(
        causes=narrated,
        status="ok",
        accepted=accepted,
        rejected=max(0, len(selected) - accepted),
        error="; ".join(reasons)[:500] or None,
    )


def findings_by_id(findings: Sequence[FindingOut]) -> dict[str, FindingOut]:
    return {finding.id: finding for finding in findings}
