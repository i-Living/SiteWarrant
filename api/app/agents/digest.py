import json
from collections.abc import Sequence

from app.agents.models import ObservationFacts

MAX_ENTRY_CHARS = 1200
MAX_DIGEST_CHARS = 14_000
# The order the digest presents channels in: the ones most agents need first.
CHANNEL_ORDER = (
    "http",
    "dom",
    "axe",
    "contrast",
    "responsive",
    "occlusion",
    "performance",
    "screenshot",
)


def observation_line(observation_id: str, facts: ObservationFacts) -> str:
    where = f" at {facts.viewport}" if facts.viewport else ""
    payload = json.dumps(facts.payload, ensure_ascii=False, sort_keys=True)
    if len(payload) > MAX_ENTRY_CHARS:
        payload = payload[:MAX_ENTRY_CHARS] + "…(truncated)"
    return (
        f"- observation_id={observation_id} tool={facts.tool} kind={facts.kind}"
        f" rule_ref={facts.rule_ref or '-'}{where}\n  {payload}"
    )


def build_digest(
    observations: Sequence[tuple[str, ObservationFacts]], *, max_chars: int = MAX_DIGEST_CHARS
) -> str:
    """Every fact with its id, in a stable order, cut at a budget.

    The digest is context, not evidence: an agent may cite any observation id it sees here,
    and the validator checks the citation against the database, not against this text.
    """
    ordered = sorted(
        observations,
        key=lambda pair: (
            CHANNEL_ORDER.index(pair[1].tool) if pair[1].tool in CHANNEL_ORDER else 99,
            pair[1].tool,
            pair[1].viewport or "",
            pair[0],
        ),
    )
    lines: list[str] = []
    total = 0
    for observation_id, facts in ordered:
        line = observation_line(observation_id, facts)
        if total + len(line) > max_chars:
            lines.append(f"- ({len(ordered) - len(lines)} more observation(s) omitted; ask a tool)")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
