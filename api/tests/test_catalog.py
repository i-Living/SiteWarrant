from app.rules.catalog import RULES, rule_by_match


def test_rule_ids_are_unique() -> None:
    ids = [rule.id for rule in RULES]
    assert len(ids) == len(set(ids))


def test_matches_are_unique_per_source() -> None:
    keys = [(rule.source, rule.match) for rule in RULES]
    assert len(keys) == len(set(keys))


def test_every_rule_states_its_case() -> None:
    for rule in RULES:
        assert rule.title.strip()
        assert rule.summary.strip()
        assert rule.suggested_fix.strip()


def test_every_source_is_covered() -> None:
    """Each measured channel that has a rule is named, and no rule comes from nowhere."""
    assert {rule.source for rule in RULES} == {"axe", "dom", "occlusion"}
    for source in ("axe", "dom", "occlusion"):
        assert any(rule.source == source for rule in RULES)


def test_the_occlusion_rule_consumes_its_own_channel() -> None:
    rule = next(rule for rule in RULES if rule.id == "LAYOUT-OCCLUSION")
    assert rule.category == "responsive"
    assert rule_by_match("occlusion", rule.match) is rule


def test_rule_by_match_rejects_unknown_rule() -> None:
    assert rule_by_match("axe", "not-a-real-rule") is None
    assert rule_by_match("dom", "not-a-real-check") is None
