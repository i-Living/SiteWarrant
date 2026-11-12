import hashlib
from pathlib import Path

from app.agents.models import AgentSpec
from app.rules import corpus
from app.rules.catalog import Category

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

SHARED_RULES = """\
You are one auditor inside SiteWarrant, a tool that measures websites and reports what is
wrong with evidence. You do not measure anything yourself: the measurements already exist as
observations, and every claim you make must point at one.

Non-negotiable rules:
1. Cite observations by id in `evidence`. A finding without a citation to an observation of
   this audit is rejected and never reaches the report.
2. `evidence.kind` is the channel the observation came from (`dom`, `axe`, `contrast`, `http`,
   `responsive`, `occlusion`, `performance`, `screenshot`) and must match the observation's tool.
   Never state a number that is not in the cited observation payload. Write counts and
   measurements as digits. The validator compares each number you write against the payloads
   you cite and rejects the finding when one does not match.
3. Use a `rule_id` from the claim list below. A claim that is not in the list is not ours to
   make, and inventing one is rejected.
4. You may raise severity above the claim default when the evidence supports it. You may not
   lower it.
5. Submit with the `submit_findings` tool. If the validator rejects a finding, read the
   reasons, fix the citation or the wording, and submit again.
6. If the page is clean for your category, submit an empty list. An empty result is a valid
   answer; a padded report is not.
7. When one observation supports several distinct findings (two small targets in one responsive
   report), set `subject` to the element or URL each finding is about, copied from the
   observation. A subject the observation does not contain does not distinguish anything: the
   same claim filed twice is one finding, and the second copy is dropped.
"""


def claim_list(category: Category) -> str:
    lines = []
    for claim in corpus.claims_for(category):
        tools = "/".join(claim.observation_tools) or "any"
        lines.append(
            f"- {claim.id} (severity {claim.severity}, evidence from {tools}): {claim.title}\n"
            f"  {claim.body}"
        )
    return "\n".join(lines) if lines else "- (no claims in this category)"


def criteria_list(claim_ids: list[str]) -> str:
    wanted = {claim.wcag for claim in corpus.claims() if claim.id in claim_ids and claim.wcag}
    lines = []
    for criterion in corpus.criteria():
        if criterion.id in wanted:
            lines.append(f"- {criterion.id} {criterion.title}: {criterion.body}")
    return "\n".join(lines)


def system_prompt(spec: AgentSpec, *, facts_digest: str) -> str:
    """The full system prompt: shared rules, this agent's brief, its claims and the facts."""
    brief = (PROMPT_DIR / spec.prompt_file).read_text(encoding="utf-8").strip()
    claim_ids = [claim.id for claim in corpus.claims_for(spec.category)]
    criteria = criteria_list(claim_ids)
    parts = [
        SHARED_RULES,
        f"# Your brief\n{brief}",
        f"# Claims you may file ({spec.category})\n{claim_list(spec.category)}",
    ]
    if criteria:
        parts.append(f"# WCAG criteria these claims rest on\n{criteria}")
    parts.append(f"# Observations for this page\n{facts_digest}")
    return "\n\n".join(parts)


def user_prompt() -> str:
    return (
        "Audit this page for your category using the observations above. Call the tools when "
        "you need a fact that is not in the digest, then submit your findings with "
        "`submit_findings`."
    )


def prompts_digest() -> str:
    """Digest of everything that reaches the model as instructions.

    The Markdown briefs are only part of it: SHARED_RULES and user_prompt() are sent on every
    call, so editing either has to change agent_version as well.
    """
    parts = [SHARED_RULES, user_prompt()]
    parts.extend(
        f"{path.name}\t{path.read_text(encoding='utf-8')}"
        for path in sorted(PROMPT_DIR.glob("*.md"))
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
