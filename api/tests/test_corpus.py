from app.rules import corpus


def test_the_corpus_has_claims_and_criteria() -> None:
    assert len(corpus.claims()) >= 20
    assert len(corpus.criteria()) >= 10


def test_every_claim_names_its_category_and_the_channels_it_may_cite() -> None:
    for claim in corpus.claims():
        assert claim.category is not None, claim.id
        assert claim.severity is not None, claim.id
        assert claim.observation_tools, claim.id
        for tool in claim.observation_tools:
            assert tool in {
                "http",
                "dom",
                "axe",
                "contrast",
                "responsive",
                "occlusion",
                "performance",
                "screenshot",
            }, claim.id


def test_every_claim_that_names_a_criterion_names_a_real_one() -> None:
    for claim in corpus.claims():
        if claim.wcag is not None:
            assert corpus.criterion_by_id(claim.wcag) is not None, claim.id


def test_ids_are_unique() -> None:
    ids = [entry.id for entry in corpus.entries()]
    assert len(ids) == len(set(ids))


def test_retrieval_finds_the_contrast_criterion() -> None:
    hits = corpus.search("contrast ratio of text on a background", limit=3)
    assert hits[0].id == "WCAG-1.4.3"


def test_retrieval_finds_the_canonical_claim() -> None:
    hits = corpus.search("canonical url duplicates", limit=3)
    assert any(hit.id == "SEO-CANONICAL" for hit in hits)


def test_retrieval_is_deterministic() -> None:
    first = [entry.id for entry in corpus.search("security headers csp", limit=5)]
    second = [entry.id for entry in corpus.search("security headers csp", limit=5)]
    assert first == second


def test_embedding_is_normalized_and_stable() -> None:
    vector = corpus.embed("contrast ratio")
    assert abs(sum(value * value for value in vector) - 1.0) < 1e-9
    assert vector == corpus.embed("contrast ratio")
    assert vector != corpus.embed("canonical url")


def test_the_digest_is_stable_across_reloads() -> None:
    before = corpus.corpus_digest()
    corpus.entries.cache_clear()
    corpus._vectors.cache_clear()
    assert corpus.corpus_digest() == before


def test_the_digest_covers_fields_beyond_the_text(monkeypatch) -> None:
    """An edit to the citation channels or the criterion has to change the digest."""
    original = corpus.entries()
    before = corpus.corpus_digest()

    changed = [entry.model_copy(deep=True) for entry in original]
    target = next(entry for entry in changed if entry.kind == "claim")
    target.observation_tools = (*target.observation_tools, "performance")

    monkeypatch.setattr(corpus, "entries", lambda: tuple(changed))
    assert corpus.corpus_digest() != before
