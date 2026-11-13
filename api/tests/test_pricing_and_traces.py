import pytest

from app.pricing import PricingError, load_pricing
from app.telemetry import Tracer, current_span_id, current_trace_id


def test_a_price_is_per_million_tokens() -> None:
    pricing = load_pricing()
    price = pricing.price_for("deepseek-v4.1-flash")
    assert price is not None
    assert price.cost(1_000_000, 0) == pytest.approx(price.input_usd_per_1m)
    assert price.cost(0, 1_000_000) == pytest.approx(price.output_usd_per_1m)
    assert price.cost(0, 0) == 0.0


def test_cost_is_rounded_once_not_per_call() -> None:
    price = load_pricing().price_for("deepseek-v4.1-flash")
    assert price is not None
    once = price.cost(120_000, 4_000)
    # A hundred small calls must add up to the same number as one big call.
    parts = sum(price.cost(1_200, 40) for _ in range(100))
    assert abs(parts - once) < 1e-6


def test_an_unpriced_model_costs_none_not_zero() -> None:
    pricing = load_pricing()
    assert pricing.price_for("some-model-nobody-priced") is None
    assert pricing.estimate("some-model-nobody-priced", 1000, 1000) is None
    assert pricing.unpriced(["deepseek-v4.1-flash", "ghost-model"]) == ["ghost-model"]


def test_pricing_carries_the_version_an_audit_records() -> None:
    pricing = load_pricing()
    assert pricing.version
    assert pricing.currency == "USD"
    assert pricing.sources and pricing.sources[0].startswith("https://")


def test_a_price_file_without_a_version_is_refused(tmp_path) -> None:
    broken = tmp_path / "pricing.yaml"
    broken.write_text("models:\n  x:\n    input: 1\n    output: 2\n", encoding="utf-8")
    with pytest.raises(PricingError, match="version"):
        load_pricing(broken)


def test_a_negative_price_is_refused(tmp_path) -> None:
    broken = tmp_path / "pricing.yaml"
    broken.write_text(
        'version: "1"\nmodels:\n  x:\n    input: -1\n    output: 2\n', encoding="utf-8"
    )
    with pytest.raises(PricingError, match="negative"):
        load_pricing(broken)


def test_spans_nest_and_carry_the_trace() -> None:
    tracer = Tracer()
    assert current_trace_id() is None
    with tracer.span("audit", site="http://x/") as audit:
        with tracer.span("agent", agent="seo") as agent:
            with tracer.span("llm.call", model="m") as call:
                assert current_trace_id() == tracer.trace_id
                assert current_span_id() == call.span_id
                assert agent.span_id == call.parent_id
            assert current_span_id() == agent.span_id
        assert agent.parent_id == audit.span_id
    assert current_span_id() is None
    assert current_trace_id() is None
    assert [span.name for span in tracer.spans] == ["llm.call", "agent", "audit"]


def test_a_failing_span_is_recorded_with_its_error() -> None:
    tracer = Tracer()
    with pytest.raises(RuntimeError), tracer.span("tool.call", tool="list_pages"):
        raise RuntimeError("mcp died")
    span = tracer.spans[0]
    assert span.status == "error"
    assert "mcp died" in (span.error or "")
    assert span.duration_ms >= 0


def test_the_trace_is_written_as_json_lines() -> None:
    tracer = Tracer()
    with tracer.span("audit"), tracer.span("page", viewport="390x844"):
        pass
    lines = tracer.to_jsonl().strip().splitlines()
    assert len(lines) == 2
    assert all('"trace_id"' in line for line in lines)
    assert tracer.summary() == {"audit": 1, "page": 1}
