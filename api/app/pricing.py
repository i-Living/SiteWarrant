"""Prices, and the honest limits of a price list.

`cost_estimate_usd` is an estimate computed from a versioned price file; token counts are measured.
An unpriced model gets `None`, never `0.0`: a zero would read as "this run was free", which is a
claim nobody made.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PRICING_PATH = Path(__file__).resolve().parents[2] / "pricing" / "pricing.yaml"
PER_TOKENS = 1_000_000
BASIS = (
    "list price for the same model and tokens; the subscription plan bills a flat fee, so this is "
    "not an invoice"
)


class PricingError(ValueError):
    """The price file cannot be used."""


@dataclass(frozen=True)
class Price:
    model: str
    input_usd_per_1m: float
    output_usd_per_1m: float

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        """Round at the last step only: a per-call rounding would drift over 80 pages."""
        return round(
            tokens_in / PER_TOKENS * self.input_usd_per_1m
            + tokens_out / PER_TOKENS * self.output_usd_per_1m,
            6,
        )

    def digest_payload(self) -> str:
        return json.dumps(
            [self.model, self.input_usd_per_1m, self.output_usd_per_1m], sort_keys=True
        )


@dataclass(frozen=True)
class Pricing:
    version: str
    currency: str
    models: dict[str, Price]
    sources: tuple[str, ...] = ()

    def price_for(self, model: str) -> Price | None:
        return self.models.get(model)

    def estimate(self, model: str, tokens_in: int, tokens_out: int) -> float | None:
        price = self.price_for(model)
        if price is None:
            return None
        return price.cost(tokens_in, tokens_out)

    def unpriced(self, models: list[str]) -> list[str]:
        return sorted({model for model in models if model not in self.models})


def load_pricing(path: Path | None = None) -> Pricing:
    target = path or DEFAULT_PRICING_PATH
    if not target.is_file():
        raise PricingError(f"{target} does not exist")
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise PricingError(
            "pricing needs a version: an audit records the version it was priced with"
        )
    models_payload = payload.get("models") or {}
    if not isinstance(models_payload, dict) or not models_payload:
        raise PricingError("pricing needs at least one model")
    models: dict[str, Price] = {}
    for name, entry in models_payload.items():
        if not isinstance(entry, dict):
            raise PricingError(f"{name}: a model entry must be a mapping")
        try:
            rate_in = float(entry["input"])
            rate_out = float(entry["output"])
        except (KeyError, TypeError, ValueError) as error:
            raise PricingError(f"{name}: input and output must be numbers") from error
        if rate_in < 0 or rate_out < 0:
            raise PricingError(f"{name}: prices cannot be negative")
        models[name] = Price(model=name, input_usd_per_1m=rate_in, output_usd_per_1m=rate_out)
    sources = tuple(
        str(item.get("url", "")) for item in payload.get("sources", []) if isinstance(item, dict)
    )
    return Pricing(
        version=version,
        currency=str(payload.get("currency", "USD")),
        models=models,
        sources=sources,
    )


@lru_cache(maxsize=1)
def pricing() -> Pricing:
    return load_pricing()


def pricing_version() -> str:
    return pricing().version
