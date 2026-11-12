import pytest

from app.agents.specs import SPECS, parse_agent_names


def test_a_repeated_agent_runs_once() -> None:
    """Running the same agent twice doubles the cost and duplicates its findings."""
    assert parse_agent_names("a11y,a11y,seo") == ["a11y", "seo"]


def test_all_means_every_agent_even_beside_a_name() -> None:
    assert parse_agent_names("all,a11y") == list(SPECS)


def test_an_unknown_agent_is_rejected_loudly() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        parse_agent_names("a11y,nope")


def test_names_are_case_and_space_insensitive() -> None:
    assert parse_agent_names(" A11Y , seo ") == ["a11y", "seo"]
