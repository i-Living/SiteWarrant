from app.agents.models import AgentBudget, AgentSpec
from app.rules.catalog import Category

# One loop, eight briefs. The tool list per agent is the plan's table in docs/PLAN.md
# section 6: an agent that cannot read the contrast channel cannot claim a contrast problem.
SPECS: dict[str, AgentSpec] = {
    "seo": AgentSpec(
        name="seo",
        category="seo",
        prompt_file="seo.md",
        tools=("list_observations", "get_observation", "channel_report", "rules_lookup"),
    ),
    "a11y": AgentSpec(
        name="a11y",
        category="a11y",
        prompt_file="a11y.md",
        tools=("list_observations", "get_observation", "channel_report", "rules_lookup"),
    ),
    "performance": AgentSpec(
        name="performance",
        category="performance",
        prompt_file="performance.md",
        tools=("channel_report", "list_observations", "rules_lookup"),
    ),
    "security": AgentSpec(
        name="security",
        category="security",
        prompt_file="security.md",
        tools=("list_observations", "get_observation", "rules_lookup"),
    ),
    "ui": AgentSpec(
        name="ui",
        category="ui",
        prompt_file="ui.md",
        tools=("channel_report", "list_observations"),
    ),
    "ux": AgentSpec(
        name="ux",
        category="ux",
        prompt_file="ux.md",
        tools=("list_observations", "channel_report", "get_observation"),
    ),
    "responsive": AgentSpec(
        name="responsive",
        category="responsive",
        prompt_file="responsive.md",
        tools=("channel_report", "list_observations"),
    ),
    "conversion": AgentSpec(
        name="conversion",
        category="conversion",
        prompt_file="conversion.md",
        tools=("channel_report", "list_observations", "get_observation"),
    ),
}

DEFAULT_BUDGET = AgentBudget()


def parse_agent_names(value: str) -> list[str]:
    """Read `--agents seo,a11y` and `--agents all`, rejecting unknown names loudly."""
    names = [item.strip().lower() for item in value.split(",") if item.strip()]
    if names == ["all"]:
        return list(SPECS)
    unknown = [name for name in names if name not in SPECS]
    if unknown:
        raise ValueError(
            f"unknown agent(s): {', '.join(unknown)}; known: {', '.join(SPECS)} or all"
        )
    return names


def spec_for(name: str) -> AgentSpec:
    return SPECS[name]


def category_of(name: str) -> Category:
    return SPECS[name].category
